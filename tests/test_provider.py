import pytest


def _clean_env(monkeypatch):
    for k in ("OPSMIND_LLM_PROVIDER", "GOOGLE_API_KEY", "GEMINI_MODEL",
              "OPSMIND_LLM_BASE_URL", "OPSMIND_LLM_MODEL", "OPSMIND_LLM_API_KEY"):
        monkeypatch.delenv(k, raising=False)


def test_default_kind_is_gemini(monkeypatch):
    _clean_env(monkeypatch)
    from app.agents import llm_provider as p
    p.reset_provider_cache()
    assert p.get_provider_kind() == "gemini"
    assert p.get_model_name() == "gemini-3.5-flash-lite"


def test_gemini_needs_key(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("OPSMIND_LLM_PROVIDER", "gemini")
    from app.agents import llm_provider as p
    p.reset_provider_cache()
    assert p.provider_enabled() is False
    with pytest.raises(RuntimeError, match="GOOGLE_API_KEY"):
        p.get_chat_model()
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    assert p.provider_enabled() is True


def test_openai_compat_needs_base_url_and_model(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("OPSMIND_LLM_PROVIDER", "openai_compat")
    from app.agents import llm_provider as p
    p.reset_provider_cache()
    assert p.provider_enabled() is False
    with pytest.raises(RuntimeError, match="BASE_URL"):
        p.get_chat_model()
    monkeypatch.setenv("OPSMIND_LLM_BASE_URL", "http://localhost:11434/v1")
    with pytest.raises(RuntimeError, match="BASE_URL|MODEL"):
        p.get_chat_model()
    monkeypatch.setenv("OPSMIND_LLM_MODEL", "llama3.1")
    assert p.provider_enabled() is True
    assert p.get_model_name() == "llama3.1"


def test_unknown_provider_rejected(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("OPSMIND_LLM_PROVIDER", "bogus")
    from app.agents import llm_provider as p
    p.reset_provider_cache()
    assert p.provider_enabled() is False
    with pytest.raises(ValueError, match="unknown"):
        p.get_chat_model()


def test_local_pricing_is_zero():
    from app.observability.metrics import _price
    assert _price("llama3.1") == (0.0, 0.0)
    assert _price("qwen2.5:7b") == (0.0, 0.0)
    assert _price("ollama/llama3.1") == (0.0, 0.0)
    assert _price("gemini-3.5-flash-lite") == (0.07, 0.28)


def test_invoke_tracked_uses_provider_model(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("OPSMIND_LLM_PROVIDER", "openai_compat")
    monkeypatch.setenv("OPSMIND_LLM_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("OPSMIND_LLM_MODEL", "llama3.1")
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
    assert m.llm_tokens.get(("llama3.1", "input"), 0) >= before.get(("llama3.1", "input"), 0) + 10
