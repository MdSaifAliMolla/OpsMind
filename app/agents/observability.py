import json

from app.agents.llm import get_llm, note_llm_error
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
    if llm is not None:
        try:
            res = llm.bind_tools(tools).invoke(
                f"Incident on {incident['service']}: {incident.get('alert_type')}. "
                "Gather metrics, logs, and deployment history with the available tools."
            )
            for call in res.tool_calls or []:
                t = by_name.get(call["name"])
                if t is None:
                    continue
                evidence.append({"source": call["name"], "args": call["args"],
                                 "result": json.loads(t.invoke(call["args"]))})
        except Exception as e:
            note_llm_error("tool loop", e)

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

    return {**mark("observability"), "evidence": evidence}
