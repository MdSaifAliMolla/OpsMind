import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("OPSMIND_API_KEY", raising=False)
    monkeypatch.delenv("OPSMIND_ALERTMANAGER_KEY", raising=False)
    from app.api import ratelimit
    ratelimit.reset()
    yield
    ratelimit.reset()


def test_allows_under_limit_and_blocks_over(monkeypatch):
    from app.api import ratelimit
    monkeypatch.setenv("OPSMIND_RATE_LIMIT_PER_MIN", "2")
    assert ratelimit.check("1.2.3.4", now=1000.0) == (True, 0)
    assert ratelimit.check("1.2.3.4", now=1001.0) == (True, 0)
    allowed, retry = ratelimit.check("1.2.3.4", now=1002.0)
    assert allowed is False and retry > 0


def test_window_slides(monkeypatch):
    from app.api import ratelimit
    monkeypatch.setenv("OPSMIND_RATE_LIMIT_PER_MIN", "1")
    assert ratelimit.check("ip", now=1000.0)[0] is True
    assert ratelimit.check("ip", now=1030.0)[0] is False
    assert ratelimit.check("ip", now=1061.0)[0] is True


def test_disabled_by_default(monkeypatch):
    from app.api import ratelimit
    monkeypatch.delenv("OPSMIND_RATE_LIMIT_PER_MIN", raising=False)
    for _ in range(50):
        assert ratelimit.check("ip")[0] is True


def test_ips_independent(monkeypatch):
    from app.api import ratelimit
    monkeypatch.setenv("OPSMIND_RATE_LIMIT_PER_MIN", "1")
    assert ratelimit.check("a", now=1000.0)[0] is True
    assert ratelimit.check("b", now=1000.0)[0] is True
    assert ratelimit.check("a", now=1001.0)[0] is False


def test_post_incidents_rate_limited(monkeypatch):
    import app.api.server as srv
    monkeypatch.setenv("OPSMIND_RATE_LIMIT_PER_MIN", "2")
    monkeypatch.setattr(srv, "run_incident",
                        lambda incident, *a, **k: ({"incident": incident,
                                                   "approval_status": "auto_approved"}, "t"))
    client = TestClient(srv.app)
    body = {"incident_id": "rl_test", "service": "s", "metrics": {}}
    assert client.post("/incidents", json=body).status_code == 200
    assert client.post("/incidents", json=body).status_code == 200
    r = client.post("/incidents", json=body)
    assert r.status_code == 429
    assert "Retry-After" in r.headers


def test_gets_never_limited(monkeypatch):
    import app.api.server as srv
    monkeypatch.setenv("OPSMIND_RATE_LIMIT_PER_MIN", "1")
    client = TestClient(srv.app)
    for _ in range(3):
        assert client.get("/health").status_code == 200
