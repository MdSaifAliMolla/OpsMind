import logging
import os
import threading

log = logging.getLogger(__name__)

DIM = 384
_ST_MODEL_NAME = os.getenv("OPSMIND_EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
_st_model = None
_st_lock = threading.Lock()


def _load_model():
    global _st_model
    if _st_model is None:
        with _st_lock:
            if _st_model is None:
                from sentence_transformers import SentenceTransformer

                _st_model = SentenceTransformer(_ST_MODEL_NAME)
    return _st_model


def embed_texts(texts: list) -> list:
    model = _load_model()
    mat = model.encode(texts, normalize_embeddings=True)
    return [[float(v) for v in row] for row in mat]


def embed_text(text: str):
    model = _load_model()
    vec = model.encode(text or "", normalize_embeddings=True)
    return [float(v) for v in vec]


def embedding_backend() -> str:
    return "sentence-transformers"


def warmup():
    _load_model().encode("opsmind embedding warmup", normalize_embeddings=True)


def cosine(a, b) -> float:
    return sum(x * y for x, y in zip(a, b))
