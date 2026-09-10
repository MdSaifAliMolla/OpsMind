import logging
import os
import re

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from app.agents.graph import is_paused, resume, run_incident
from app.api import db as store
from app.observability import metrics
from app.observability.langfuse import get_trace_handler
from app.observability.notifier import notify

load_dotenv()
log = logging.getLogger("opsmind")

app = FastAPI(title="opsmind")
threads: dict = {}  # incident_id -> langgraph thread_id


@app.get("/health")
def health():
    return {"ok": True, "pending": len(threads)}


@app.get("/metrics")
def agent_metrics():
    return PlainTextResponse(metrics.render())


@app.get("/demo/{incident_id}.json")
def demo_blob(incident_id: str):
    safe = re.sub(r"[^a-z0-9_]", "", incident_id)
    path = os.path.join(os.getcwd(), "data/incidents", safe, "incident.json")
    if not os.path.isfile(path):
        raise HTTPException(404, "unknown demo incident")
    return FileResponse(path)


@app.get("/incidents")
def list_incidents():
    return list(store.memory_store.values())


@app.get("/incidents/{incident_id}")
def get_incident(incident_id: str):
    tid = threads.get(incident_id)
    if tid is not None:
        from app.agents.graph import _config, ops_mind_graph
        return ops_mind_graph.get_state(_config(tid)).values
    snap = store.load_snapshot(incident_id)
    if snap is not None:
        return snap["state"]
    raise HTTPException(404, "unknown incident")


@app.post("/incidents/alertmanager")
async def alertmanager_webhook(payload: dict):
    """Alertmanager webhook receiver: normalizes firing alerts into incidents."""
    import asyncio

    results = []
    for alert in payload.get("alerts", []):
        if alert.get("status") == "resolved":
            continue
        labels = alert.get("labels", {})
        annotations = alert.get("annotations", {})
        incident = {
            "incident_id": re.sub(r"[^a-z0-9_]", "",
                                  alert.get("fingerprint", labels.get("alertname", "alert")).lower())[:32]
            or f"am-{len(threads)}",
            "service": labels.get("service", labels.get("instance", "unknown")),
            "environment": labels.get("environment", "production"),
            "alert_type": labels.get("alertname", "prometheus_alert").lower(),
            "description": annotations.get("summary", ""),
            "metrics": {},
            "logs": [],
            "deployment_minutes_ago": 9999,
        }
        result, tid = await asyncio.to_thread(run_incident, incident,
                                              f"{incident['incident_id']}-{len(threads)}")
        threads[incident["incident_id"]] = tid
        _persist(incident, tid, result)
        results.append(result)
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


@app.post("/incidents")
async def create_incident(incident: dict):
    import asyncio

    if not incident.get("incident_id") or not incident.get("service"):
        raise HTTPException(400, "incident_id and service are required")

    last_error = None
    result, tid = None, None
    handler = get_trace_handler()
    callbacks = [handler] if handler else None
    for attempt in range(2):  # one retry before we call it failed
        try:
            result, tid = await asyncio.to_thread(
                run_incident, incident,
                f"{incident['incident_id']}-{len(threads)}", callbacks,
            )
            break
        except Exception as e:
            last_error = e
            log.warning(f"graph run failed (attempt {attempt + 1}/2): {e}")
    if result is None:
        metrics.record_failure()
        store.save_incident({**{k: incident.get(k) for k in
                                ("service", "environment", "alert_type", "description")},
                             "id": incident["incident_id"], "status": "failed"})
        raise HTTPException(500, f"investigation failed twice: {last_error}")

    threads[incident["incident_id"]] = tid
    _persist(incident, tid, result)

    if result.get("severity") == "P1":
        notify("triage", incident, f"severity P1, cause: {result.get('root_cause')}")
    if result.get("approval_status") == "awaiting_human":
        notify("approval-needed", incident, f"proposed fix: {result['remediation_plan']['action']}")
    return result


@app.post("/incidents/{incident_id}/approve")
async def approve_incident(incident_id: str, body: dict = None):
    import asyncio

    from app.agents.graph import _config, ops_mind_graph

    tid = threads.get(incident_id)
    if tid is None:
        # server restarted and the thread only lives in the snapshot:
        # re-run on a fresh thread (deterministic, so the proposal matches).
        snap = store.load_snapshot(incident_id)
        if snap is None:
            raise HTTPException(404, "unknown incident")
        incident = snap["state"]["incident"]
        result, tid = await asyncio.to_thread(run_incident, incident)
        threads[incident_id] = tid
        if not is_paused(tid):
            _persist(incident, tid, result)
            return result
    else:
        incident = ops_mind_graph.get_state(_config(tid)).values["incident"]

    if not is_paused(tid):
        return ops_mind_graph.get_state(_config(tid)).values

    try:
        handler = get_trace_handler()
        result = await asyncio.to_thread(
            resume, tid, [handler] if handler else None)
    except Exception as e:
        raise HTTPException(500, f"resume failed: {e}")
    result["approved_by"] = (body or {}).get("approved_by", "human")
    result["approval_status"] = "approved"
    if (result.get("verification_result") or {}).get("healthy"):
        from app.agents.postmortem import write_postmortem
        pm = write_postmortem({**result, "incident": incident})
        if pm:
            result["postmortem"] = pm
    _persist(incident, tid, result)
    notify("executed", incident, f"ran {result['remediation_plan']['action']}, "
                                 f"healthy={result.get('verification_result', {}).get('healthy')}")
    return result


# mounted last so /incidents/* and friends take precedence
app.mount("/", StaticFiles(directory=os.path.join(os.getcwd(), "public"), html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "4000")))
