from app.agents.state import mark
from app.tools import kubernetes as k8s
from app.tools.prometheus import query_metric


def execute_node(state: dict):
    plan = dict(state.get("remediation_plan") or {})
    action = str(plan.get("action", "")).lower()
    params = plan.get("params", {}) or {}
    if not isinstance(params, dict):
        params = {}
    incident = state.get("incident") or {}
    service = str(incident.get("service", "unknown"))[:128]
    plan["pre_error_rate"] = query_metric(incident, "error_rate")["value"]

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
    elif "network policy" in action:
        result = {"ok": False, "error": f"action not implemented yet: {action[:64]}"}
    else:
        result = {"ok": False, "error": f"unknown action: {action[:64]}"}

    plan.update({"executed": result["ok"], "result": result})
    return {**mark("execute"), "remediation_plan": plan,
            "executions": state.get("executions", 0) + 1}
