import json
import logging
import os
import socket
import threading
from urllib.parse import urlparse

from app.rag.embeddings import cosine, embed_text

log = logging.getLogger(__name__)

COLLECTION = "runbooks"

_lock = threading.Lock()
_qdrant_down = False  # set after the first failure so offline runs stay fast


def _store_path() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "store.json")


def _qdrant_reachable() -> bool:
    try:
        parts = urlparse(os.getenv("QDRANT_URL", "http://localhost:6333"))
        if not parts.hostname:
            return False
        socket.create_connection((parts.hostname, parts.port or 6333), timeout=0.5).close()
        return True
    except OSError:
        return False


def _local_search(query_vec, top_k=3):
    store_path = _store_path()
    if not os.path.exists(store_path):
        return []
    try:
        with open(store_path) as f:
            points = json.load(f)
    except Exception:
        return []
    hits = []
    for p in points:
        try:
            if len(p.get("vector", [])) != len(query_vec):
                continue
            hits.append({"text": str(p.get("text", ""))[:2000],
                         "source": str(p.get("source", "unknown"))[:128],
                         "score": cosine(query_vec, p["vector"])})
        except Exception:
            continue
    hits.sort(key=lambda h: h["score"], reverse=True)
    return hits[:max(1, min(10, top_k))]


def retrieve_runbooks(query: str, top_k=3):
    global _qdrant_down
    vector = embed_text((query or "")[:2000])
    top_k = max(1, min(10, int(top_k or 3)))
    with _lock:
        down = _qdrant_down
    if not down and _qdrant_reachable():
        try:
            from qdrant_client import QdrantClient

            qdrant = QdrantClient(url=os.getenv("QDRANT_URL", "http://localhost:6333"),
                                  timeout=2, check_compatibility=False)
            res = qdrant.query_points(COLLECTION, query=vector, limit=top_k)
            pts = res.points or []
            if pts:
                return [
                    {"text": str(p.payload.get("text", ""))[:2000],
                     "source": str(p.payload.get("source", "unknown"))[:128],
                     "score": p.score or 0}
                    for p in pts
                ]
        except Exception as e:
            log.debug(f"qdrant query failed, using local store: {e}")
            with _lock:
                _qdrant_down = True
    return _local_search(vector, top_k)
