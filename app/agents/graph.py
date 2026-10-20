import logging
import os
import uuid

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
from app.observability.tracing import finish_incident_span, incident_span, traced

log = logging.getLogger(__name__)


def _approval_router(state: dict) -> str:
    if state.get("approval_status") in ("rejected", "escalated", "denied"):
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
        return END
    if state.get("investigation_loops", 0) >= 3:
        return END
    return "remediation"


def _build_checkpointer():
    dsn = os.getenv("DATABASE_URL", "").strip()
    if not dsn:
        raise RuntimeError("DATABASE_URL is required (no memory fallback)")
    import psycopg
    from langgraph.checkpoint.postgres import PostgresSaver

    conn = psycopg.connect(dsn, autocommit=True)
    saver = PostgresSaver(conn)
    saver.setup()
    log.info("checkpointer: postgres")
    return saver


_builder = StateGraph(IncidentState)
_builder.add_node("triage", traced("triage", triage_node))
_builder.add_node("observability", traced("observability", observability_node))
_builder.add_node("rag", traced("rag", rag_node))
_builder.add_node("rca", traced("rca", rca_node))
_builder.add_node("remediation", traced("remediation", remediation_node))
_builder.add_node("approval", traced("approval", approval_node))
_builder.add_node("execute", traced("execute", execute_node))
_builder.add_node("verify", traced("verify", verify_node))
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
    with incident_span({"incident_id": thread_id}) as span:
        result = ops_mind_graph.invoke(Command(resume=True), _config(thread_id, callbacks))
        finish_incident_span(span, result)
        return result


def run_incident(incident: dict, thread_id: str = None, callbacks=None):
    tid = thread_id or f"run-{uuid.uuid4().hex[:8]}"
    with incident_span(incident) as span:
        result = ops_mind_graph.invoke({"incident": incident}, _config(tid, callbacks))
        if is_paused(tid) and result.get("approval_status") == "auto_approved":
            resumed = ops_mind_graph.invoke(Command(resume=True), _config(tid, callbacks))
            finish_incident_span(span, resumed)
            return resumed, tid
        finish_incident_span(span, result)
        return result, tid
