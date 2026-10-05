from app.evaluation.analysis import (
    calibration_summary,
    calibration_table,
    cost_gate,
    cost_stats,
    ece,
    failure_taxonomy,
    retrieval_metrics,
    safety_metrics,
)


def test_ece_perfect_is_zero():
    assert ece([0.9, 0.9, 0.1, 0.1], [1, 1, 0, 0]) < 0.15


def test_ece_confident_wrong_is_high():
    assert ece([0.95] * 10, [0] * 10) > 0.5


def test_calibration_table_bins():
    rows = [{"confidence": 0.95, "rca_correct": True},
            {"confidence": 0.95, "rca_correct": False},
            {"confidence": 0.2, "rca_correct": False}]
    table = calibration_table(rows)
    assert len(table) == 10
    top = table[9]
    assert top["n"] == 2 and top["accuracy"] == 0.5


def test_calibration_summary_high_conf():
    rows = [{"confidence": 0.9, "rca_correct": True},
            {"confidence": 0.85, "rca_correct": True},
            {"confidence": 0.5, "rca_correct": False}]
    s = calibration_summary(rows)
    assert s["n_scored"] == 3 and s["high_conf_n"] == 2
    assert s["high_conf_accuracy"] == 1.0


def test_calibration_missing_confidence():
    s = calibration_summary([{"rca_correct": True}])
    assert s == {"n_scored": 0, "ece": None, "high_conf_accuracy": None,
                "high_conf_n": 0, "threshold": 0.8}


def test_taxonomy_buckets():
    rows = [
        {"rca_correct": False, "predicted_severity": "ERROR: boom"},
        {"rca_correct": False, "evidence_count": 1},
        {"rca_correct": False, "evidence_count": 10,
         "gold_runbook": "database.md", "retrieved_runbooks": ["rag:redis.md"]},
        {"rca_correct": False, "evidence_count": 10,
         "gold_runbook": "database.md", "retrieved_runbooks": ["rag:database.md"]},
        {"rca_correct": True},
    ]
    assert failure_taxonomy(rows) == {"agent_error": 1, "missing_evidence": 1,
                                      "retrieval_miss": 1, "wrong_family": 1}


def test_retrieval_hit():
    rows = [{"gold_runbook": "a.md", "retrieved_runbooks": ["rag:a.md"]},
            {"gold_runbook": "b.md", "retrieved_runbooks": ["rag:c.md"]}]
    assert retrieval_metrics(rows) == {"n_scored": 2, "hit_at_3": 0.5}
    assert retrieval_metrics([{"rca_correct": True}]) == {"n_scored": 0, "hit_at_3": None}


def test_safety_metrics():
    rows = [
        {"predicted_action": "restart pods", "predicted_risk": "low",
         "expected_risk": "low"},
        {"predicted_action": "nuke everything", "predicted_risk": "low",
         "expected_risk": "medium"},
    ]
    s = safety_metrics(rows)
    assert s["allowlist_match"] == 0.5 and s["risk_correct"] == 0.5


def test_cost_stats_and_gate(tmp_path, monkeypatch):
    rows = [{"tokens": 100, "cost": 0.01, "latency_s": 2.0},
            {"tokens": 200, "cost": 0.03, "latency_s": 4.0}]
    c = cost_stats(rows)
    assert (c["avg_tokens"], c["avg_cost"], c["avg_latency_s"]) == (150.0, 0.02, 3.0)
    # missing baseline -> skip, never fail
    monkeypatch.chdir(tmp_path)
    ok, _ = cost_gate(0.02, baseline_path="nope.json")
    assert ok is True
    # pass within 25%
    (tmp_path / "base.json").write_text('{"avg_cost_per_incident": 0.02}')
    ok, _ = cost_gate(0.024, baseline_path="base.json")
    assert ok is True
    ok, msg = cost_gate(0.03, baseline_path="base.json")
    assert ok is False and "+25%" in msg
    # no cost data -> skip
    ok, _ = cost_gate(None, baseline_path="base.json")
    assert ok is True
