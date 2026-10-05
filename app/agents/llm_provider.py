import logging
import os

log = logging.getLogger(__name__)

GEMINI_DEFAULT_MODEL = "gemini-3.5-flash-lite"

_cache: dict = {}


def get_provider_kind() -> str:
    return os.getenv("OPSMIND_LLM_PROVIDER", "gemini").strip().lower() or "gemini"


def get_model_name(kind: str | None = None) -> str:
    kind = (kind or get_provider_kind()).lower()
    if kind == "openai_compat":
        return os.getenv("OPSMIND_LLM_MODEL", "llama3.1").strip() or "llama3.1"
    return os.getenv("GEMINI_MODEL", GEMINI_DEFAULT_MODEL).strip() or GEMINI_DEFAULT_MODEL


def provider_enabled(kind: str | None = None) -> bool:
    kind = (kind or get_provider_kind()).lower()
    if kind == "gemini":
        return bool(os.getenv("GOOGLE_API_KEY"))
    if kind == "openai_compat":
        return bool(os.getenv("OPSMIND_LLM_BASE_URL") and os.getenv("OPSMIND_LLM_MODEL"))
    return False


def reset_provider_cache():
    _cache.clear()


def get_chat_model():
    kind = get_provider_kind()
    if kind == "gemini":
        if not os.getenv("GOOGLE_API_KEY"):
            raise RuntimeError("GOOGLE_API_KEY is not set")
        key = (kind, get_model_name(kind))
        if key not in _cache:
            try:
                from langchain_google_genai import ChatGoogleGenerativeAI

                _cache[key] = ChatGoogleGenerativeAI(
                    model=get_model_name(kind),
                    google_api_key=os.getenv("GOOGLE_API_KEY"),
                    temperature=0,
                )
            except Exception as e:
                raise RuntimeError(f"could not initialize gemini client: {e}") from e
        return _cache[key]
    if kind == "openai_compat":
        base_url = os.getenv("OPSMIND_LLM_BASE_URL", "").strip()
        model = os.getenv("OPSMIND_LLM_MODEL", "").strip()
        if not base_url or not model:
            raise RuntimeError("OPSMIND_LLM_BASE_URL and OPSMIND_LLM_MODEL are required for openai_compat")
        key = (kind, base_url, model)
        if key not in _cache:
            try:
                from langchain_openai import ChatOpenAI
            except ImportError as e:
                raise RuntimeError(
                    "langchain-openai is not installed (pip install langchain-openai) "
                    "— required for OPSMIND_LLM_PROVIDER=openai_compat"
                ) from e
            try:
                _cache[key] = ChatOpenAI(
                    base_url=base_url,
                    api_key=os.getenv("OPSMIND_LLM_API_KEY", "none") or "none",
                    model=model,
                    temperature=0,
                )
            except Exception as e:
                raise RuntimeError(f"could not initialize openai-compat client: {e}") from e
        return _cache[key]
    raise ValueError(
        f"unknown OPSMIND_LLM_PROVIDER={kind!r} (expected gemini|openai_compat)"
    )
