"""Fault catalog shared by triage, remediation, and evaluation."""
GOLD_FIX = {
    "bad_deploy": "rollback deployment",
    "oom_crashloop": "restart pods",
    "cpu_starvation": "scale replicas",
    "pod_kill_storm": "scale replicas",
    "dependency_down": "restart redis",
    "network_delay": None,
}

UNFIXABLE = {fam for fam, fix in GOLD_FIX.items() if fix is None}

INTERIM_FAMILIES = (
    "db_pool_exhaustion",
    "memory_leak",
    "redis_unavailable",
    "traffic_spike",
    "bad_deployment_crashloop",
    "dns_resolution_failure",
    "retry_storm_cascade",
    "disk_pressure_evictions",
    "slow_query_degradation",
    "cache_hit_drop",
    "minor_error_blip",
)

KNOWN_FAMILIES = tuple(GOLD_FIX) + INTERIM_FAMILIES


def normalize_family(value) -> str | None:
    """Lowercased family if known, else None (caller decides: raise or miss)."""
    v = str(value or "").strip().lower()
    return v if v in KNOWN_FAMILIES else None
