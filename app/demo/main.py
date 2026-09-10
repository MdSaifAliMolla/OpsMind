"""Toy checkout service that emits real Prometheus metrics and can break on demand.

GET  /health, /metrics
POST /chaos/{mode}  (mode: ok | errors | slow)  -> flips the failure switch
GET  /checkout      -> simulated checkout, fails fast when chaos=errors
"""
import os
import random
import time

from fastapi import FastAPI, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Histogram,
    generate_latest,
)

app = FastAPI(title="demo-checkout")

CHECKOUTS = Counter("demo_checkouts_total", "Checkouts attempted", ["status"])
LATENCY = Histogram("demo_checkout_latency_seconds", "Checkout latency")
MODE = {"chaos": "ok"}


@app.get("/health")
def health():
    return {"ok": True, "chaos": MODE["chaos"]}


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/chaos/{mode}")
def set_chaos(mode: str):
    if mode not in ("ok", "errors", "slow"):
        return {"error": "mode must be ok|errors|slow"}
    MODE["chaos"] = mode
    return {"chaos": mode}


@app.get("/checkout")
def checkout():
    start = time.time()
    time.sleep(random.uniform(0.02, 0.08) + (2.0 if MODE["chaos"] == "slow" else 0))
    if MODE["chaos"] == "errors" and random.random() < 0.35:
        CHECKOUTS.labels(status="error").inc()
        LATENCY.observe(time.time() - start)
        return {"error": "payment upstream refused"}, 500
    CHECKOUTS.labels(status="ok").inc()
    LATENCY.observe(time.time() - start)
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("DEMO_PORT", "8002")))
