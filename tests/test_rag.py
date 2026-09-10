from app.rag.embeddings import cosine, local_embed
from app.rag.ingest import chunk


def test_chunking_splits_long_text():
    assert len(chunk("a" * 1200)) > 1


def test_similar_texts_score_higher():
    a = local_embed("database connection pool exhausted")
    b = local_embed("connection pool timeout acquiring connection")
    c = local_embed("completely unrelated banana pancake recipe")
    assert cosine(a, b) > cosine(a, c)
