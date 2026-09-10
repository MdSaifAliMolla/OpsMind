import json
import os

from app.rag.embeddings import DIM, embed_text

COLLECTION = "runbooks"


def chunk(text: str, size=500, overlap=50):
    out = []
    for i in range(0, len(text), size - overlap):
        c = text[i:i + size].strip()
        if len(c) > 40:
            out.append(c)
    return out


def main():
    runbooks = os.path.join(os.getcwd(), "data/runbooks")
    store_path = os.path.join(os.getcwd(), "app/rag/store.json")

    points = []
    for fname in sorted(os.listdir(runbooks)):
        if not fname.endswith(".md"):
            continue
        with open(os.path.join(runbooks, fname)) as f:
            text = f.read()
        for c in chunk(text):
            points.append({
                "id": len(points),
                "source": fname,
                "text": c,
                "vector": embed_text(c),
            })

    with open(store_path, "w") as f:
        json.dump(points, f, indent=2)
    print(f"wrote {len(points)} chunks to app/rag/store.json")

    try:
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, PointStruct, VectorParams

        qdrant = QdrantClient(url=os.getenv("QDRANT_URL", "http://localhost:6333"),
                              timeout=5, check_compatibility=False)
        if not qdrant.collection_exists(COLLECTION):
            qdrant.create_collection(COLLECTION, vectors_config=VectorParams(size=DIM, distance=Distance.COSINE))
        qdrant.upsert(COLLECTION, points=[
            PointStruct(id=p["id"], vector=p["vector"], payload={"source": p["source"], "text": p["text"]})
            for p in points
        ])
        print(f"upserted {len(points)} points to qdrant")
    except Exception as e:
        print(f"qdrant unavailable, local store is enough for dev: {e}")


if __name__ == "__main__":
    main()
