import pytest


@pytest.fixture(scope="module")
def spans():
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    import app.observability.tracing as t

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    t._provider_override = provider.get_tracer("opsmind-test")
    t._configured = True  # never let ensure_exporter() touch the global provider
    yield exporter
    exporter.clear()
    t._provider_override = None


def _attrs(spans, name):
    for s in spans.get_finished_spans():
        if s.name == name:
            return dict(s.attributes or {})
    return None


def test_chat_span_attrs(spans):
    from app.observability.tracing import chat_span
    spans.clear()
    with chat_span("rca", "llama3.1") as span:
        span.set_attribute("gen_ai.usage.input_tokens", 10)
        span.set_attribute("gen_ai.usage.output_tokens", 5)
    attrs = _attrs(spans, "chat llama3.1")
    assert attrs is not None
    assert attrs["gen_ai.operation.name"] == "chat"
    assert attrs["gen_ai.request.model"] == "llama3.1"
    assert attrs["opsmind.node"] == "rca"
    assert attrs["gen_ai.usage.input_tokens"] == 10


def test_content_redacted_by_default(spans, monkeypatch):
    monkeypatch.delenv("OPSMIND_TRACE_CONTENT", raising=False)
    from app.observability.tracing import chat_span, maybe_attach_content
    spans.clear()
    with chat_span("rca", "m") as span:
        maybe_attach_content(span, "SECRET prompt", "SECRET completion")
    attrs = _attrs(spans, "chat m")
    assert "gen_ai.prompt.0.content" not in attrs
    assert "gen_ai.completion.0.content" not in attrs


def test_content_attached_when_enabled(spans, monkeypatch):
    monkeypatch.setenv("OPSMIND_TRACE_CONTENT", "true")
    from app.observability.tracing import chat_span, maybe_attach_content
    spans.clear()
    with chat_span("rca", "m") as span:
        maybe_attach_content(span, "hello prompt", "hello completion")
    attrs = _attrs(spans, "chat m")
    assert attrs["gen_ai.prompt.0.content"] == "hello prompt"


def test_traced_node_marks_and_propagates(spans):
    from app.observability.tracing import traced
    spans.clear()

    def _node(state):
        return {"ok": True}

    out = traced("triage", _node)({"incident": {"incident_id": "i1"}})
    assert out == {"ok": True}
    attrs = _attrs(spans, "opsmind.triage")
    assert attrs is not None and attrs["incident.id"] == "i1"


def test_traced_node_records_error(spans):
    from opentelemetry.trace import StatusCode

    from app.observability.tracing import traced
    spans.clear()

    def _boom(state):
        raise ValueError("kaboom")

    with pytest.raises(ValueError):
        traced("rca", _boom)({"incident": {}})
    got = [s for s in spans.get_finished_spans() if s.name == "opsmind.rca"]
    assert got and got[0].status.status_code == StatusCode.ERROR


def test_invoke_tracked_emits_chat_span(spans, monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    monkeypatch.delenv("OPSMIND_TRACE_CONTENT", raising=False)
    from app.agents import llm_provider as p
    p.reset_provider_cache()
    spans.clear()

    class _Resp:
        content = "hello"
        usage_metadata = {"input_tokens": 7, "output_tokens": 3}

    class _FakeChat:
        def invoke(self, messages):
            return _Resp()

    monkeypatch.setattr(p, "get_chat_model", lambda: _FakeChat())
    from app.agents import llm as llm_mod
    llm_mod.invoke_tracked("hi", where="judge")
    attrs = _attrs(spans, "chat gemini-3.5-flash-lite")
    assert attrs is not None
    assert attrs["opsmind.node"] == "judge"
    assert attrs["gen_ai.usage.input_tokens"] == 7
    assert attrs["gen_ai.usage.output_tokens"] == 3


def test_incident_span_outcome_attrs(spans):
    from app.observability.tracing import finish_incident_span, incident_span
    spans.clear()
    with incident_span({"incident_id": "i9", "service": "s", "alert_type": "a"}) as span:
        finish_incident_span(span, {"severity": "P1", "approval_status": "approved",
                                    "root_cause": "x", "confidence": 0.9})
    attrs = _attrs(spans, "opsmind.incident")
    assert attrs["incident.id"] == "i9"
    assert attrs["incident.severity"] == "P1"
    assert attrs["incident.approval_status"] == "approved"
