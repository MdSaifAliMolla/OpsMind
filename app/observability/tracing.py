import functools
import logging
import os
import threading

log = logging.getLogger(__name__)

_provider_lock = threading.Lock()
_configured = False
_provider_override = None

CONTENT_MAX = 2000


def trace_content_enabled() -> bool:
    return os.getenv("OPSMIND_TRACE_CONTENT", "false").strip().lower() == "true"


def ensure_exporter():
    global _configured
    if _provider_override is not None:
        return
    with _provider_lock:
        if _configured:
            return
        _configured = True
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    if not endpoint:
        return
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except Exception as e:
        log.debug(f"otel disabled (sdk missing): {e}")
        return
    try:
        if "Proxy" not in type(trace.get_tracer_provider()).__name__:
            return
        provider = TracerProvider()
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, insecure=True)))
        trace.set_tracer_provider(provider)
    except Exception as e:
        log.debug(f"otel setup skipped: {e}")


def _tracer():
    if _provider_override is not None:
        return _provider_override
    from opentelemetry import trace

    return trace.get_tracer("opsmind")


def _safe_set(span, key, value):
    try:
        if value is not None:
            span.set_attribute(key, value)
    except Exception:
        pass


def incident_span(incident: dict):
    from contextlib import contextmanager

    inc = incident or {}

    @contextmanager
    def _ctx():
        ensure_exporter()
        span = _tracer().start_span("opsmind.incident")
        _safe_set(span, "incident.id", str(inc.get("incident_id", "unknown"))[:128])
        _safe_set(span, "incident.service", str(inc.get("service", "unknown"))[:128])
        _safe_set(span, "incident.alert_type", str(inc.get("alert_type", "unknown"))[:128])
        try:
            with _use_span(span):
                yield span
        finally:
            try:
                span.end()
            except Exception:
                pass

    return _ctx()


def _use_span(span):
    from contextlib import contextmanager

    @contextmanager
    def _ctx():
        try:
            from opentelemetry import trace

            cm = trace.use_span(span, end_on_exit=False)
        except Exception:
            yield span
            return
        with cm:
            yield span

    return _ctx()


def finish_incident_span(span, result: dict):
    result = result or {}
    _safe_set(span, "incident.severity", str(result.get("severity", "unknown"))[:16])
    _safe_set(span, "incident.approval_status", str(result.get("approval_status", "unknown"))[:32])
    _safe_set(span, "incident.root_cause", str(result.get("root_cause", ""))[:300])
    try:
        _safe_set(span, "incident.confidence", float(result.get("confidence", 0)))
    except (TypeError, ValueError):
        pass


def chat_span(node: str, model: str):
    from contextlib import contextmanager

    @contextmanager
    def _ctx():
        span = _tracer().start_span(f"chat {model}")
        _safe_set(span, "gen_ai.operation.name", "chat")
        _safe_set(span, "gen_ai.request.model", model)
        _safe_set(span, "opsmind.node", node)
        try:
            with _use_span(span):
                yield span
        except Exception as e:
            try:
                from opentelemetry.trace import Status, StatusCode

                span.set_status(Status(StatusCode.ERROR, str(e)[:300]))
            except Exception:
                pass
            raise
        finally:
            try:
                span.end()
            except Exception:
                pass

    return _ctx()


def maybe_attach_content(span, prompt_text: str, completion_text: str):
    if not trace_content_enabled():
        return
    _safe_set(span, "gen_ai.prompt.0.content", (prompt_text or "")[:CONTENT_MAX])
    _safe_set(span, "gen_ai.completion.0.content", (completion_text or "")[:CONTENT_MAX])


def traced(name: str, fn):
    @functools.wraps(fn)
    def _wrapper(state: dict):
        ensure_exporter()
        span = _tracer().start_span(f"opsmind.{name}")
        _safe_set(span, "opsmind.node", name)
        try:
            incident = (state or {}).get("incident") or {}
            _safe_set(span, "incident.id", str(incident.get("incident_id", "unknown"))[:128])
            with _use_span(span):
                return fn(state)
        except Exception as e:
            try:
                from opentelemetry.trace import Status, StatusCode

                span.set_status(Status(StatusCode.ERROR, str(e)[:300]))
            except Exception:
                pass
            raise
        finally:
            try:
                span.end()
            except Exception:
                pass

    return _wrapper
