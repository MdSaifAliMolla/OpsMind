import os

import requests

_session = requests.Session()
_session.trust_env = False
TIMEOUT = 2

_down = False


def search_logs(service: str, query: str, incident=None):
    global _down
    if incident and incident.get("logs"):
        return incident["logs"]
    if _down:
        return []

    base = os.getenv("LOKI_URL", "http://localhost:3100")
    try:
        r = _session.get(f"{base}/loki/api/v1/query_range",
                         params={"query": f'{{service="{service}"}} |= "{query}"', "limit": 20},
                         timeout=TIMEOUT)
        if r.ok:
            out = []
            for res in r.json()["data"]["result"]:
                out.extend(v[1] for v in res.get("values", []))
            if out:
                return out
    except Exception:
        _down = True
    return []
