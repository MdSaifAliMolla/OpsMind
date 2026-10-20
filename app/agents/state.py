import operator
from datetime import datetime
from typing import Annotated

from typing_extensions import TypedDict


class IncidentState(TypedDict, total=False):
    incident: dict
    severity: str
    severity_source: str
    fault_family: str | None
    evidence: Annotated[list, operator.add]
    trace: Annotated[list, operator.add]
    hypotheses: list
    confidence: float
    root_cause: str | None
    remediation_plan: dict | None
    risk_level: str | None
    approval_status: str
    verification_result: dict | None
    investigation_loops: int
    executions: int
    injection_suspected: bool


def mark(node: str) -> dict:
    return {"trace": [{"node": node, "at": datetime.now().isoformat()}]}
