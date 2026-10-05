import json
import logging
import os

log = logging.getLogger(__name__)

INVESTIGATORS = ["metrics_agent", "logs_agent", "trace_agent", "runbook_agent"]

WANT_METRICS = ["error_rate", "p95_latency_ms", "cpu_pct", "memory_pct",
                "db_connections", "redis_up", "pods_ready", "request_rate"]


def get_mode() -> str:
    mode = os.getenv("OPSMIND_MODE", "single").strip().lower()
    return mode if mode in ("single", "multi", "debate") else "single"


def metrics_agent(state: dict):
    from app.agents.state import mark
    from app.tools.registry import build_tools

    incident = state.get("incident") or {}
    tools = build_tools(incident)
    by_name = {t.name: t for t in tools}
    evidence = []
    for m in WANT_METRICS:
        try:
            evidence.append({"source": "query_metrics", "args": {"metric": m},
                             "result": json.loads(by_name["query_metrics"].invoke({"metric": m}))})
        except Exception:
            continue
    return {**mark("metrics_agent"), "evidence": evidence}


def logs_agent(state: dict):
    import json as _json

    from app.agents.state import mark
    from app.tools.registry import build_tools

    incident = state.get("incident") or {}
    tools = build_tools(incident)
    by_name = {t.name: t for t in tools}
    try:
        result = _json.loads(by_name["search_logs"].invoke(
            {"query": str(incident.get("alert_type", ""))}))
    except Exception:
        result = []
    return {**mark("logs_agent"),
            "evidence": [{"source": "search_logs",
                          "args": {"query": str(incident.get("alert_type", ""))},
                          "result": result}]}


def trace_agent(state: dict):
    import json as _json

    from app.agents.state import mark
    from app.tools.registry import build_tools

    incident = state.get("incident") or {}
    tools = build_tools(incident)
    by_name = {t.name: t for t in tools}
    evidence = []
    for name in ("get_trace", "get_deployment_history"):
        try:
            evidence.append({"source": name, "args": {},
                             "result": _json.loads(by_name[name].invoke({}))})
        except Exception:
            continue
    return {**mark("trace_agent"), "evidence": evidence}


def runbook_agent(state: dict):
    from app.agents.rag import rag_node

    out = rag_node(state)
    from app.agents.state import mark as _mark
    extra = _mark("runbook_agent")
    return {**out, "trace": out.get("trace", []) + extra["trace"]}


def join(state: dict):
    from app.agents.state import mark
    from app.security.untrusted import injection_evidence_item, scan_state_for_injection

    incident = state.get("incident") or {}
    evidence = state.get("evidence", []) or []
    out = mark("join")
    if scan_state_for_injection(incident, evidence):
        out["injection_suspected"] = True
        out["evidence"] = [injection_evidence_item("join input matched injection heuristic")]
    return out


def _rca_variant(state: dict, bias: str, node: str):
    from langchain_core.messages import HumanMessage, SystemMessage

    from app.agents.llm import content_to_text, invoke_tracked
    from app.agents.rca import SYSTEM, extract_json
    from app.agents.state import mark
    from app.security.untrusted import (
        build_wrapped_evidence_text,
        scan_state_for_injection,
    )

    incident = state.get("incident") or {}
    evidence = state.get("evidence", []) or []
    evidence_text = build_wrapped_evidence_text(incident, evidence)
    system = SYSTEM + f"\n\nInvestigator bias: {bias}."
    try:
        res = invoke_tracked([
            SystemMessage(content=system),
            HumanMessage(content=f"Incident: {incident.get('alert_type')} on "
                                 f"{incident.get('service')}\n\nEvidence:\n{evidence_text}"),
        ], where=node)
        hyps = extract_json(content_to_text(res.content))["hypotheses"]
    except Exception as e:
        raise RuntimeError(f"{node} llm call failed: {e}") from e
    cleaned = []
    for h in (hyps or [])[:3]:
        if not isinstance(h, dict) or not h.get("root_cause"):
            continue
        try:
            conf = float(h.get("confidence", 0))
        except (TypeError, ValueError):
            continue
        cleaned.append({
            "root_cause": str(h["root_cause"])[:300],
            "supporting": [str(x)[:300] for x in (h.get("supporting") or [])][:8],
            "contradicting": [str(x)[:300] for x in (h.get("contradicting") or [])][:8],
            "confidence": max(0.0, min(1.0, conf)),
        })
    if not cleaned:
        raise RuntimeError(f"{node} returned no valid hypotheses")
    vote = {"agent": node, "bias": bias, "hypotheses": cleaned}
    out = {**mark(node), "agent_votes": [vote]}
    if scan_state_for_injection(incident, evidence) or state.get("injection_suspected"):
        out["injection_suspected"] = True
    return out


def rca_metrics_first(state: dict):
    return _rca_variant(state, "metrics-first: weight numeric telemetry heaviest", "rca_metrics_first")


def rca_change_first(state: dict):
    return _rca_variant(state, "change-first: weight recent deploys and config drift heaviest",
                        "rca_change_first")


def judge(state: dict):
    from langchain_core.messages import HumanMessage, SystemMessage

    from app.agents.llm import content_to_text, invoke_tracked
    from app.agents.rca import extract_json
    from app.agents.state import mark
    from app.security.untrusted import (
        PROMPT_RULE,
        build_wrapped_evidence_text,
        injection_evidence_item,
        scan_state_for_injection,
    )

    incident = state.get("incident") or {}
    evidence = state.get("evidence", []) or []
    votes = state.get("agent_votes", []) or []
    evidence_text = build_wrapped_evidence_text(incident, evidence)
    votes_text = json.dumps(votes)[:6000]
    system = ("You are the RCA judge. Two investigators propose competing hypotheses. "
              "Compare each hypothesis against the evidence, pick or merge the best-supported "
              "root cause, and output calibrated confidence 0-1. Respond ONLY as JSON: "
              '{"hypotheses": [{"root_cause": str, "supporting": [str], '
              '"contradicting": [str], "confidence": float}]}'
              f"\n\n{PROMPT_RULE}")
    try:
        res = invoke_tracked([
            SystemMessage(content=system),
            HumanMessage(content=f"Votes:\n{votes_text}\n\nEvidence:\n{evidence_text}"),
        ], where="judge")
    except Exception as e:
        raise RuntimeError(f"judge llm call failed: {e}") from e
    try:
        hyps = extract_json(content_to_text(res.content))["hypotheses"]
    except Exception:
        hyps = []
    cleaned = []
    for h in (hyps or [])[:3]:
        if not isinstance(h, dict) or not h.get("root_cause"):
            continue
        try:
            conf = float(h.get("confidence", 0))
        except (TypeError, ValueError):
            continue
        cleaned.append({
            "root_cause": str(h["root_cause"])[:300],
            "supporting": [str(x)[:300] for x in (h.get("supporting") or [])][:8],
            "contradicting": [str(x)[:300] for x in (h.get("contradicting") or [])][:8],
            "confidence": max(0.0, min(1.0, conf)),
        })
    if not cleaned:
        flat = [h for v in votes if isinstance(v, dict) for h in v.get("hypotheses", [])]
        flat.sort(key=lambda h: h.get("confidence", 0), reverse=True)
        cleaned = flat[:3]
    if not cleaned:
        raise RuntimeError("judge had no hypotheses to pick from")
    cleaned.sort(key=lambda h: h["confidence"], reverse=True)
    out = {**mark("judge"), "hypotheses": cleaned, "confidence": cleaned[0]["confidence"],
           "root_cause": cleaned[0]["root_cause"],
           "investigation_loops": state.get("investigation_loops", 0) + 1}
    if scan_state_for_injection(incident, evidence) or state.get("injection_suspected"):
        out["injection_suspected"] = True
        out["evidence"] = [injection_evidence_item("judge input matched injection heuristic")]
    return out
