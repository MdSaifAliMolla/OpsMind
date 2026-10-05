import hashlib
import json
import logging
import os
import threading
import time

log = logging.getLogger(__name__)

_meta_lock = threading.Lock()
_approval_meta: dict = {}  # incident_id -> {"paused_at": float, "plan_hash": str}
_idempotency: dict = {}  # (incident_id, key) -> result dict
_idem_order: list = []
_MAX_META = 1000
_MAX_IDEM = 500
_approve_locks: dict = {}
_approve_locks_lock = threading.Lock()


def plan_hash(plan: dict) -> str:
    return hashlib.sha256(
        json.dumps(plan or {}, sort_keys=True, default=str).encode()).hexdigest()[:16]


def approval_ttl_minutes() -> float:
    try:
        return max(0.0, float(os.getenv("OPSMIND_APPROVAL_TTL_MIN", "60")))
    except (TypeError, ValueError):
        return 60.0


def approver_required() -> bool:
    return os.getenv("OPSMIND_REQUIRE_APPROVER", "false").strip().lower() == "true"


def approve_lock(incident_id: str) -> threading.Lock:
    with _approve_locks_lock:
        lock = _approve_locks.get(incident_id)
        if lock is None:
            lock = threading.Lock()
            if len(_approve_locks) >= _MAX_META:
                try:
                    _approve_locks.pop(next(iter(_approve_locks)))
                except StopIteration:
                    pass
            _approve_locks[incident_id] = lock
        return lock


def mark_paused(incident_id: str, plan: dict):
    with _meta_lock:
        if len(_approval_meta) >= _MAX_META and incident_id not in _approval_meta:
            try:
                _approval_meta.pop(next(iter(_approval_meta)))
            except StopIteration:
                pass
        _approval_meta[incident_id] = {"paused_at": time.time(),
                                       "plan_hash": plan_hash(plan)}


def get_meta(incident_id: str):
    with _meta_lock:
        meta = _approval_meta.get(incident_id)
        return dict(meta) if meta else None


def clear_meta(incident_id: str):
    with _meta_lock:
        _approval_meta.pop(incident_id, None)


def is_expired(incident_id: str):
    meta = get_meta(incident_id)
    if not meta:
        return False, None
    ttl = approval_ttl_minutes()
    if ttl <= 0:
        return False, meta
    return (time.time() - meta["paused_at"]) > ttl * 60, meta


def idempotency_get(incident_id: str, key: str):
    if not key:
        return None
    with _meta_lock:
        return _idempotency.get((incident_id, key))


def idempotency_put(incident_id: str, key: str, result: dict):
    if not key:
        return
    with _meta_lock:
        if (incident_id, key) not in _idempotency:
            _idem_order.append((incident_id, key))
        _idempotency[(incident_id, key)] = result
        while len(_idem_order) > _MAX_IDEM:
            _idempotency.pop(_idem_order.pop(0), None)


def reset_approval_state():
    with _meta_lock:
        _approval_meta.clear()
        _idempotency.clear()
        _idem_order.clear()
    with _approve_locks_lock:
        _approve_locks.clear()
