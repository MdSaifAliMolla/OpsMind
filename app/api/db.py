import logging
import os
import threading

log = logging.getLogger(__name__)

_pool = None
_pool_lock = threading.Lock()
memory_store = {}
memory_approvals = []
_MAX_MEMORY = 1000


def get_pool():
    global _pool
    with _pool_lock:
        if _pool is not None:
            return _pool
    if not os.getenv("DATABASE_URL"):
        return None
    try:
        from psycopg2 import pool as pg_pool
        with _pool_lock:
            if _pool is None:
                _pool = pg_pool.SimpleConnectionPool(1, 5, dsn=os.getenv("DATABASE_URL"))
            return _pool
    except Exception as e:
        log.debug(f"db pool unavailable: {e}")
        return None


def _exec(query, params=()):
    p = get_pool()
    if p is None:
        return
    conn = p.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(query, params)
        conn.commit()
    except Exception as e:
        conn.rollback()
        log.debug(f"db write skipped: {e}")
    finally:
        p.putconn(conn)


def save_incident(row: dict):
    if row.get("id"):
        memory_store[row["id"]] = row
        if len(memory_store) > _MAX_MEMORY:
            try:
                memory_store.pop(next(iter(memory_store)))
            except StopIteration:
                pass
    _exec(
        """INSERT INTO incidents (id, service, environment, alert_type, description, severity, status)
           VALUES (%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT (id) DO UPDATE SET severity=EXCLUDED.severity, status=EXCLUDED.status""",
        (row["id"], row["service"], row["environment"], row["alert_type"],
         row.get("description", ""), row.get("severity"), row.get("status", "open")),
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

    prev = ""
    for row in reversed(memory_approvals):
        if row.get("incident_id") == incident_id and row.get("row_hash"):
            prev = row["row_hash"]
            break
    payload = json.dumps({"prev": prev, "incident_id": incident_id,
                          "approver": approver, "plan_hash": plan_hash,
                          "decision": decision}, sort_keys=True)
    row_hash = hashlib.sha256(payload.encode()).hexdigest()[:16]
    memory_approvals.append({
        "incident_id": incident_id, "approver": approver[:64],
        "approver_source": approver_source[:16], "plan_hash": plan_hash[:16],
        "idempotency_key": (idempotency_key or "")[:64], "decision": decision[:16],
        "prev_hash": prev, "row_hash": row_hash,
    })
    if len(memory_approvals) > _MAX_MEMORY:
        del memory_approvals[:-_MAX_MEMORY]
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
    if p is None:
        return None
    try:
        conn = p.getconn()
    except Exception:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT thread_id, state FROM state_snapshots WHERE incident_id=%s",
                        (incident_id,))
            row = cur.fetchone()
        if not row:
            return None
        raw = row[1]
        if isinstance(raw, dict):
            state = raw
        elif isinstance(raw, str):
            try:
                state = json.loads(raw)
            except Exception:
                return None
        else:
            return None
        if not isinstance(state, dict) or "incident" not in state:
            return None
        return {"thread_id": row[0], "state": state}
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return None
    finally:
        try:
            p.putconn(conn)
        except Exception:
            pass
