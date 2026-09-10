import os

from dotenv import load_dotenv

load_dotenv()  # keys must resolve regardless of import order

_handler = "unset"
_client = None


def flush_traces():
    if _client is not None:
        _client.flush()


def get_trace_handler():
    global _handler, _client
    if _handler != "unset":
        return _handler
    if not os.getenv("LANGFUSE_PUBLIC_KEY") or not os.getenv("LANGFUSE_SECRET_KEY"):
        _handler = None
        return None
    try:
        # langfuse>=4 needs an initialized client first; the langchain
        # handler then attaches to it by public key.
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
