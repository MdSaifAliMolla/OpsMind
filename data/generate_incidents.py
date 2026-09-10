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
    # novel families: deliberately outside the rules engine's coverage,
    # so the eval can measure what the LLM adds over rules
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
]

NOVEL_TYPES = {s["type"] for s in SCENARIOS if s.get("novel")}


def jitter(v, pct=0.15):
    if isinstance(v, (int, float)):
        return round(v * (1 + random.uniform(-pct, pct)), 2)
    return v


def generate(n=40, out_dir=None):
    if out_dir is None:
        out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "incidents")
    out_dir = os.path.abspath(out_dir)
    os.makedirs(out_dir, exist_ok=True)

    for i in range(n):
        base = random.choices(SCENARIOS, weights=[1 if s.get("novel") else 2 for s in SCENARIOS])[0]
        inc_id = f"incident_{i+1:03d}"
        folder = os.path.join(out_dir, inc_id)
        os.makedirs(folder, exist_ok=True)

        metrics = {k: jitter(v) for k, v in base["metrics"].items()}
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
    p.add_argument("--n", type=int, default=40)
    p.add_argument("--out", type=str, default=None)
    args = p.parse_args()
    random.seed(42)
    generate(n=args.n, out_dir=args.out)
