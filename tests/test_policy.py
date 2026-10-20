import pytest

from app.evaluation.analysis import family_exact, wilson
from app.ml.classifier import rule_based
from app.policy.faults import UNFIXABLE, normalize_family
from app.policy.severity import from_label


@pytest.mark.parametrize(
    "value,expected",
    [("p1", "P1"), (" P2 ", "P2"), ("P4", "P4")],
)
def test_alert_severity_labels_are_normalized(value, expected):
    assert from_label(value) == expected


@pytest.mark.parametrize("value", ["", "critical", "P0", None, 1])
def test_invalid_severity_labels_are_ignored(value):
    assert from_label(value) is None


def test_rule_based_severity_escalates_on_hard_failures():
    assert rule_based({"pods_ready": 0}) == "P1"
    assert rule_based({"redis_up": 0}) == "P1"
    assert rule_based({"db_connections": 90}) == "P1"
    assert rule_based({"error_rate": 0.3}) == "P1"


def test_rule_based_severity_uses_progressive_thresholds():
    assert rule_based({"error_rate": 0.12}) == "P2"
    assert rule_based({"cpu_pct": 85}) == "P2"
    assert rule_based({"error_rate": 0.04}) == "P3"
    assert rule_based({}) == "P4"


def test_fault_family_normalization():
    assert normalize_family("BAD_DEPLOY") == "bad_deploy"
    assert normalize_family(" unknown_family ") is None
    assert normalize_family(None) is None
    assert "network_delay" in UNFIXABLE


def test_family_exact_requires_both_sides_to_be_known():
    assert family_exact("bad_deploy", "bad_deploy")
    assert not family_exact("bad_deploy", "oom_crashloop")
    assert not family_exact("invented", "invented")


def test_wilson_interval_bounds():
    result = wilson(80, 100)
    assert result["accuracy"] == 0.8
    assert 0.7 < result["lo"] < 0.8
    assert 0.8 < result["hi"] < 0.9
    assert wilson(0, 0) == {"n": 0, "accuracy": None, "lo": None, "hi": None}
