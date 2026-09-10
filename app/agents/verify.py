from app.agents.state import mark
from app.tools.prometheus import query_metric_synthetic


def verify_node(state: dict):
    plan = state.get("remediation_plan") or {}
    before = plan.get("pre_error_rate",
                      state["incident"].get("metrics", {}).get("error_rate", 0))
    executed = plan.get("executed", False)

    # re-read through the same metric path the investigation used
    after = query_metric_synthetic(state["incident"], "error_rate")["value"]
    healthy = bool(executed and after < 0.05 and after < before)

    if healthy:
        # against a real cluster, also require the rollout to look finished
        from app.tools.kubernetes import connected, rollout_status
        if connected():
            rollout_ok = rollout_status(state["incident"]["service"])
            if rollout_ok is False:
                healthy = False

    return {**mark("verify"),
            "verification_result": {"before": before, "after": after, "healthy": healthy}}
