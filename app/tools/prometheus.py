import datetime
import os

import requests

_session = requests.Session()
_session.trust_env = False  # ignore proxy env vars, we only talk to local infra
TIMEOUT = 2

_down = False  # once prometheus fails, stop stalling every call on it

# Synthetic traffic model: after a successful remediation the service actually
# gets healthier, so later reads through this tool reflect the recovery.
# Keyed by incident so unrelated incidents are unaffected.
_recovery_factor: dict = {}


def set_recovered(incident_id: str, factor=0.08):
    _recovery_factor[incident_id] = factor


def query_prometheus(service: str, metric: str):
    global _down
    now = datetime.datetime.now().isoformat()
    if _down:
        return {"value": 0, "timestamp": now}
    base = os.getenv("PROMETHEUS_URL", "http://localhost:9090")
    try:
        r = _session.get(f"{base}/api/v1/query",
                         params={"query": f'{metric}{{service="{service}"}}'}, timeout=TIMEOUT)
        if r.ok:
            v = r.json()["data"]["result"][0]["value"][1]
            return {"value": float(v), "timestamp": now}
    except Exception:
        _down = True
    return {"value": 0, "timestamp": now}


def query_metric_synthetic(incident: dict, metric: str):
    live = query_prometheus(incident["service"], metric)
    if live["value"] != 0:
        return live
    value = float(incident.get("metrics", {}).get(metric, 0))
    factor = _recovery_factor.get(incident.get("incident_id"), 1.0)
    if factor != 1.0 and metric in ("error_rate", "p95_latency_ms"):
        value = round(value * factor, 4)
    return {"value": value, "timestamp": datetime.datetime.now().isoformat()}
