from app.api import ratelimit


def test_rate_limit_disabled_allows_everything():
    ratelimit.reset()
    assert ratelimit.check("1.2.3.4", limit_per_min=0) == (True, 0)


def test_rate_limit_counts_within_window():
    ratelimit.reset()
    now = 1000.0
    for _ in range(3):
        assert ratelimit.check("1.2.3.4", limit_per_min=3, now=now)[0]
    allowed, retry = ratelimit.check("1.2.3.4", limit_per_min=3, now=now + 1)
    assert not allowed
    assert retry == 59


def test_rate_limit_isolated_per_ip_and_recovers_after_window():
    ratelimit.reset()
    now = 2000.0
    assert ratelimit.check("1.1.1.1", limit_per_min=1, now=now)[0]
    assert not ratelimit.check("1.1.1.1", limit_per_min=1, now=now + 1)[0]
    assert ratelimit.check("2.2.2.2", limit_per_min=1, now=now + 1)[0]
    assert ratelimit.check("1.1.1.1", limit_per_min=1, now=now + 61)[0]


def test_rate_limit_reads_environment(monkeypatch):
    ratelimit.reset()
    monkeypatch.setenv("OPSMIND_RATE_LIMIT_PER_MIN", "2")
    assert ratelimit.rate_limit_per_min() == 2.0
    monkeypatch.setenv("OPSMIND_RATE_LIMIT_PER_MIN", "not-a-number")
    assert ratelimit.rate_limit_per_min() == 0.0
