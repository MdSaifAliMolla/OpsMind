import json
import os

import pandas as pd

FEATURE_COLUMNS = [
    "error_rate",
    "p95_latency_ms",
    "cpu_pct",
    "memory_pct",
    "request_rate",
    "deployment_minutes_ago",
    "db_connections",
    "redis_up",
    "pods_ready",
]

DEFAULTS = {
    "error_rate": 0,
    "p95_latency_ms": 0,
    "cpu_pct": 0,
    "memory_pct": 0,
    "request_rate": 0,
    "deployment_minutes_ago": 99999,
    "db_connections": 0,
    "redis_up": 1,
    "pods_ready": 1,
}


def incident_to_features(record: dict) -> dict:
    m = record.get("metrics", {})
    feats = {c: m.get(c, DEFAULTS[c]) for c in FEATURE_COLUMNS}
    feats["deployment_minutes_ago"] = record.get(
        "deployment_minutes_ago", DEFAULTS["deployment_minutes_ago"]
    )
    return feats


def load_dataset(incidents_dir=None):
    if incidents_dir is None:
        incidents_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../data/incidents")
    incidents_dir = os.path.abspath(incidents_dir)
    rows = []
    for name in sorted(os.listdir(incidents_dir)):
        path = os.path.join(incidents_dir, name, "incident.json")
        if not os.path.isfile(path):
            continue
        with open(path) as f:
            rec = json.load(f)
        feats = incident_to_features(rec)
        feats["severity"] = rec["ground_truth"]["severity"]
        rows.append(feats)
    return pd.DataFrame(rows)
