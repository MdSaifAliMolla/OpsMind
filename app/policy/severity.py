"""Severity label validation."""

SEVERITIES = ("P1", "P2", "P3", "P4")


def from_label(value) -> str | None:
    """Alert-provided severity (e.g. Alertmanager label). None if invalid."""
    v = str(value or "").strip().upper()
    return v if v in SEVERITIES else None
