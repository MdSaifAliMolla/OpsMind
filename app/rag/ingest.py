import os
import re

from app.rag.embeddings import embed_texts, embedding_backend

COLLECTION = "runbooks"


def chunk(text: str, size=800, overlap=100):
    """Split by markdown headers, then by size if still too big."""
    sections = re.split(r'(?m)^##\s', text)
    out = []
    for s in sections:
        s = s.strip()
        if not s:
            continue
        s = "## " + s if not text.startswith(s) else s
        if len(s) > size:
            step = size - overlap
            for i in range(0, len(s), step):
                c = s[i:i + size].strip()
                if len(c) > 40:
                    out.append(c)
        else:
            if len(s) > 40:
                out.append(s)
    return out


def main():
    base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    runbooks = os.path.join(base, "data", "runbooks")

    if not os.path.isdir(runbooks):
        raise SystemExit(f"runbooks dir not found: {runbooks}")

    chunks = []
    for fname in sorted(os.listdir(runbooks)):
        if not fname.endswith(".md"):
            continue
        with open(os.path.join(runbooks, fname), encoding="utf-8") as f:
            text = f.read()
        for c in chunk(text):
            chunks.append((fname, c))

    print(f"embedding backend: {embedding_backend()}")
    vectors = embed_texts([c for _, c in chunks])
    if not vectors:
        print("no chunks to ingest")
        return
    dim = len(vectors[0])
    points = [
        {"id": i, "source": fname, "text": c, "vector": v}
        for i, ((fname, c), v) in enumerate(zip(chunks, vectors))
    ]

    print(f"generated {len(points)} chunks (dim={dim})")
    from qdrant_client import QdrantClient
    from qdrant_client.models import Distance, PointStruct, VectorParams

    url = os.getenv("QDRANT_URL", "").strip()
    if not url:
        raise RuntimeError("QDRANT_URL is required")
    qdrant = QdrantClient(url=url, timeout=5, check_compatibility=False)
    if not qdrant.collection_exists(COLLECTION):
        qdrant.create_collection(COLLECTION, vectors_config=VectorParams(size=dim, distance=Distance.COSINE))
    qdrant.upsert(COLLECTION, points=[
        PointStruct(id=p["id"], vector=p["vector"], payload={"source": p["source"], "text": p["text"]})
        for p in points
    ])
    print(f"upserted {len(points)} points to qdrant")


if __name__ == "__main__":
    main()
