"""Qdrant-backed dense index (the vector-store service in docker compose). Same interface as DenseIndex.

Embeddings are still computed locally with fastembed (cached); Qdrant stores and searches them. One
collection per (embedding model, unit set) fingerprint, so re-running with unchanged data reuses it and a
changed portfolio gets a fresh collection automatically.
"""
from __future__ import annotations

import hashlib
import os

from rag.index.dense import Embedder


def _client():
    from qdrant_client import QdrantClient
    url = os.getenv("QDRANT_URL", ":memory:")
    return QdrantClient(location=":memory:") if url == ":memory:" else QdrantClient(url=url, api_key=os.getenv("QDRANT_API_KEY"))


class QdrantIndex:
    _shared = None

    def __init__(self, ids: list[str], texts: list[str], embedder: Embedder) -> None:
        from qdrant_client import models
        self.ids, self.embedder, self.models = ids, embedder, models
        if QdrantIndex._shared is None:
            QdrantIndex._shared = _client()
        self.client = QdrantIndex._shared
        fp = hashlib.sha1((embedder.model_name + "\x00" + "\x00".join(texts)).encode("utf-8")).hexdigest()[:16]
        self.collection = f"gigbid_{fp}"
        if not ids:
            return
        if not self.client.collection_exists(self.collection):
            vecs = embedder.embed(texts)
            embedder.save()
            self.client.create_collection(self.collection, vectors_config=models.VectorParams(
                size=vecs.shape[1], distance=models.Distance.COSINE))
            self.client.upload_points(self.collection, points=[
                models.PointStruct(id=i, vector=v.tolist(), payload={"uid": uid})
                for i, (uid, v) in enumerate(zip(ids, vecs))], batch_size=256)

    def search(self, query: str, k: int = 10, allowed: set[str] | None = None) -> list[tuple[str, float]]:
        if not self.ids:
            return []
        m = self.models
        q = self.embedder.embed([query], query=True)[0].tolist()
        flt = m.Filter(must=[m.FieldCondition(key="uid", match=m.MatchAny(any=sorted(allowed)))]) if allowed else None
        res = self.client.query_points(self.collection, query=q, limit=k, query_filter=flt).points
        return [(p.payload["uid"], float(p.score)) for p in res]


def make_dense_index(ids: list[str], texts: list[str], embedder: Embedder):
    """Qdrant when QDRANT_URL is set (compose / production), the in-process numpy index otherwise."""
    if os.getenv("QDRANT_URL"):
        return QdrantIndex(ids, texts, embedder)
    from rag.index.dense import DenseIndex
    return DenseIndex(ids, texts, embedder)
