from app.agents.state import mark
from app.ml.classifier import rule_based
from app.ml.family import predict_family
from app.ml.features import DEFAULTS
from app.policy.severity import from_label


def triage_node(state: dict):
    incident = state.get("incident") or {}
    claimed = from_label(incident.get("severity"))
    if claimed is not None:
        return {**mark("triage"), "severity": claimed,
                "severity_source": "alert", "fault_family": None}
    m = incident.get("metrics") or {}
    features = {
        "error_rate": m.get("error_rate", DEFAULTS["error_rate"]),
        "p95_latency_ms": m.get("p95_latency_ms", DEFAULTS["p95_latency_ms"]),
        "cpu_pct": m.get("cpu_pct", DEFAULTS["cpu_pct"]),
        "memory_pct": m.get("memory_pct", DEFAULTS["memory_pct"]),
        "request_rate": m.get("request_rate", DEFAULTS["request_rate"]),
        "deployment_minutes_ago": incident.get("deployment_minutes_ago",
                                               DEFAULTS["deployment_minutes_ago"]),
        "db_connections": m.get("db_connections", DEFAULTS["db_connections"]),
        "redis_up": m.get("redis_up", DEFAULTS["redis_up"]),
        "pods_ready": m.get("pods_ready", DEFAULTS["pods_ready"]),
    }
    severity = rule_based(features)
    try:
        family = predict_family(features)
    except Exception:
        family = None
    return {**mark("triage"), "severity": severity,
            "severity_source": "rules", "fault_family": family}
