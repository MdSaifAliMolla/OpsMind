import json
import os

from app.agents.graph import run_incident


def load_incident(name: str):
    with open(os.path.join(os.getcwd(), "data/incidents", name, "incident.json")) as f:
        return json.load(f)


def test_db_pool_incident_end_to_end():
    result, _ = run_incident(load_incident("incident_001"))
    assert result["severity"] in ("P1", "P2", "P3", "P4")
    assert result["root_cause"]
    assert result["remediation_plan"]["action"]


def test_first_five_stay_confident():
    saw_p1 = False
    for n in ["incident_001", "incident_002", "incident_003", "incident_004", "incident_005"]:
        result, _ = run_incident(load_incident(n))
        saw_p1 |= result["severity"] == "P1"
        assert result["confidence"] > 0.5
    assert saw_p1
