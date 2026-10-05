from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

PLAN = {"action": "rollback deployment", "root_cause": "bad deploy",
        "params": {"target": "previous ReplicaSet", "deployed_minutes_ago": 3}}
INCIDENT = {"incident_id": "test_appr", "service": "auth-service",
            "environment": "production", "alert_type": "bad_deployment_crashloop",
            "description": "test", "metrics": {}, "logs": [],
            "deployment_minutes_ago": 3}


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    # No DB in these tests: exercise the memory paths without TCP stalls.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from app.api import approvals as appr
    from app.api import db as store
    appr.reset_approval_state()
    store.memory_approvals.clear()
    store.memory_store.clear()
    yield
    appr.reset_approval_state()
    store.memory_approvals.clear()
    store.memory_store.clear()


def _wired(monkeypatch, paused=True, healthy=True):
    """Point the server at a canned paused incident. Returns (client, calls)."""
    import app.agents.graph as graph_mod
    import app.agents.postmortem as pm_mod
    import app.api.server as srv
    from app.api import approvals as appr

    calls = {"resume": 0}
    live = {"incident": dict(INCIDENT),
            "remediation_plan": dict(PLAN),
            "approval_status": "awaiting_human",
            "risk_level": "medium"}

    def _get_state(cfg):
        return SimpleNamespace(values=live)

    def _resume(tid, callbacks=None):
        calls["resume"] += 1
        return {"incident": dict(INCIDENT), "remediation_plan": dict(PLAN),
                "risk_level": "medium",
                "verification_result": {"before": 0.6, "after": 0.01, "healthy": healthy}}

    monkeypatch.setattr(graph_mod.ops_mind_graph, "get_state", _get_state)
    monkeypatch.setattr(srv, "is_paused", lambda tid: paused)
    monkeypatch.setattr(srv, "resume", _resume)
    monkeypatch.setattr(pm_mod, "write_postmortem", lambda state: "POSTMORTEM")
    srv._set_thread("test_appr", "tid-test")
    appr.mark_paused("test_appr", PLAN)
    return TestClient(srv.app), calls, live


def test_plan_hash_stable_and_bound():
    from app.api.approvals import plan_hash
    h1 = plan_hash(PLAN)
    assert len(h1) == 16 and h1 == plan_hash(dict(PLAN))
    assert plan_hash({**PLAN, "params": {"target": "other"}}) != h1


def test_expired_rejected_410(monkeypatch):
    from app.api import approvals as appr
    from app.api.db import memory_approvals
    client, calls, _ = _wired(monkeypatch)
    # age the pause beyond TTL
    with appr._meta_lock:
        appr._approval_meta["test_appr"]["paused_at"] -= 3700
    r = client.post("/incidents/test_appr/approve", json={"approved_by": "sam"})
    assert r.status_code == 410
    assert calls["resume"] == 0
    assert memory_approvals and memory_approvals[-1]["decision"] == "expired"


def test_stale_hash_409(monkeypatch):
    from app.api.db import memory_approvals
    client, calls, _ = _wired(monkeypatch)
    r = client.post("/incidents/test_appr/approve",
                    json={"approved_by": "sam", "plan_hash": "0" * 16})
    assert r.status_code == 409
    assert calls["resume"] == 0
    assert memory_approvals[-1]["decision"] == "stale"


def test_double_approve_single_execution(monkeypatch):
    from app.api import approvals as appr
    client, calls, _ = _wired(monkeypatch)
    h = appr.plan_hash(PLAN)
    kw = {"headers": {"Idempotency-Key": "click-1"}}
    r1 = client.post("/incidents/test_appr/approve",
                     json={"approved_by": "sam", "plan_hash": h}, **kw)
    r2 = client.post("/incidents/test_appr/approve",
                     json={"approved_by": "sam", "plan_hash": h}, **kw)
    assert r1.status_code == 200 and r2.status_code == 200
    assert calls["resume"] == 1
    assert r1.json()["approved_by"] == r2.json()["approved_by"] == "sam"


def test_approver_header_precedence_and_required(monkeypatch):
    from app.api import approvals as appr
    client, calls, _ = _wired(monkeypatch)
    h = appr.plan_hash(PLAN)
    r = client.post("/incidents/test_appr/approve", headers={"X-Approver": "boss"},
                    json={"approved_by": "sam", "plan_hash": h})
    assert r.status_code == 200 and r.json()["approved_by"] == "boss"
    # required mode rejects faceless body identity; unknown thread still 404s with a header
    monkeypatch.setenv("OPSMIND_REQUIRE_APPROVER", "true")
    r = client.post("/incidents/test_appr/approve", json={"approved_by": "sam", "plan_hash": h})
    assert r.status_code == 401
    r = client.post("/incidents/test_appr2/approve", headers={"X-Approver": "boss"},
                    json={"approved_by": "boss"})
    assert r.status_code == 404


def test_audit_chain_links(monkeypatch):
    from app.api import approvals as appr
    from app.api.db import memory_approvals
    client, calls, _ = _wired(monkeypatch)
    h = appr.plan_hash(PLAN)
    client.post("/incidents/test_appr/approve",
                json={"approved_by": "sam", "plan_hash": "0" * 16})  # stale row
    # re-pause (stale attempt does not clear meta) then approve for real
    appr.mark_paused("test_appr", PLAN)
    client.post("/incidents/test_appr/approve",
                json={"approved_by": "sam", "plan_hash": h})  # approved row
    rows = [r for r in memory_approvals if r["incident_id"] == "test_appr"]
    assert [r["decision"] for r in rows] == ["stale", "approved"]
    assert rows[1]["prev_hash"] == rows[0]["row_hash"]
    assert rows[1]["approver"] == "sam" and rows[1]["plan_hash"] == h


def test_ttl_disabled_never_expires(monkeypatch):
    from app.api import approvals as appr
    monkeypatch.setenv("OPSMIND_APPROVAL_TTL_MIN", "0")
    client, calls, _ = _wired(monkeypatch)
    with appr._meta_lock:
        appr._approval_meta["test_appr"]["paused_at"] -= 10 ** 6
    r = client.post("/incidents/test_appr/approve", json={"approved_by": "sam"})
    assert r.status_code == 200 and calls["resume"] == 1


def test_missing_meta_skips_ttl(monkeypatch):
    from app.api import approvals as appr
    client, calls, _ = _wired(monkeypatch)
    appr.clear_meta("test_appr")  # e.g. restart path before re-mark
    r = client.post("/incidents/test_appr/approve", json={"approved_by": "sam"})
    assert r.status_code == 200
