import logging
import math
import os
import re
import threading

log = logging.getLogger(__name__)

DIM = 384
_ST_MODEL_NAME = os.getenv("OPSMIND_EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
_st_model = None
_st_lock = threading.Lock()
_st_failed = False


def _hash_token(tok: str) -> int:
    h = 2166136261
    for ch in tok:
        h ^= ord(ch)
        h = (h * 16777619) & 0xFFFFFFFF
    if h >= 0x80000000:
        h -= 0x100000000
    return abs(h) % DIM


def local_embed(text: str):
    vec = [0.0] * DIM
    for tok in re.findall(r"[a-z0-9]+", text.lower()):
        vec[_hash_token(tok)] += 1.0
        if len(tok) > 4:
            vec[_hash_token(tok[:4])] += 0.3
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _st_embed(text: str):
    global _st_model, _st_failed
    if _st_failed:
        return None
    if _st_model is None:
        with _st_lock:
            if _st_model is None and not _st_failed:
                try:
                    from sentence_transformers import SentenceTransformer

                    _st_model = SentenceTransformer(_ST_MODEL_NAME)
                except Exception as e:
                    log.debug(f"sentence-transformers unavailable, hash fallback: {e}")
                    _st_failed = True
                    return None
    try:
        vec = _st_model.encode(text, normalize_embeddings=True)
        return [float(v) for v in vec]
    except Exception as e:
        log.debug(f"st embed failed, hash fallback: {e}")
        return None


def embed_texts(texts: list) -> list:
    global _st_failed
    if not _st_failed:
        try:
            from sentence_transformers import SentenceTransformer  # noqa: F401
            if _st_model is None:
                _st_embed(texts[0] if texts else "")
            if _st_model is not None:
                mat = _st_model.encode(texts, normalize_embeddings=True)
                return [[float(v) for v in row] for row in mat]
        except Exception as e:
            log.debug(f"st batch failed, hash fallback: {e}")
    return [local_embed(t) for t in texts]


def embed_text(text: str):
    st = _st_embed(text)
    if st is not None:
        return st
    return local_embed(text)


def embedding_backend() -> str:
    if _st_model is not None:
        return "sentence-transformers"
    if _st_failed:
        return "hash"
    try:
        import sentence_transformers  # noqa: F401

        return "sentence-transformers (lazy)"
    except ImportError:
        return "hash"


def warmup():
    _st_embed("opsmind embedding warmup")


def cosine(a, b) -> float:
    return sum(x * y for x, y in zip(a, b))
