from app.agents.state import mark
from app.tools import kubernetes as k8s
from app.tools.prometheus import query_metric_synthetic, set_recovered


def execute_node(state: dict):
    plan = dict(state.get("remediation_plan") or {})
    action = plan.get("action", "").lower()
    params = plan.get("params", {}) or {}
    service = state["incident"]["service"]

    # pre-execution reading, so verify can do a genuine before/after comparison
    plan["pre_error_rate"] = query_metric_synthetic(state["incident"], "error_rate")["value"]

    if "rollback" in action:
        result = k8s.rollback_deployment(service)
    elif "restart redis" in action:
        result = k8s.restart_redis()
    elif "restart" in action:
        result = k8s.restart_pods(service)
    elif "scale" in action:
        result = k8s.scale_replicas(service, params.get("replicas", 5))
    else:
        result = {"ok": False, "error": f"unknown action: {action}"}

    if result["ok"]:
        set_recovered(state["incident"]["incident_id"])
    plan.update({"executed": result["ok"], "result": result})
    return {**mark("execute"), "remediation_plan": plan,
            "executions": state.get("executions", 0) + 1}
