import logging
import os

from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)

_handler = "unset"
_client = None


def flush_traces():
    if _client is not None:
        _client.flush()


def warmup():
    if _client is None:
        get_trace_handler()
    if _client is None:
        return
    try:
        _client.auth_check()
    except Exception as e:
        log.debug(f"langfuse warmup skipped: {e}")


def get_trace_handler():
    global _handler, _client
    if _handler != "unset":
        return _handler
    if not os.getenv("LANGFUSE_PUBLIC_KEY") or not os.getenv("LANGFUSE_SECRET_KEY"):
        _handler = None
        return None
    try:
        host = os.getenv("LANGFUSE_HOST") or os.getenv("LANGFUSE_BASE_URL") \
            or "https://cloud.langfuse.com"
        from langfuse import Langfuse
        from langfuse.langchain import CallbackHandler

        _client = Langfuse(public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
                           secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
                           host=host)
        _handler = CallbackHandler(public_key=os.getenv("LANGFUSE_PUBLIC_KEY"))
    except Exception:
        _handler = None
    return _handler
