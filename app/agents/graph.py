import logging
import os
import socket
import uuid
from urllib.parse import urlparse

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from app.agents.approval import approval_node
from app.agents.execute import execute_node
from app.agents.observability import observability_node
from app.agents.rag import rag_node
from app.agents.rca import rca_node
from app.agents.remediation import remediation_node
from app.agents.state import IncidentState
from app.agents.triage import triage_node
from app.agents.verify import verify_node

log = logging.getLogger(__name__)


def _approval_router(state: dict) -> str:
    # rejected ends here. everything else flows into execute, which the
    # checkpointer pauses in front of until a human (or auto-approval) resumes.
    if state.get("approval_status") == "rejected":
        return END
    return "execute"


def _confidence_router(state: dict) -> str:
    if state.get("confidence", 0) >= 0.8 or state.get("investigation_loops", 0) >= 3:
        return "remediation"
    return "observability"


def _verify_router(state: dict) -> str:
    if (state.get("verification_result") or {}).get("healthy"):
        return END
    if state.get("executions", 0) >= 2:
        return END  # tried twice, stop retrying without a human looking
    if state.get("investigation_loops", 0) >= 3:
        return END
    return "remediation"


def _tcp_reachable(dsn: str) -> bool:
    try:
        parts = urlparse(dsn if "://" in dsn else f"postgres://{dsn}")
        socket.create_connection((parts.hostname, parts.port or 5432), timeout=0.5).close()
        return True
    except OSError:
        return False


def _build_checkpointer():
    if os.getenv("OPSMIND_CHECKPOINTER", "auto") != "memory" and os.getenv("DATABASE_URL"):
        if _tcp_reachable(os.getenv("DATABASE_URL")):
            try:
                import psycopg
                from langgraph.checkpoint.postgres import PostgresSaver

                conn = psycopg.connect(os.getenv("DATABASE_URL"), autocommit=True)
                saver = PostgresSaver(conn)
                saver.setup()
                log.info("checkpointer: postgres")
                return saver
            except Exception as e:
                log.warning(f"postgres checkpointer unavailable, using memory: {e}")
    from langgraph.checkpoint.memory import InMemorySaver
    log.info("checkpointer: in-memory")
    return InMemorySaver()


_builder = StateGraph(IncidentState)
_builder.add_node("triage", triage_node)
_builder.add_node("observability", observability_node)
_builder.add_node("rag", rag_node)
_builder.add_node("rca", rca_node)
_builder.add_node("remediation", remediation_node)
_builder.add_node("approval", approval_node)
_builder.add_node("execute", execute_node)
_builder.add_node("verify", verify_node)
_builder.add_edge(START, "triage")
_builder.add_edge("triage", "observability")
_builder.add_edge("observability", "rag")
_builder.add_edge("rag", "rca")
_builder.add_conditional_edges("rca", _confidence_router,
                               {"remediation": "remediation", "observability": "observability"})
_builder.add_edge("remediation", "approval")
_builder.add_conditional_edges("approval", _approval_router, {"execute": "execute", END: END})
_builder.add_edge("execute", "verify")
_builder.add_conditional_edges("verify", _verify_router, {"remediation": "remediation", END: END})

ops_mind_graph = _builder.compile(checkpointer=_build_checkpointer(),
                                  interrupt_before=["execute"])


def _config(thread_id: str, callbacks=None) -> dict:
    cfg: dict = {"configurable": {"thread_id": thread_id}}
    cb = [c for c in (callbacks or []) if c is not None]
    if cb:
        cfg["callbacks"] = cb
    return cfg


def is_paused(thread_id: str) -> bool:
    return bool(ops_mind_graph.get_state(_config(thread_id)).next)


def resume(thread_id: str, callbacks=None) -> dict:
    """Resume a thread paused in front of execute. One resume == one execution;
    if verification fails the graph pauses again and needs a fresh approval."""
    return ops_mind_graph.invoke(Command(resume=True), _config(thread_id, callbacks))


def run_incident(incident: dict, thread_id: str = None, callbacks=None):
    """Run the graph for one incident. Returns (result, thread_id).

    Low-risk incidents run to completion. Medium/high-risk ones pause before
    execute with approval_status == awaiting_human; resume them with resume().
    """
    tid = thread_id or f"run-{uuid.uuid4().hex[:8]}"
    result = ops_mind_graph.invoke({"incident": incident}, _config(tid, callbacks))
    if is_paused(tid) and result.get("approval_status") == "auto_approved":
        result = resume(tid, callbacks)
    return result, tid
