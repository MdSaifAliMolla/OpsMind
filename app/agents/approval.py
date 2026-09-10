from app.agents.state import mark


def approval_node(state: dict):
    if state.get("risk_level") == "forbidden":
        return {**mark("approval"), "approval_status": "rejected"}
    if state.get("risk_level") == "low":
        return {**mark("approval"), "approval_status": "auto_approved"}
    return {**mark("approval"), "approval_status": "awaiting_human"}
