import logging
import os
import re
import threading
import time
import uuid

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.agents.graph import is_paused, resume, run_incident
from app.api import db as store
from app.observability import metrics
from app.observability.langfuse import flush_traces, get_trace_handler
from app.observability.notifier import notify

load_dotenv()
log = logging.getLogger("opsmind")

threads: dict = {}  # incident_id -> langgraph thread_id
_threads_lock = threading.Lock()


def _new_thread_id(incident_id: str) -> str:
    return f"{incident_id}-{uuid.uuid4().hex[:8]}"


def _set_thread(incident_id: str, tid: str):
    with _threads_lock:
        if len(threads) >= 1000 and incident_id not in threads:
            try:
                threads.pop(next(iter(threads)))
            except StopIteration:
                pass
        threads[incident_id] = tid


def _get_thread(incident_id: str):
    with _threads_lock:
        return threads.get(incident_id)


async def _lifespan(app: FastAPI):
    import asyncio

    def _warm():
        try:
            from app.rag.embeddings import warmup as _embed_warmup

            _embed_warmup()
        except Exception as e:
            log.debug(f"embedding warmup skipped: {e}")
        try:
            from app.observability.langfuse import warmup as _lf_warmup

            _lf_warmup()
        except Exception as e:
            log.debug(f"langfuse warmup skipped: {e}")

    async def _sweep_loop():
        """Expire paused approvals older than OPSMIND_APPROVAL_TTL_MIN."""
        from app.api import approvals as _appr

        while True:
            await asyncio.sleep(60)
            try:
                with _appr._meta_lock:
                    candidates = list(_appr._approval_meta.items())
            except Exception:
                continue
            for incident_id, meta in candidates:
                try:
                    expired, _ = _appr.is_expired(incident_id)
                    if not expired:
                        continue
                    tid = _get_thread(incident_id)
                    if tid is None or not is_paused(tid):
                        _appr.clear_meta(incident_id)
                        continue
                    snap = store.load_snapshot(incident_id)
                    incident = ((snap or {}).get("state") or {}).get("incident",
                                {"incident_id": incident_id})
                    store.save_incident({**{k: incident.get(k) for k in
                                            ("service", "environment", "alert_type",
                                             "description")},
                                         "id": incident_id, "status": "expired"})
                    store.save_approval(incident_id, "system", "sweeper", "", "", "expired")
                    _appr.clear_meta(incident_id)
                    notify("approval-expired", incident,
                           "approval window elapsed; re-investigate for a fresh plan")
                except Exception as e:
                    log.debug(f"approval sweep skipped {incident_id}: {e}")

    asyncio.create_task(asyncio.to_thread(_warm))
    asyncio.create_task(_sweep_loop())
    yield


app = FastAPI(title="opsmind", lifespan=_lifespan)


class IncidentIn(BaseModel):
    incident_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_\-]+$")
    service: str = Field(min_length=1, max_length=128)
    environment: str = Field(default="production", max_length=32)
    alert_type: str = Field(default="unknown", max_length=128)
    description: str = Field(default="", max_length=2000)
    metrics: dict = Field(default_factory=dict)
    logs: list = Field(default_factory=list)
    deployment_minutes_ago: float = Field(default=9999, ge=0, le=1_000_000)


class ApproveIn(BaseModel):
    approved_by: str = Field(default="human", min_length=1, max_length=64)
    plan_hash: str | None = Field(default=None, max_length=64)


class AlertmanagerAlert(BaseModel):
    status: str = "firing"
    fingerprint: str = ""
    labels: dict = Field(default_factory=dict)
    annotations: dict = Field(default_factory=dict)


class AlertmanagerPayload(BaseModel):
    alerts: list[AlertmanagerAlert] = Field(default_factory=list)


@app.middleware("http")
async def _auth_and_timing(request: Request, call_next):
    expected = os.getenv("OPSMIND_API_KEY")
    am_key = os.getenv("OPSMIND_ALERTMANAGER_KEY") or expected
    path = request.url.path
    if request.url.path.startswith("/incidents/alertmanager") and am_key:
        if request.headers.get("x-api-key") != am_key:
            return PlainTextResponse("unauthorized", status_code=401)
    elif expected and (path.startswith("/incidents") or path.startswith("/demo")):
        if request.headers.get("x-api-key") != expected:
            return PlainTextResponse("unauthorized", status_code=401)
    if request.method == "POST" and path.startswith("/incidents"):
        from app.api.ratelimit import check, client_ip
        allowed, retry = check(client_ip(request))
        if not allowed:
            return PlainTextResponse("rate limited", status_code=429,
                                     headers={"Retry-After": str(retry)})
    return await call_next(request)


@app.get("/health")
def health():
    with _threads_lock:
        pending = len(threads)
    return {"ok": True, "pending": pending}


@app.get("/metrics")
def agent_metrics():
    return PlainTextResponse(metrics.render())


@app.get("/demo/{incident_id}.json")
def demo_blob(incident_id: str):
    safe = re.sub(r"[^a-z0-9_]", "", (incident_id or "").lower())[:64]
    if not safe:
        raise HTTPException(404, "unknown demo incident")
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "incidents")
    path = os.path.abspath(os.path.join(base, safe, "incident.json"))
    if not path.startswith(os.path.abspath(base) + os.sep):
        raise HTTPException(404, "unknown demo incident")
    if not os.path.isfile(path):
        raise HTTPException(404, "unknown demo incident")
    return FileResponse(path)


@app.get("/incidents")
def list_incidents():
    return list(store.memory_store.values())


@app.get("/incidents/{incident_id}")
def get_incident(incident_id: str):
    safe = re.sub(r"[^a-zA-Z0-9_\-]", "", incident_id)[:64]
    if not safe:
        raise HTTPException(404, "unknown incident")
    tid = _get_thread(safe)
    if tid is not None:
        from app.agents.graph import _config, ops_mind_graph
        try:
            return ops_mind_graph.get_state(_config(tid)).values
        except Exception:
            pass
    snap = store.load_snapshot(safe)
    if snap is not None:
        return snap["state"]
    raise HTTPException(404, "unknown incident")


@app.post("/incidents/alertmanager")
async def alertmanager_webhook(payload: AlertmanagerPayload):
    """Alertmanager webhook receiver: normalizes firing alerts into incidents."""
    import asyncio

    results = []
    for alert in payload.alerts:
        if alert.status == "resolved":
            continue
        labels = alert.labels or {}
        annotations = alert.annotations or {}
        incident = {
            "incident_id": re.sub(r"[^a-z0-9_]", "",
                                   (alert.fingerprint or labels.get("alertname", "alert")).lower())[:32]
            or f"am-{uuid.uuid4().hex[:8]}",
            "service": str(labels.get("service", labels.get("instance", "unknown")))[:128],
            "environment": str(labels.get("environment", "production"))[:32],
            "alert_type": str(labels.get("alertname", "prometheus_alert")).lower()[:128],
            "description": str(annotations.get("summary", ""))[:2000],
            "metrics": {},
            "logs": [],
            "deployment_minutes_ago": 9999,
        }
        result, tid = await asyncio.to_thread(run_incident, incident,
                                              _new_thread_id(incident["incident_id"]))
        _set_thread(incident["incident_id"], tid)
        _persist(incident, tid, result)
        results.append(result)
    try:
        flush_traces()
    except Exception:
        pass
    return results


def _persist(incident: dict, thread_id: str, result: dict):
    store.save_incident({
        "id": incident["incident_id"],
        "service": incident["service"],
        "environment": incident.get("environment", "production"),
        "alert_type": incident.get("alert_type", "unknown"),
        "description": incident.get("description", ""),
        "severity": result.get("severity"),
        "status": "resolved" if (result.get("verification_result") or {}).get("healthy")
        else "investigating" if result.get("approval_status") == "awaiting_human"
        else "remediating",
    })
    store.save_evidence(incident["incident_id"], result.get("evidence", []))
    store.save_hypotheses(incident["incident_id"], result.get("hypotheses", []),
                           result.get("root_cause"))
    if (result.get("remediation_plan") or {}).get("action"):
        store.save_remediation(incident["incident_id"], result["remediation_plan"]["action"],
                               result.get("risk_level", "unknown"),
                               "executed" if result.get("approval_status") in ("auto_approved", "approved")
                               else "proposed")
    store.save_snapshot(incident["incident_id"], thread_id, result)
    metrics.record_result(result)
    if result.get("approval_status") == "awaiting_human" and result.get("remediation_plan"):
        try:
            from app.api import approvals as _appr
            _appr.mark_paused(incident["incident_id"], result["remediation_plan"])
        except Exception:
            pass


@app.post("/incidents")
async def create_incident(incident: IncidentIn):
    import asyncio

    incident = incident.model_dump()
    if isinstance(incident.get("logs"), list):
        incident["logs"] = [str(x)[:500] for x in incident["logs"][:20]]
    if isinstance(incident.get("metrics"), dict):
        incident["metrics"] = {str(k)[:64]: incident["metrics"][k] for k in list(incident["metrics"])[:32]}

    last_error = None
    result, tid = None, None
    handler = get_trace_handler()
    callbacks = [handler] if handler else None
    started = time.time()
    for attempt in range(2):  # one retry before we call it failed
        try:
            result, tid = await asyncio.to_thread(
                run_incident, incident,
                _new_thread_id(incident["incident_id"]), callbacks,
            )
            break
        except Exception as e:
            last_error = e
            log.warning(f"graph run failed (attempt {attempt + 1}/2): {e}")
    metrics.observe_latency(time.time() - started)
    try:
        flush_traces()
    except Exception:
        pass
    if result is None:
        metrics.record_failure()
        store.save_incident({**{k: incident.get(k) for k in
                                ("service", "environment", "alert_type", "description")},
                             "id": incident["incident_id"], "status": "failed"})
        raise HTTPException(500, f"investigation failed twice: {last_error}")

    _set_thread(incident["incident_id"], tid)
    _persist(incident, tid, result)

    if result.get("severity") == "P1":
        notify("triage", incident, f"severity P1, cause: {result.get('root_cause')}")
    if result.get("approval_status") == "awaiting_human":
        action = (result.get("remediation_plan") or {}).get("action", "unknown")
        notify("approval-needed", incident, f"proposed fix: {action}")
    return result


@app.post("/incidents/{incident_id}/approve")
async def approve_incident(incident_id: str, body: ApproveIn | None = None,
                           request: Request = None):
    import asyncio

    from app.agents.graph import _config, ops_mind_graph
    from app.api import approvals as appr

    safe_id = re.sub(r"[^a-zA-Z0-9_\-]", "", incident_id)[:64]
    if not safe_id:
        raise HTTPException(404, "unknown incident")

    headers = request.headers if request is not None else {}
    header_approver = (headers.get("x-approver") or "").strip()[:64]
    idem_key = (headers.get("idempotency-key") or "").strip()[:64]
    if header_approver:
        approver, approver_source = header_approver, "header"
    elif body and body.approved_by:
        approver, approver_source = body.approved_by[:64], "body"
    else:
        approver, approver_source = "human", "default"
    if appr.approver_required() and not header_approver:
        raise HTTPException(401, "approver identity required (X-Approver header)")

    with appr.approve_lock(safe_id):
        replayed = appr.idempotency_get(safe_id, idem_key)
        if replayed is not None:
            return replayed

        tid = _get_thread(safe_id)
        if tid is None:
            snap = store.load_snapshot(safe_id)
            if snap is None:
                raise HTTPException(404, "unknown incident")
            incident = (snap.get("state") or {}).get("incident")
            if not isinstance(incident, dict):
                raise HTTPException(500, "snapshot corrupted: missing incident")
            result, tid = await asyncio.to_thread(run_incident, incident,
                                                  _new_thread_id(safe_id))
            _set_thread(safe_id, tid)
            if not is_paused(tid):
                _persist(incident, tid, result)
                return result
            appr.mark_paused(safe_id, result.get("remediation_plan") or {})
        else:
            try:
                incident = ops_mind_graph.get_state(_config(tid)).values.get("incident", {})
            except Exception as e:
                raise HTTPException(500, f"could not load incident state: {e}")

        if not is_paused(tid):
            return ops_mind_graph.get_state(_config(tid)).values

        expired, _meta = appr.is_expired(safe_id)
        if expired:
            store.save_incident({**{k: (incident or {}).get(k) for k in
                                    ("service", "environment", "alert_type", "description")},
                                 "id": safe_id, "status": "expired"})
            store.save_approval(safe_id, approver, approver_source, "", idem_key, "expired")
            appr.clear_meta(safe_id)
            notify("approval-expired", incident or {"incident_id": safe_id},
                   "approval window elapsed; re-investigate to propose a fresh plan")
            raise HTTPException(410, "approval expired: re-investigate for a fresh plan")

        try:
            live_plan = (ops_mind_graph.get_state(_config(tid)).values
                         .get("remediation_plan") or {})
        except Exception as e:
            raise HTTPException(500, f"could not load incident state: {e}")
        current_hash = appr.plan_hash(live_plan)
        wanted = (body.plan_hash if body and body.plan_hash else "").strip()[:64]
        if wanted and wanted != current_hash:
            store.save_approval(safe_id, approver, approver_source,
                                wanted, idem_key, "stale")
            raise HTTPException(409, "stale plan: the proposal changed since review; "
                                     "fetch the incident and approve the current plan_hash")

        try:
            handler = get_trace_handler()
            result = await asyncio.to_thread(
                resume, tid, [handler] if handler else None)
        except Exception as e:
            raise HTTPException(500, f"resume failed: {e}")
        finally:
            try:
                flush_traces()
            except Exception:
                pass
        result["approved_by"] = approver
        result["approval_status"] = "approved"
        if (result.get("verification_result") or {}).get("healthy"):
            from app.agents.postmortem import write_postmortem
            try:
                pm = write_postmortem({**result, "incident": incident})
            except Exception as e:
                log.warning(f"postmortem failed: {e}")
                pm = None
            if pm:
                result["postmortem"] = pm
        store.save_approval(safe_id, approver, approver_source,
                            current_hash, idem_key, "approved")
        appr.clear_meta(safe_id)
        appr.idempotency_put(safe_id, idem_key, dict(result))
        _persist(incident, tid, result)
        action = (result.get("remediation_plan") or {}).get("action", "unknown")
        healthy = (result.get("verification_result") or {}).get("healthy")
        notify("executed", incident, f"ran {action}, healthy={healthy}")
        return result


# static dashboard mounted last
_PUBLIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "public")
app.mount("/", StaticFiles(directory=_PUBLIC_DIR, html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "4000")))
