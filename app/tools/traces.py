import os

import requests

_session = requests.Session()
_session.trust_env = False
TIMEOUT = 3


def _base() -> str:
    base = os.getenv("JAEGER_URL", "").strip()
    if not base:
        raise RuntimeError("JAEGER_URL is required (no empty fallback)")
    return base


def get_trace(service: str, limit: int = 5) -> list:
    r = _session.get(f"{_base()}/api/traces", params={"service": service},
                     timeout=TIMEOUT)
    r.raise_for_status()
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
