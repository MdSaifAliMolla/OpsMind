"""Postmortem feedback: resolved incidents teach future ones.

Strict: Qdrant required, raises on failure. No local JSON store, no zero
vectors, no skip flags.
"""
import os
import uuid


def ingest_postmortem(incident_id: str, text: str, outcome: str = "healthy",
                      fault_family: str = "", action: str = "") -> int:
    """Chunk + embed + upsert postmortem to Qdrant. Returns chunks written."""
    from app.rag.embeddings import embed_texts
    from app.rag.ingest import chunk

    body = str(text or "").strip()
    if not body:
        raise ValueError("postmortem text is required")
    source = f"postmortem:{str(incident_id or 'unknown')[:64]}"
    chunks = [c for c in chunk(body) if c.strip()]
    if not chunks:
        raise ValueError("postmortem produced no chunks")
    vectors = embed_texts(chunks)
    points = [{"source": source, "text": c, "vector": v,
               "outcome": str(outcome or "")[:32],
               "fault_family": str(fault_family or "")[:64],
               "action": str(action or "")[:64]}
              for c, v in zip(chunks, vectors)]

    url = os.getenv("QDRANT_URL", "").strip()
    if not url:
        raise RuntimeError("QDRANT_URL is required")
    from qdrant_client import QdrantClient
    from qdrant_client.http.models import PointStruct

    qdrant = QdrantClient(url=url, timeout=5, check_compatibility=False)
    ids = [str(uuid.uuid4()) for _ in points]
    qdrant.upsert("runbooks", points=[
        PointStruct(id=i, vector=p["vector"],
                    payload={k: p[k] for k in ("source", "text", "outcome",
                                               "fault_family", "action")})
        for i, p in zip(ids, points)
    ])
    return len(points)
