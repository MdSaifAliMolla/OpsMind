import logging

from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)

_warned = False


def llm_enabled() -> bool:
    from app.agents.llm_provider import provider_enabled

    return provider_enabled()


def reset_llm_cache():
    from app.agents.llm_provider import reset_provider_cache

    reset_provider_cache()


def note_llm_error(where: str, e: Exception):
    global _warned
    if not _warned:
        log.warning(f"llm {where} failed (further failures go to debug): {e}")
        _warned = True
    else:
        log.debug(f"llm {where} failed: {e}")


def content_to_text(content) -> str:
    import json as _json

    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for b in content:
            if isinstance(b, str):
                parts.append(b)
            elif isinstance(b, dict):
                parts.append(b.get("text", _json.dumps(b)))
            else:
                parts.append(str(getattr(b, "text", b)))
        return "\n".join(parts)
    return _json.dumps(content)


def get_llm():
    from app.agents.llm_provider import get_chat_model

    return get_chat_model()


def _estimate_tokens(text: str) -> int:
    return max(1, len(text or "") // 4)


def invoke_tracked(messages, *, where: str = "agent"):
    import time

    from app.agents.llm_provider import get_model_name
    from app.observability import metrics as _m
    from app.observability.tracing import chat_span, maybe_attach_content

    llm = get_llm()
    model = get_model_name()
    prompt_text = " ".join(
        (getattr(m, "content", "") if isinstance(getattr(m, "content", ""), str) else str(getattr(m, "content", "")))
        for m in (messages if isinstance(messages, list) else [messages])
    )
    start = time.time()
    with chat_span(where, model) as span:
        try:
            res = llm.invoke(messages)
        except Exception:
            _m.record_llm_error()
            raise
        latency = time.time() - start
        try:
            completion = content_to_text(res.content)
        except Exception:
            completion = ""
        maybe_attach_content(span, prompt_text, completion)
        in_tok = out_tok = None
        try:
            usage = getattr(res, "usage_metadata", None) or {}
            if isinstance(usage, dict):
                in_tok = usage.get("input_tokens") or usage.get("prompt_token_count")
                out_tok = usage.get("output_tokens") or usage.get("candidates_token_count")
            else:
                in_tok = getattr(usage, "input_tokens", None)
                out_tok = getattr(usage, "output_tokens", None)
        except Exception:
            pass
        if not in_tok:
            in_tok = _estimate_tokens(prompt_text)
        if not out_tok:
            out_tok = _estimate_tokens(completion)
        try:
            span.set_attribute("gen_ai.usage.input_tokens", int(in_tok))
            span.set_attribute("gen_ai.usage.output_tokens", int(out_tok))
        except Exception:
            pass
    _m.record_llm_call(model, in_tok, out_tok, latency)
    return res
