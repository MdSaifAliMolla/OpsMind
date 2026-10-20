import json
import time

from app.agents.llm import get_llm
from app.agents.state import mark
from app.tools.registry import build_tools

WANT_METRICS = ["error_rate", "p95_latency_ms", "cpu_pct", "memory_pct",
                "db_connections", "redis_up", "pods_ready", "request_rate"]


def observability_node(state: dict):
    incident = state["incident"]
    tools = build_tools(incident)
    by_name = {t.name: t for t in tools}
    evidence = []
    llm = get_llm()
    from app.agents.llm_provider import get_model_name
    from app.observability import metrics as _m
    from app.observability.tracing import chat_span, maybe_attach_content

    model = get_model_name()
    prompt = (
        f"Incident on {incident.get('service', 'unknown')}: {incident.get('alert_type')}. "
        "Gather metrics, logs, deployment history, and traces with the available tools."
    )
    start = time.time()
    with chat_span("observability", model) as span:
        res = llm.bind_tools(tools).invoke(prompt)
        maybe_attach_content(span, prompt, str(getattr(res, "content", "")))
    _m.record_llm_call(
        model,
        len(prompt) // 4,
        len(str(getattr(res, "content", ""))) // 4,
        time.time() - start,
    )
    for call in list(res.tool_calls or [])[:3]:
        if isinstance(call, dict):
            name, args = call.get("name"), call.get("args", {})
        else:
            name, args = getattr(call, "name", None), getattr(call, "args", {}) or {}
        t = by_name.get(name)
        if t is None:
            continue
        try:
            evidence.append({"source": name, "args": args,
                             "result": json.loads(t.invoke(args or {}))})
        except Exception:
            continue

    for m in WANT_METRICS:
        if any(e["source"] == "query_metrics" and e.get("args", {}).get("metric") == m for e in evidence):
            continue
        evidence.append({"source": "query_metrics", "args": {"metric": m},
                         "result": json.loads(by_name["query_metrics"].invoke({"metric": m}))})

    if not any(e["source"] == "search_logs" for e in evidence):
        evidence.append({"source": "search_logs", "args": {"query": incident.get("alert_type", "")},
                         "result": json.loads(by_name["search_logs"].invoke(
                             {"query": incident.get("alert_type", "")}))})

    if not any(e["source"] == "get_deployment_history" for e in evidence):
        evidence.append({"source": "get_deployment_history", "args": {},
                         "result": json.loads(by_name["get_deployment_history"].invoke({}))})

    if not any(e["source"] == "get_trace" for e in evidence):
        evidence.append({"source": "get_trace", "args": {},
                         "result": json.loads(by_name["get_trace"].invoke({}))})

    if not any(e["source"] == "pod_events" for e in evidence):
        from app.tools.kubernetes import get_events as _events
        evidence.append({"source": "pod_events",
                         "args": {"service": incident.get("service", "")},
                         "result": _events(str(incident.get("service", "")))})

    return {**mark("observability"), "evidence": evidence}
