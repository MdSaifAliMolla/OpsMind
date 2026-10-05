"""LLM provider: Gemini (single provider, keep it simple).

Needs GOOGLE_API_KEY. Missing config is a configuration error, not a signal
to guess — callers raise instead of falling back.
"""
import logging
import os

log = logging.getLogger(__name__)

GEMINI_DEFAULT_MODEL = "gemini-3.5-flash-lite"

_cache: dict = {}


def get_model_name() -> str:
    return os.getenv("GEMINI_MODEL", GEMINI_DEFAULT_MODEL).strip() or GEMINI_DEFAULT_MODEL


def provider_enabled() -> bool:
    return bool(os.getenv("GOOGLE_API_KEY"))


def reset_provider_cache():
    _cache.clear()


def get_chat_model():
    """Return the cached Gemini chat model, or raise."""
    if not os.getenv("GOOGLE_API_KEY"):
        raise RuntimeError("GOOGLE_API_KEY is not set")
    key = ("gemini", get_model_name())
    if key not in _cache:
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI

            _cache[key] = ChatGoogleGenerativeAI(
                model=get_model_name(),
                google_api_key=os.getenv("GOOGLE_API_KEY"),
                temperature=0,
            )
        except Exception as e:
            raise RuntimeError(f"could not initialize gemini client: {e}") from e
    return _cache[key]
