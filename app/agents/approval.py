from typing import Literal

from pydantic import BaseModel, Field

from app.agents.state import mark
from app.security.untrusted import INJECTION_EVIDENCE_SOURCE

ActionLiteral = Literal[
    "restart pods",
    "scale replicas",
    "restart redis",
    "rollback deployment",
    "modify network policy",
    "delete database",
]


class RemediationPlan(BaseModel):
    action: ActionLiteral
    root_cause: str = Field(default="", max_length=500)
    params: dict = Field(default_factory=dict)

    def params_valid(self) -> bool:
        p = self.params or {}
        if not isinstance(p, dict):
            return False
        if self.action == "scale replicas":
            try:
                n = int(p.get("replicas", 0))
            except (TypeError, ValueError):
                return False
            return 1 <= n <= 20
        return True


def _injection_suspected(state: dict) -> bool:
    if state.get("injection_suspected"):
        return True
    for e in state.get("evidence", []) or []:
        if isinstance(e, dict) and e.get("source") == INJECTION_EVIDENCE_SOURCE:
            return True
    return False


def _plan_valid(state: dict) -> bool:
    plan = state.get("remediation_plan") or {}
    try:
        parsed = RemediationPlan(
            action=plan.get("action", ""),
            root_cause=str(plan.get("root_cause", ""))[:500],
            params=plan.get("params", {}) or {},
        )
    except Exception:
        return False
    return parsed.params_valid()


def approval_node(state: dict):
    if not _plan_valid(state):
        return {**mark("approval"), "approval_status": "rejected"}
    if state.get("risk_level") == "forbidden":
        return {**mark("approval"), "approval_status": "rejected"}
    if _injection_suspected(state):
        return {**mark("approval"), "approval_status": "awaiting_human"}
    if state.get("risk_level") == "low":
        return {**mark("approval"), "approval_status": "auto_approved"}
    return {**mark("approval"), "approval_status": "awaiting_human"}
