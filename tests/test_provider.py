import pytest


def _clean_env(monkeypatch):
    for k in ("GOOGLE_API_KEY", "GEMINI_MODEL"):
        monkeypatch.delenv(k, raising=False)


def test_default_model(monkeypatch):
    _clean_env(monkeypatch)
    from app.agents import llm_provider as p
    p.reset_provider_cache()
    assert p.get_model_name() == "gemini-3.5-flash-lite"


def test_gemini_needs_key(monkeypatch):
    _clean_env(monkeypatch)
    from app.agents import llm_provider as p
    p.reset_provider_cache()
    assert p.provider_enabled() is False
    with pytest.raises(RuntimeError, match="GOOGLE_API_KEY"):
        p.get_chat_model()
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    assert p.provider_enabled() is True


def test_gemini_pricing():
    from app.observability.metrics import _price
    assert _price("gemini-3.5-flash-lite") == (0.07, 0.28)


def test_invoke_tracked_records_usage(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    from app.agents import llm_provider as p
    from app.observability import metrics as m
    p.reset_provider_cache()

    class _FakeResp:
        content = '{"hypotheses": []}'
        usage_metadata = {"input_tokens": 10, "output_tokens": 5}

    class _FakeChat:
        def invoke(self, messages):
            return _FakeResp()

    monkeypatch.setattr(p, "get_chat_model", lambda: _FakeChat())
    # llm.get_llm delegates to provider, so patch provider only
    from app.agents import llm as llm_mod
    before = dict(m.llm_tokens)
    llm_mod.invoke_tracked("hello", where="test")
    assert m.llm_tokens.get(("gemini-3.5-flash-lite", "input"), 0) >= before.get(("gemini-3.5-flash-lite", "input"), 0) + 10
