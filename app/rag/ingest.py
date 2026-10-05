import json
import os

from app.rag.embeddings import embed_texts, embedding_backend

COLLECTION = "runbooks"


def chunk(text: str, size=500, overlap=50):
    if size <= overlap:
        raise ValueError("chunk size must exceed overlap")
    out = []
    step = size - overlap
    for i in range(0, len(text or ""), step):
        c = text[i:i + size].strip()
        if len(c) > 40:
            out.append(c)
    return out


def main():
    base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    runbooks = os.path.join(base, "data", "runbooks")
    store_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "store.json")

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

    with open(store_path, "w", encoding="utf-8") as f:
        json.dump(points, f, indent=2)
    print(f"wrote {len(points)} chunks to {store_path} (dim={dim})")

    try:
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, PointStruct, VectorParams

        qdrant = QdrantClient(url=os.getenv("QDRANT_URL", "http://localhost:6333"),
                              timeout=5, check_compatibility=False)
        if not qdrant.collection_exists(COLLECTION):
            qdrant.create_collection(COLLECTION, vectors_config=VectorParams(size=dim, distance=Distance.COSINE))
        qdrant.upsert(COLLECTION, points=[
            PointStruct(id=p["id"], vector=p["vector"], payload={"source": p["source"], "text": p["text"]})
            for p in points
        ])
        print(f"upserted {len(points)} points to qdrant")
    except Exception as e:
        print(f"qdrant unavailable, local store is enough for dev: {e}")


if __name__ == "__main__":
    main()
