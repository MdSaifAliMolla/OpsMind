import json
import logging
import os
import socket
from urllib.parse import urlparse

from app.rag.embeddings import cosine, embed_text

log = logging.getLogger(__name__)

COLLECTION = "runbooks"

_qdrant_down = False  # set after the first failure so offline runs stay fast


def _qdrant_reachable() -> bool:
    try:
        parts = urlparse(os.getenv("QDRANT_URL", "http://localhost:6333"))
        socket.create_connection((parts.hostname, parts.port or 6333), timeout=0.5).close()
        return True
    except OSError:
        return False


def _local_search(query_vec, top_k=3):
    store_path = os.path.join(os.getcwd(), "app/rag/store.json")
    if not os.path.exists(store_path):
        return []
    with open(store_path) as f:
        points = json.load(f)
    hits = [
        {"text": p["text"], "source": p["source"], "score": cosine(query_vec, p["vector"])}
        for p in points
    ]
    hits.sort(key=lambda h: h["score"], reverse=True)
    return hits[:top_k]


def retrieve_runbooks(query: str, top_k=3):
    global _qdrant_down
    vector = embed_text(query)
    if not _qdrant_down and _qdrant_reachable():
        try:
            from qdrant_client import QdrantClient

            qdrant = QdrantClient(url=os.getenv("QDRANT_URL", "http://localhost:6333"),
                                  timeout=2, check_compatibility=False)
            res = qdrant.query_points(COLLECTION, query=vector, limit=top_k)
            pts = res.points or []
            if pts:
                return [
                    {"text": p.payload.get("text", ""), "source": p.payload.get("source", "unknown"),
                     "score": p.score or 0}
                    for p in pts
                ]
        except Exception as e:
            log.debug(f"qdrant query failed, using local store: {e}")
            _qdrant_down = True
    return _local_search(vector, top_k)
