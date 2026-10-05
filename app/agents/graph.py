import logging
import os
import socket
import uuid
from urllib.parse import urlparse

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, Send

from app.agents.approval import approval_node
from app.agents.execute import execute_node
from app.agents.observability import observability_node
from app.agents.rag import rag_node
from app.agents.rca import rca_node
from app.agents.remediation import remediation_node
from app.agents.state import IncidentState
from app.agents.team import (
    INVESTIGATORS,
    get_mode,
    join,
    judge,
    logs_agent,
    metrics_agent,
    rca_change_first,
    rca_metrics_first,
    runbook_agent,
    trace_agent,
)
from app.agents.triage import triage_node
from app.agents.verify import verify_node
from app.observability.tracing import finish_incident_span, incident_span, traced

log = logging.getLogger(__name__)


def _triage_router(state: dict):
    if get_mode() == "single":
        return "observability"
    return [Send(name, {"incident": state.get("incident")}) for name in INVESTIGATORS]


def _join_router(state: dict):
    if get_mode() == "debate":
        return [Send("rca_metrics_first", {}), Send("rca_change_first", {})]
    return "rca"


def _approval_router(state: dict) -> str:
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
        return END
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
_builder.add_node("triage", traced("triage", triage_node))
_builder.add_node("observability", traced("observability", observability_node))
_builder.add_node("rag", traced("rag", rag_node))
_builder.add_node("rca", traced("rca", rca_node))
_builder.add_node("remediation", traced("remediation", remediation_node))
_builder.add_node("approval", traced("approval", approval_node))
_builder.add_node("execute", traced("execute", execute_node))
_builder.add_node("verify", traced("verify", verify_node))
_builder.add_node("metrics_agent", traced("metrics_agent", metrics_agent))
_builder.add_node("logs_agent", traced("logs_agent", logs_agent))
_builder.add_node("trace_agent", traced("trace_agent", trace_agent))
_builder.add_node("runbook_agent", traced("runbook_agent", runbook_agent))
_builder.add_node("join", traced("join", join))
_builder.add_node("rca_metrics_first", traced("rca_metrics_first", rca_metrics_first))
_builder.add_node("rca_change_first", traced("rca_change_first", rca_change_first))
_builder.add_node("judge", traced("judge", judge))
_builder.add_edge(START, "triage")
_builder.add_conditional_edges("triage", _triage_router)
for _name in INVESTIGATORS:
    _builder.add_edge(_name, "join")
_builder.add_conditional_edges("join", _join_router)
_builder.add_edge("rca_metrics_first", "judge")
_builder.add_edge("rca_change_first", "judge")
_builder.add_edge("observability", "rag")
_builder.add_edge("rag", "rca")
_builder.add_conditional_edges("rca", _confidence_router,
                               {"remediation": "remediation", "observability": "observability"})
_builder.add_conditional_edges("judge", _confidence_router,
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
