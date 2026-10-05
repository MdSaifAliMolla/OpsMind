from app.agents.state import mark
from app.tools import kubernetes as k8s
from app.tools.prometheus import query_metric_synthetic, set_recovered


def execute_node(state: dict):
    plan = dict(state.get("remediation_plan") or {})
    action = str(plan.get("action", "")).lower()
    params = plan.get("params", {}) or {}
    if not isinstance(params, dict):
        params = {}
    incident = state.get("incident") or {}
    service = str(incident.get("service", "unknown"))[:128]
    incident_id = str(incident.get("incident_id", "unknown"))
    try:
        plan["pre_error_rate"] = query_metric_synthetic(incident, "error_rate")["value"]
    except Exception:
        plan["pre_error_rate"] = (incident.get("metrics") or {}).get("error_rate", 0)

    if "rollback" in action:
        result = k8s.rollback_deployment(service)
    elif "restart redis" in action:
        result = k8s.restart_redis()
    elif "restart" in action:
        result = k8s.restart_pods(service)
    elif "scale" in action:
        try:
            replicas = int(params.get("replicas", 5))
        except (TypeError, ValueError):
            replicas = 5
        replicas = max(1, min(20, replicas))
        result = k8s.scale_replicas(service, replicas)
    else:
        result = {"ok": False, "error": f"unknown action: {action[:64]}"}

    if result.get("ok"):
        set_recovered(incident_id)
    plan.update({"executed": result["ok"], "result": result})
    return {**mark("execute"), "remediation_plan": plan,
            "executions": state.get("executions", 0) + 1}
