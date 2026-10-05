"""Toy checkout service that emits real Prometheus metrics and can break on demand.

GET  /health, /metrics
POST /chaos/{mode}  (mode: ok | errors | slow)  -> flips the failure switch
GET  /checkout      -> simulated checkout, fails fast when chaos=errors

Every checkout emits a structured JSON log line (picked up by Promtail/Loki
with a service label) and an OpenTelemetry span (exported OTLP to Jaeger when
OTEL_EXPORTER_OTLP_ENDPOINT is set).
"""
import json
import logging
import os
import random
import sys
import time

from fastapi import FastAPI, Response
from fastapi.responses import JSONResponse
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

logger = logging.getLogger("demo-checkout")
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(logging.Formatter("%(message)s"))
logger.addHandler(handler)
logger.setLevel(logging.INFO)
logger.propagate = False

_tracer = None
try:
    if os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        trace.set_tracer_provider(TracerProvider())
        trace.get_tracer_provider().add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(
                endpoint=os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"), insecure=True)))
        FastAPIInstrumentor.instrument_app(app)
        _tracer = trace.get_tracer("demo-checkout")
except Exception as e:
    logger.info(json.dumps({"service": "demo-checkout", "msg": f"tracing disabled: {e}"}))


def _log(status: str, latency_s: float):
    logger.info(json.dumps({
        "service": "demo-checkout",
        "msg": f"checkout {status} in {latency_s:.3f}s (chaos={MODE['chaos']})",
        "status": status,
        "latency_s": round(latency_s, 3),
        "chaos": MODE["chaos"],
    }))


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
    if _tracer is not None:
        with _tracer.start_as_current_span("checkout", attributes={"chaos": MODE["chaos"]}):
            return _do_checkout(start)
    return _do_checkout(start)


def _do_checkout(start: float):
    time.sleep(random.uniform(0.02, 0.08) + (2.0 if MODE["chaos"] == "slow" else 0))
    latency = time.time() - start
    if MODE["chaos"] == "errors" and random.random() < 0.35:
        CHECKOUTS.labels(status="error").inc()
        LATENCY.observe(latency)
        _log("error", latency)
        return JSONResponse({"error": "payment upstream refused"}, status_code=500)
    CHECKOUTS.labels(status="ok").inc()
    LATENCY.observe(latency)
    _log("ok", latency)
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("DEMO_PORT", "8002")))
