from app.agents.state import mark
from app.tools.prometheus import query_metric


def verify_node(state: dict):
    plan = state.get("remediation_plan") or {}
    incident = state.get("incident") or {}
    incident_metrics = incident.get("metrics") or {}
    try:
        before = float(plan.get("pre_error_rate",
                        incident_metrics.get("error_rate", 0)))
    except (TypeError, ValueError):
        before = 0.0
    executed = bool(plan.get("executed", False))
    after = float(query_metric(incident, "error_rate")["value"])
    healthy = bool(executed and after < 0.05 and after < before)

    if healthy:
        from app.tools.kubernetes import rollout_status
        rollout_ok = rollout_status(str(incident.get("service", "unknown")))
        if rollout_ok is False:
            healthy = False

    return {**mark("verify"),
            "verification_result": {"before": before, "after": after, "healthy": healthy}}
