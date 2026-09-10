import logging
import os

log = logging.getLogger(__name__)

_pool = None
memory_store = {}


def get_pool():
    global _pool
    if _pool is not None:
        return _pool
    if not os.getenv("DATABASE_URL"):
        return None
    try:
        from psycopg2 import pool as pg_pool
        _pool = pg_pool.SimpleConnectionPool(1, 5, dsn=os.getenv("DATABASE_URL"))
        return _pool
    except Exception:
        _pool = None
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
    memory_store[row["id"]] = row
    _exec(
        """INSERT INTO incidents (id, service, environment, alert_type, description, severity, status)
           VALUES (%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT (id) DO UPDATE SET severity=EXCLUDED.severity, status=EXCLUDED.status""",
        (row["id"], row["service"], row["environment"], row["alert_type"],
         row.get("description", ""), row.get("severity"), row.get("status", "open")),
    )


def save_evidence(incident_id: str, evidence: list):
    import json
    for e in evidence[:20]:
        _exec("INSERT INTO evidence (incident_id, source, payload) VALUES (%s,%s,%s)",
              (incident_id, str(e.get("source", "unknown")), json.dumps(e)))


def save_hypotheses(incident_id: str, hyps: list, root_cause):
    for h in hyps:
        _exec("INSERT INTO hypotheses (incident_id, root_cause, confidence, selected) VALUES (%s,%s,%s,%s)",
              (incident_id, h["root_cause"], h["confidence"], h["root_cause"] == root_cause))


def save_remediation(incident_id: str, action: str, risk: str, status: str):
    _exec("INSERT INTO remediations (incident_id, action, risk_level, status) VALUES (%s,%s,%s,%s)",
          (incident_id, action, risk, status))


def save_snapshot(incident_id: str, thread_id: str, state: dict):
    import json
    _exec(
        """INSERT INTO state_snapshots (incident_id, thread_id, state)
           VALUES (%s,%s,%s)
           ON CONFLICT (incident_id) DO UPDATE SET thread_id=EXCLUDED.thread_id,
             state=EXCLUDED.state, updated_at=now()""",
        (incident_id, thread_id, json.dumps(state, default=str)),
    )


def load_snapshot(incident_id: str):
    import json
    p = get_pool()
    if p is None:
        return None
    conn = p.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT thread_id, state FROM state_snapshots WHERE incident_id=%s",
                        (incident_id,))
            row = cur.fetchone()
        return {"thread_id": row[0], "state": row[1] if isinstance(row[1], dict) else json.loads(row[1])} \
            if row else None
    except Exception:
        conn.rollback()
        return None
    finally:
        p.putconn(conn)
