"""Dense embeddings (fastembed ONNX, runs on CPU, no API key) with an on-disk cache.

The model is configurable (`rag.embedding_model`); the default is BAAI/bge-small-en-v1.5
(384 dims, ~130 MB). Embeddings are cached by text hash in data/processed/, so rerunning
the variant comparison only embeds new or changed text.
"""
from __future__ import annotations

import hashlib
import os
import threading
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
MODELS = Path(os.getenv("GIGBID_MODEL_CACHE", ROOT / "data" / "models"))
CACHE = ROOT / "data" / "processed"


def _h(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


class Embedder:
    _instances: dict[str, "Embedder"] = {}
    _lock = threading.Lock()

    def __init__(self, model: str) -> None:
        from fastembed import TextEmbedding

        self.model_name = model
        self.model = TextEmbedding(model, cache_dir=str(MODELS))
        self.file = CACHE / f"emb_{model.replace('/', '_')}.npz"
        self.cache: dict[str, np.ndarray] = {}
        if self.file.exists():
            z = np.load(self.file)
            self.cache = dict(zip(z["keys"].tolist(), z["vecs"]))
        self._dirty = False

    @classmethod
    def get(cls, model: str = "BAAI/bge-small-en-v1.5") -> "Embedder":
        with cls._lock:
            if model not in cls._instances:
                cls._instances[model] = cls(model)
            return cls._instances[model]

    def embed(self, texts: list[str], query: bool = False) -> np.ndarray:
        prefix = "query: " if query and "e5" in self.model_name else ""
        keys = [("q:" if query else "d:") + _h(prefix + t) for t in texts]
        todo = [(k, prefix + t) for k, t in zip(keys, texts) if k not in self.cache]
        if todo:
            fn = self.model.query_embed if query else self.model.embed
            for (k, _), v in zip(todo, fn([t for _, t in todo])):
                self.cache[k] = np.asarray(v, dtype=np.float32)
            self._dirty = True
        m = np.stack([self.cache[k] for k in keys]) if keys else np.zeros((0, 384), np.float32)
        return m / np.maximum(np.linalg.norm(m, axis=1, keepdims=True), 1e-9)

    def save(self) -> None:
        if not self._dirty:
            return
        CACHE.mkdir(parents=True, exist_ok=True)
        keys = list(self.cache)
        tmp = self.file.with_name(self.file.stem + ".tmp.npz")
        np.savez(tmp, keys=np.array(keys), vecs=np.stack([self.cache[k] for k in keys]))
        tmp.replace(self.file)
        self._dirty = False


class DenseIndex:
    def __init__(self, ids: list[str], texts: list[str], embedder: Embedder) -> None:
        self.ids, self.embedder = ids, embedder
        self.matrix = embedder.embed(texts) if texts else np.zeros((0, 384), np.float32)
        embedder.save()

    def search(self, query: str, k: int = 10, allowed: set[str] | None = None) -> list[tuple[str, float]]:
        if not self.ids:
            return []
        q = self.embedder.embed([query], query=True)[0]
        sims = self.matrix @ q
        order = np.argsort(-sims)
        out = []
        for i in order:
            if allowed is None or self.ids[i] in allowed:
                out.append((self.ids[i], float(sims[i])))
                if len(out) == k:
                    break
        return out
