import json
import os

from fastapi.testclient import TestClient

from app.api.server import app

client = TestClient(app)


def test_approval_loop():
    with open(os.path.join(os.getcwd(), "data/incidents/incident_003/incident.json")) as f:
        incident = json.load(f)

    r1 = client.post("/incidents", json=incident).json()
    assert r1["severity"] == "P1", r1
    assert r1["approval_status"] == "awaiting_human", r1

    r2 = client.post(f"/incidents/{incident['incident_id']}/approve",
                     json={"approved_by": "smoke"}).json()
    assert r2["approval_status"] == "approved", r2
    assert r2["verification_result"]["healthy"] is True, r2

    assert client.get("/").status_code == 200  # dashboard serves
    print("smoke OK")
