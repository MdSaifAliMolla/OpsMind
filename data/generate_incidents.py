import argparse
import json
import os
import random

SCENARIOS = [
    {
        "type": "db_pool_exhaustion",
        "service": "payment-api",
        "root_cause": "database connection pool exhaustion",
        "metrics": {"error_rate": 0.28, "p95_latency_ms": 2400, "cpu_pct": 45, "db_connections": 99},
        "logs": ["connection pool exhausted - timeout acquiring connection", "FATAL: remaining connection slots are reserved"],
        "deployment_minutes_ago": 7,
        "runbook": "database.md",
        "expected_remediation": "rollback deployment",
        "expected_risk": "medium",
        "severity": "P1",
    },
    {
        "type": "memory_leak",
        "service": "checkout-service",
        "root_cause": "application memory leak",
        "metrics": {"error_rate": 0.05, "p95_latency_ms": 900, "cpu_pct": 30, "memory_pct": 94},
        "logs": ["OOM killer invoked for checkout-service", "heap allocation failure, GC overhead limit"],
        "deployment_minutes_ago": 300,
        "runbook": "kubernetes.md",
        "expected_remediation": "restart pods",
        "expected_risk": "low",
        "severity": "P2",
    },
    {
        "type": "redis_unavailable",
        "service": "session-service",
        "root_cause": "redis connection refused",
        "metrics": {"error_rate": 0.41, "p95_latency_ms": 3100, "cpu_pct": 20, "redis_up": 0},
        "logs": ["ECONNREFUSED redis:6379", "session store unreachable, failing over"],
        "deployment_minutes_ago": 2,
        "runbook": "redis.md",
        "expected_remediation": "restart redis",
        "expected_risk": "medium",
        "severity": "P1",
    },
    {
        "type": "traffic_spike",
        "service": "search-api",
        "root_cause": "unprovisioned traffic spike",
        "metrics": {"error_rate": 0.12, "p95_latency_ms": 1800, "cpu_pct": 88, "request_rate": 9000},
        "logs": ["queue depth increasing, worker saturation", "upstream timeout on /search"],
        "deployment_minutes_ago": 4000,
        "runbook": "networking.md",
        "expected_remediation": "scale replicas",
        "expected_risk": "low",
        "severity": "P2",
    },
    {
        "type": "bad_deployment_crashloop",
        "service": "auth-service",
        "root_cause": "bad deployment causing crashloop",
        "metrics": {"error_rate": 0.65, "p95_latency_ms": 0, "cpu_pct": 5, "pods_ready": 0},
        "logs": ["CrashLoopBackOff: back-off restarting failed container", "panic: nil pointer dereference in auth handler"],
        "deployment_minutes_ago": 3,
        "runbook": "kubernetes.md",
        "expected_remediation": "rollback deployment",
        "expected_risk": "medium",
        "severity": "P1",
    },
    {
        "type": "dns_resolution_failure",
        "service": "api-gateway",
        "root_cause": "upstream dns resolution failure",
        "metrics": {"error_rate": 0.33, "p95_latency_ms": 4500, "cpu_pct": 25, "request_rate": 2500},
        "logs": ["getaddrinfo EAI_AGAIN payments.internal", "upstream host resolution failed, retrying"],
        "deployment_minutes_ago": 900,
        "runbook": "networking.md",
        "expected_remediation": "restart pods",
        "expected_risk": "low",
        "severity": "P1",
        "novel": True,
    },
    {
        "type": "retry_storm_cascade",
        "service": "order-service",
        "root_cause": "client retry storm cascading into overload",
        "metrics": {"error_rate": 0.22, "p95_latency_ms": 3900, "cpu_pct": 91, "request_rate": 22000},
        "logs": ["retry budget exhausted on /orders", "circuit breaker open for inventory-client", "duplicate request ids flooding"],
        "deployment_minutes_ago": 1500,
        "runbook": "networking.md",
        "expected_remediation": "scale replicas",
        "expected_risk": "low",
        "severity": "P2",
        "novel": True,
    },
    {
        "type": "disk_pressure_evictions",
        "service": "worker-queue",
        "root_cause": "node disk pressure evicting pods",
        "metrics": {"error_rate": 0.18, "p95_latency_ms": 1200, "cpu_pct": 40, "memory_pct": 55, "pods_ready": 1},
        "logs": ["Evicted: The node had condition: [DiskPressure]", "no space left on device writing checkpoint"],
        "deployment_minutes_ago": 2600,
        "runbook": "kubernetes.md",
        "expected_remediation": "restart pods",
        "expected_risk": "low",
        "severity": "P2",
        "novel": True,
    },
    {
        "type": "slow_query_degradation",
        "service": "payment-api",
        "root_cause": "slow database query degrading latency",
        "metrics": {"error_rate": 0.045, "p95_latency_ms": 1150, "cpu_pct": 52, "memory_pct": 58, "db_connections": 45, "request_rate": 1800},
        "logs": ["slow query: SELECT orders took 980ms", "p95 latency above SLO for 10m, error budget burning slowly"],
        "deployment_minutes_ago": 700,
        "runbook": "database.md",
        "expected_remediation": "rollback deployment",
        "expected_risk": "medium",
        "severity": "P3",
    },
    {
        "type": "cache_hit_drop",
        "service": "search-api",
        "root_cause": "cache hit ratio drop overloading origin",
        "metrics": {"error_rate": 0.035, "p95_latency_ms": 950, "cpu_pct": 68, "memory_pct": 62, "request_rate": 4200},
        "logs": ["cache hit ratio 0.41 below threshold 0.8", "origin latency climbing as cache bypass grows"],
        "deployment_minutes_ago": 1200,
        "runbook": "networking.md",
        "expected_remediation": "scale replicas",
        "expected_risk": "low",
        "severity": "P3",
    },
    {
        "type": "minor_error_blip",
        "service": "checkout-service",
        "root_cause": "transient upstream error blip",
        "metrics": {"error_rate": 0.012, "p95_latency_ms": 320, "cpu_pct": 28, "memory_pct": 48, "request_rate": 900},
        "logs": ["transient upstream timeout, succeeded on retry", "single error burst, no sustained failure"],
        "deployment_minutes_ago": 5000,
        "runbook": "networking.md",
        "expected_remediation": "restart pods",
        "expected_risk": "low",
        "severity": "P4",
    },
]

NOVEL_TYPES = {s["type"] for s in SCENARIOS if s.get("novel")}

BACKGROUND_RANGES = {
    "error_rate": (0.001, 0.01),
    "p95_latency_ms": (80, 450),
    "cpu_pct": (15, 60),
    "memory_pct": (35, 70),
    "request_rate": (300, 2500),
    "db_connections": (5, 40),
    "redis_up": (1, 1),
    "pods_ready": (1, 1),
}


def sample_background():
    bg = {}
    for k, (lo, hi) in BACKGROUND_RANGES.items():
        if k in ("redis_up", "pods_ready"):
            bg[k] = 1
        elif k == "error_rate":
            bg[k] = round(random.uniform(lo, hi), 4)
        elif k == "p95_latency_ms":
            bg[k] = round(random.uniform(lo, hi), 1)
        elif k == "request_rate":
            bg[k] = int(random.uniform(lo, hi))
        else:
            bg[k] = round(random.uniform(lo, hi), 1)
    return bg


def jitter(v, pct=0.15):
    if isinstance(v, (int, float)):
        return round(v * (1 + random.uniform(-pct, pct)), 2)
    return v


def generate(n=160, out_dir=None):
    if out_dir is None:
        out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "incidents")
    out_dir = os.path.abspath(out_dir)
    os.makedirs(out_dir, exist_ok=True)

    classic = [s for s in SCENARIOS if not s.get("novel")][:5]
    for i in range(n):
        if i < len(classic):
            base = classic[i]
        else:
            base = random.choices(SCENARIOS, weights=[1 if s.get("novel") else 2 for s in SCENARIOS])[0]
        inc_id = f"incident_{i+1:03d}"
        folder = os.path.join(out_dir, inc_id)
        os.makedirs(folder, exist_ok=True)

        metrics = sample_background()
        for k, v in base["metrics"].items():
            metrics[k] = jitter(v, 0.2)
        if random.random() < 0.05:
            metrics.pop(random.choice(["cpu_pct", "memory_pct", "request_rate"]), None)
        record = {
            "incident_id": inc_id,
            "service": base["service"],
            "environment": "production",
            "alert_type": base["type"],
            "description": f"{base['type']} on {base['service']}",
            "metrics": metrics,
            "logs": base["logs"],
            "deployment_minutes_ago": jitter(base["deployment_minutes_ago"], 0.3),
            "ground_truth": {
                "root_cause": base["root_cause"],
                "severity": base["severity"],
                "runbook": base["runbook"],
                "expected_remediation": base["expected_remediation"],
                "expected_risk": base["expected_risk"],
            },
        }
        with open(os.path.join(folder, "incident.json"), "w") as f:
            json.dump(record, f, indent=2)

    print(f"wrote {n} incidents to {out_dir}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--n", type=int, default=160)
    p.add_argument("--out", type=str, default=None)
    args = p.parse_args()
    random.seed(42)
    generate(n=args.n, out_dir=args.out)
