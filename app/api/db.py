import logging
import os
import threading

log = logging.getLogger(__name__)

_pool = None
_pool_lock = threading.Lock()


def get_pool():
    global _pool
    with _pool_lock:
        if _pool is not None:
            return _pool
    dsn = os.getenv("DATABASE_URL", "").strip()
    if not dsn:
        raise RuntimeError("DATABASE_URL is required (no memory fallback)")
    from psycopg_pool import ConnectionPool
    with _pool_lock:
        if _pool is None:
            _pool = ConnectionPool(dsn, min_size=1, max_size=5, open=True)
        return _pool


def _exec(query, params=()):
    p = get_pool()
    conn = p.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(query, params)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        p.putconn(conn)


def save_incident(row: dict):
    _exec(
        """INSERT INTO incidents (id, service, namespace, environment, alert_type, description, severity, status)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT (id) DO UPDATE SET severity=EXCLUDED.severity, status=EXCLUDED.status,
           namespace=EXCLUDED.namespace""",
        (row["id"], row["service"], row.get("namespace") or "default", row["environment"],
         row["alert_type"], row.get("description", ""), row.get("severity"),
         row.get("status", "open")),
    )


def save_evidence(incident_id: str, evidence: list):
    import json
    for e in (evidence or [])[:20]:
        if not isinstance(e, dict):
            continue
        _exec("INSERT INTO evidence (incident_id, source, payload) VALUES (%s,%s,%s)",
              (incident_id, str(e.get("source", "unknown"))[:128], json.dumps(e)[:8000]))


def save_hypotheses(incident_id: str, hyps: list, root_cause):
    for h in hyps or []:
        if not isinstance(h, dict) or not h.get("root_cause"):
            continue
        try:
            conf = float(h.get("confidence", 0))
        except (TypeError, ValueError):
            continue
        _exec("INSERT INTO hypotheses (incident_id, root_cause, confidence, selected) VALUES (%s,%s,%s,%s)",
              (incident_id, str(h["root_cause"])[:500], conf, h["root_cause"] == root_cause))


def save_remediation(incident_id: str, action: str, risk: str, status: str):
    _exec("INSERT INTO remediations (incident_id, action, risk_level, status) VALUES (%s,%s,%s,%s)",
          (incident_id, str(action)[:128], str(risk)[:32], str(status)[:32]))


def save_approval(incident_id: str, approver: str, approver_source: str,
                  plan_hash: str, idempotency_key: str, decision: str):
    import hashlib
    import json

    p = get_pool()
    conn = p.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT row_hash FROM approvals WHERE incident_id=%s ORDER BY id DESC LIMIT 1",
                (incident_id,),
            )
            r = cur.fetchone()
            prev = r[0] if r and r[0] else ""
    finally:
        p.putconn(conn)
    payload = json.dumps({"prev": prev, "incident_id": incident_id,
                          "approver": approver, "plan_hash": plan_hash,
                          "decision": decision}, sort_keys=True)
    row_hash = hashlib.sha256(payload.encode()).hexdigest()[:16]
    _exec(
        """INSERT INTO approvals
           (incident_id, approver, approver_source, plan_hash, idempotency_key,
            decision, prev_hash, row_hash)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
        (incident_id, approver[:64], approver_source[:16], plan_hash[:16],
         (idempotency_key or "")[:64], decision[:16], prev, row_hash),
    )
    return row_hash


def save_snapshot(incident_id: str, thread_id: str, state: dict):
    import json
    _exec(
        """INSERT INTO state_snapshots (incident_id, thread_id, state)
           VALUES (%s,%s,%s)
           ON CONFLICT (incident_id) DO UPDATE SET thread_id=EXCLUDED.thread_id,
             state=EXCLUDED.state, updated_at=now()""",
        (incident_id, thread_id, json.dumps(state, default=str)[:50000]),
    )


def load_snapshot(incident_id: str):
    import json
    p = get_pool()
    conn = p.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT thread_id, state FROM state_snapshots WHERE incident_id=%s",
                        (incident_id,))
            row = cur.fetchone()
        if not row:
            raise RuntimeError(f"snapshot not found: {incident_id}")
        raw = row[1]
        if isinstance(raw, dict):
            state = raw
        elif isinstance(raw, str):
            state = json.loads(raw)
        else:
            raise RuntimeError(f"snapshot corrupt: {incident_id}")
        if not isinstance(state, dict) or "incident" not in state:
            raise RuntimeError(f"snapshot corrupt: {incident_id}")
        return {"thread_id": row[0], "state": state}
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        p.putconn(conn)


def list_incidents(limit: int = 100):
    p = get_pool()
    conn = p.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, service, namespace, environment, alert_type, description,"
                " severity, status FROM incidents ORDER BY id LIMIT %s",
                (limit,),
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]
    finally:
        p.putconn(conn)
