"""Severity thresholds used when an alert carries no explicit severity label."""


def rule_based(f: dict) -> str:
    if f.get("pods_ready", 1) == 0 or f.get("error_rate", 0) >= 0.25:
        return "P1"
    if f.get("redis_up", 1) == 0:
        return "P1"
    if f.get("db_connections", 0) >= 85:
        return "P1"
    if f.get("error_rate", 0) >= 0.1 or f.get("cpu_pct", 0) >= 80 or f.get("memory_pct", 0) >= 85:
        return "P2"
    if f.get("error_rate", 0) >= 0.03:
        return "P3"
    return "P4"
