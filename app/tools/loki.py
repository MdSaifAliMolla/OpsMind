import os
import threading

import requests

_session = requests.Session()
_session.trust_env = False
TIMEOUT = 2

_lock = threading.Lock()
_down = False


def _query(base: str, logql: str):
    r = _session.get(f"{base}/loki/api/v1/query_range",
                     params={"query": logql, "limit": 20},
                     timeout=TIMEOUT)
    if not r.ok:
        return []
    out = []
    for res in (r.json().get("data") or {}).get("result", []):
        for v in res.get("values", []):
            if len(v) > 1:
                out.append(str(v[1])[:500])
            if len(out) >= 20:
                return out
    return out


def search_logs(service: str, query: str, incident=None):
    global _down
    if incident and incident.get("logs"):
        return [str(x)[:500] for x in incident["logs"][:20]]
    with _lock:
        if _down:
            return []

    base = os.getenv("LOKI_URL", "http://localhost:3100")
    try:
        safe_q = (query or "").replace('"', "")
        candidates = [
            f'{{service="{service}"}} |= "{safe_q}"' if safe_q else f'{{service="{service}"}}',
            f'{{service=~".*{service}.*"}} |= "{safe_q}"' if safe_q else f'{{service=~".*{service}.*"}}',
            f'{{service=~".+"}} |= "{safe_q}"' if safe_q else None,
        ]
        for logql in candidates:
            if not logql:
                continue
            out = _query(base, logql)
            if out:
                return out
        return []
    except Exception:
        with _lock:
            _down = True
    return []
