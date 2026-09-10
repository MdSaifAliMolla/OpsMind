import math

from app.agents.llm import get_llm, note_llm_error
from app.agents.state import mark

RISK_TABLE = {
    "restart pods": "low",
    "scale replicas": "low",
    "restart redis": "medium",
    "rollback deployment": "medium",
    "modify network policy": "high",
    "delete database": "forbidden",
}


def rule_action(root_cause: str) -> str:
    rc = (root_cause or "").lower()
    if "pool exhaustion" in rc or "crashloop" in rc or "bad deployment" in rc:
        return "rollback deployment"
    if "memory leak" in rc:
        return "restart pods"
    if "redis" in rc:
        return "restart redis"
    if "traffic spike" in rc:
        return "scale replicas"
    return "restart pods"


def rule_params(action: str, state: dict) -> dict:
    m = state["incident"].get("metrics", {})
    if action == "scale replicas":
        # one replica per ~2000 rps of observed load, bounded
        n = math.ceil(m.get("request_rate", 4000) / 2000)
        return {"replicas": max(2, min(10, n))}
    if action == "rollback deployment":
        dep = next((e["result"] for e in state.get("evidence", [])
                    if e["source"] == "get_deployment_history"), None)
        return {"target": "previous ReplicaSet",
                "deployed_minutes_ago": (dep or {}).get("minutesAgo")}
    return {}


def remediation_node(state: dict):
    action = rule_action(state.get("root_cause"))
    llm = get_llm()
    if llm is not None:
        try:
            res = llm.invoke(
                f"Root cause: {state.get('root_cause')}. Metrics: "
                f"{state['incident'].get('metrics', {})}. Pick ONE remediation from: restart pods, "
                "scale replicas, rollback deployment, restart redis. If scaling, say how many replicas "
                "the load needs. Reply with only the action string."
            )
            text = (res.content if isinstance(res.content, str) else "").strip().lower()
            for allowed in RISK_TABLE:
                if allowed in text:
                    action = allowed
                    break
        except Exception as e:
            note_llm_error("remediation", e)
    plan = {"action": action, "root_cause": state.get("root_cause"),
            "params": rule_params(action, state)}
    return {**mark("remediation"), "remediation_plan": plan,
            "risk_level": RISK_TABLE.get(action, "high")}
