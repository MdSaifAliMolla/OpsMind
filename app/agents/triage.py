from app.agents.state import mark
from app.ml.classifier import predict_severity, rule_based


def triage_node(state: dict):
    m = state["incident"].get("metrics", {})
    features = {
        "error_rate": m.get("error_rate", 0),
        "p95_latency_ms": m.get("p95_latency_ms", 0),
        "cpu_pct": m.get("cpu_pct", 0),
        "memory_pct": m.get("memory_pct", 0),
        "request_rate": m.get("request_rate", 0),
        "deployment_minutes_ago": state["incident"].get("deployment_minutes_ago", 99999),
        "db_connections": m.get("db_connections", 0),
        "redis_up": m.get("redis_up", 1),
        "pods_ready": m.get("pods_ready", 1),
    }
    try:
        severity = predict_severity(features)
    except Exception:
        severity = rule_based(features)
    return {**mark("triage"), "severity": severity}
