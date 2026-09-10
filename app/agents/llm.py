import logging
import os

from dotenv import load_dotenv

load_dotenv()  # so CLIs (eval, ablation, pytest) see .env without a server running

log = logging.getLogger(__name__)

_llm = "unset"
_warned = False


def llm_enabled() -> bool:
    return bool(os.getenv("GOOGLE_API_KEY")) and os.getenv("OPSMIND_DISABLE_LLM") != "1"


def reset_llm_cache():
    global _llm
    _llm = "unset"


def note_llm_error(where: str, e: Exception):
    """First failure warns (usually a bad model name/key), the rest stay debug."""
    global _warned
    if not _warned:
        log.warning(f"llm {where} failed, using rules (further failures go to debug): {e}")
        _warned = True
    else:
        log.debug(f"llm {where} failed, using rules: {e}")


def get_llm():
    global _llm
    if _llm != "unset":
        return _llm
    if not llm_enabled():
        _llm = None
        return None
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
        _llm = ChatGoogleGenerativeAI(
            model=os.getenv("GEMINI_MODEL", "gemini-3.6-flash"),
            google_api_key=os.getenv("GOOGLE_API_KEY"),
        )
    except Exception as e:
        log.warning(f"gemini unavailable, using rules: {e}")
        _llm = None
    return _llm
