import os

from app.rag.embeddings import embed_text

COLLECTION = "runbooks"

def _rerank(hits: list, top_k: int = 3) -> list:
    """Resolved-healthy postmortems get a 1.15x boost."""
    top_k = max(1, min(10, int(top_k or 3)))
    for h in hits:
        if str(h.get("source", "")).startswith("postmortem:") and \
                h.get("outcome") == "healthy":
            h["score"] = float(h.get("score", 0)) * 1.15
    hits.sort(key=lambda h: h.get("score", 0), reverse=True)
    return hits[:top_k]


def _qdrant_url() -> str:
    url = os.getenv("QDRANT_URL", "").strip()
    if not url:
        raise RuntimeError("QDRANT_URL is required (no empty fallback)")
    return url


def retrieve_runbooks(query: str, top_k=3, fault_family: str = None):
    vector = embed_text((query or "")[:2000])
    top_k = max(1, min(10, int(top_k or 3)))

    from qdrant_client import QdrantClient
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    qdrant = QdrantClient(url=_qdrant_url(), timeout=5, check_compatibility=False)

    query_filter = None
    if fault_family:
        query_filter = Filter(
            should=[FieldCondition(key="fault_family", match=MatchValue(value=fault_family))]
        )

    res = qdrant.query_points(COLLECTION, query=vector, limit=top_k * 3, query_filter=query_filter)
    pts = res.points or []
    if not pts:
        raise RuntimeError("qdrant: no runbooks found")
    return _rerank([
        {"text": str(p.payload.get("text", ""))[:2000],
         "source": str(p.payload.get("source", "unknown"))[:128],
         "score": p.score or 0,
         "outcome": str(p.payload.get("outcome", ""))[:32]}
        for p in pts
    ], top_k)
