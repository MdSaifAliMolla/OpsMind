import datetime
import os
import threading

import requests

_session = requests.Session()
_session.trust_env = False  # ignore proxy env vars, we only talk to local infra
TIMEOUT = 2

_lock = threading.Lock()
_down = False  # once prometheus fails, stop stalling every call on it

_recovery_factor: dict = {}
_MAX_RECOVERY_KEYS = 1000


def set_recovered(incident_id: str, factor=0.08):
    with _lock:
        if len(_recovery_factor) >= _MAX_RECOVERY_KEYS and incident_id not in _recovery_factor:
            try:
                _recovery_factor.pop(next(iter(_recovery_factor)))
            except StopIteration:
                pass
        _recovery_factor[incident_id] = factor


def query_prometheus(service: str, metric: str):
    global _down
    now = datetime.datetime.now().isoformat()
    with _lock:
        down = _down
    if down:
        return {"value": 0, "timestamp": now}
    base = os.getenv("PROMETHEUS_URL", "http://localhost:9090")
    try:
        r = _session.get(f"{base}/api/v1/query",
                         params={"query": f'{metric}{{service="{service}"}}'}, timeout=TIMEOUT)
        if r.ok:
            results = (r.json().get("data") or {}).get("result") or []
            if results:
                v = results[0]["value"][1]
                return {"value": float(v), "timestamp": now}
            return {"value": 0, "timestamp": now}
    except Exception:
        with _lock:
            _down = True
    return {"value": 0, "timestamp": now}


def query_metric_synthetic(incident: dict, metric: str):
    live = query_prometheus(incident.get("service", "unknown"), metric)
    if live["value"] != 0:
        return live
    from app.ml.features import DEFAULTS
    value = float(incident.get("metrics", {}).get(metric, DEFAULTS.get(metric, 0)))
    with _lock:
        factor = _recovery_factor.get(incident.get("incident_id"), 1.0)
    if factor != 1.0 and metric in ("error_rate", "p95_latency_ms"):
        value = round(value * factor, 4)
    return {"value": value, "timestamp": datetime.datetime.now().isoformat()}
