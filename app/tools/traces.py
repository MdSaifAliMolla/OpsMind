import logging
import os
import threading

import requests

log = logging.getLogger(__name__)

_session = requests.Session()
_session.trust_env = False  # local infra only, ignore proxy env vars
TIMEOUT = 3

_lock = threading.Lock()
_down = False


def _base() -> str:
    return os.getenv("JAEGER_URL", "http://localhost:16686")


def get_trace(service: str, limit: int = 5) -> list:
    global _down
    with _lock:
        if _down:
            return []
    try:
        r = _session.get(f"{_base()}/api/traces", params={"service": service},
                         timeout=TIMEOUT)
        if not r.ok:
            return []
        out = []
        for t in r.json().get("data", [])[:limit]:
            spans = t.get("spans", [])
            errors = sum(1 for s in spans
                         if any(tag.get("key") == "error" and tag.get("value") is True
                                for tag in s.get("tags", [])))
            durations = [s.get("duration", 0) for s in spans]
            out.append({
                "traceID": t.get("traceID"),
                "spans": len(spans),
                "error_spans": errors,
                "max_duration_us": max(durations) if durations else 0,
                "operations": sorted({s.get("operationName", "") for s in spans})[:8],
            })
        return out
    except Exception as e:
        log.debug(f"jaeger query failed, no traces: {e}")
        with _lock:
            _down = True
        return []
