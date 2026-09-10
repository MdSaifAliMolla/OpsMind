import math
import os
import re

import requests

DIM = 384


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


def embed_text(text: str):
    key = os.getenv("VOYAGE_API_KEY")
    if key:
        try:
            r = requests.post(
                "https://api.voyageai.com/v1/embeddings",
                headers={"Authorization": f"Bearer {key}"},
                json={"model": "voyage-3", "input": text},
                timeout=15,
            )
            if r.ok:
                v = r.json()["data"][0]["embedding"]
                if v:
                    return v
        except Exception:
            pass
    return local_embed(text)


def cosine(a, b) -> float:
    return sum(x * y for x, y in zip(a, b))
