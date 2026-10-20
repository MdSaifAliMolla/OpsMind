import datetime
import os

import requests

_session = requests.Session()
_session.trust_env = False
TIMEOUT = 2


def _base() -> str:
    base = os.getenv("PROMETHEUS_URL", "").strip()
    if not base:
        raise RuntimeError("PROMETHEUS_URL is required (no synthetic fallback)")
    return base


def query_prometheus(service: str, metric: str):
    now = datetime.datetime.now().isoformat()
    r = _session.get(f"{_base()}/api/v1/query",
                     params={"query": f'{metric}{{service="{service}"}}'}, timeout=TIMEOUT)
    r.raise_for_status()
    results = (r.json().get("data") or {}).get("result") or []
    if not results:
        raise RuntimeError(f"prometheus: no data for {service}/{metric}")
    v = results[0]["value"][1]
    return {"value": float(v), "timestamp": now}


def query_metric(incident: dict, metric: str):
    return query_prometheus(incident.get("service", "unknown"), metric)
