import os
import threading
import time

_lock = threading.Lock()
_hits: dict = {}
_MAX_IPS = 1000


def rate_limit_per_min() -> float:
    try:
        return max(0.0, float(os.getenv("OPSMIND_RATE_LIMIT_PER_MIN", "0")))
    except (TypeError, ValueError):
        return 0.0


def check(ip: str, limit_per_min: float = None, now: float = None):
    if limit_per_min is None:
        limit_per_min = rate_limit_per_min()
    if limit_per_min <= 0:
        return True, 0
    now = time.time() if now is None else now
    window = 60.0
    ip = (ip or "unknown")[:64]
    with _lock:
        stamps = [t for t in _hits.get(ip, []) if now - t < window]
        if len(stamps) >= limit_per_min:
            retry = max(1, int(window - (now - stamps[0])))
            _hits[ip] = stamps
            return False, retry
        stamps.append(now)
        if len(_hits) >= _MAX_IPS and ip not in _hits:
            try:
                _hits.pop(next(iter(_hits)))
            except StopIteration:
                pass
        _hits[ip] = stamps
        return True, 0


def client_ip(request) -> str:
    try:
        fwd = request.headers.get("x-forwarded-for", "")
        if fwd:
            return fwd.split(",")[0].strip()[:64]
        return (request.client.host if request.client else "unknown")[:64]
    except Exception:
        return "unknown"


def reset():
    with _lock:
        _hits.clear()
