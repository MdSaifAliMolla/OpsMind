import os

import requests

_session = requests.Session()
_session.trust_env = False
TIMEOUT = 2


def _base() -> str:
    base = os.getenv("LOKI_URL", "").strip()
    if not base:
        raise RuntimeError("LOKI_URL is required (no empty fallback)")
    return base


def _query(base: str, logql: str, start: str = "", end: str = ""):
    params = {"query": logql, "limit": 20}
    if start:
        params["start"] = start
    if end:
        params["end"] = end
    r = _session.get(f"{base}/loki/api/v1/query_range", params=params,
                     timeout=TIMEOUT)
    r.raise_for_status()
    out = []
    for res in (r.json().get("data") or {}).get("result", []):
        for v in res.get("values", []):
            if len(v) > 1:
                out.append(str(v[1])[:500])
            if len(out) >= 20:
                return out
    return out


def search_logs(service: str, query: str, incident=None):
    base = _base()
    window = ((incident or {}).get("alert_window") or {}) if isinstance(incident, dict) else {}
    start, end = str(window.get("start", "")), str(window.get("end", ""))
    safe_q = (query or "").replace('"', "")
    logql = f'{{app="{service}"}} |= "{safe_q}"' if safe_q else f'{{app="{service}"}}'
    out = _query(base, logql, start, end)
    if not out:
        raise RuntimeError(f"loki: no logs for service={service}")
    return out
