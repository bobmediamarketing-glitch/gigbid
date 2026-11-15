"""Cross-encoder reranker (V3), fastembed ONNX on CPU. Scores are cached per (query, text)."""
from __future__ import annotations

import hashlib
import threading

from rag.index.dense import MODELS


class Reranker:
    _instances: dict[str, "Reranker"] = {}
    _lock = threading.Lock()

    def __init__(self, model: str) -> None:
        from fastembed.rerank.cross_encoder import TextCrossEncoder

        self.model = TextCrossEncoder(model, cache_dir=str(MODELS))
        self.cache: dict[str, float] = {}

    @classmethod
    def get(cls, model: str = "Xenova/ms-marco-MiniLM-L-6-v2") -> "Reranker":
        with cls._lock:
            if model not in cls._instances:
                cls._instances[model] = cls(model)
            return cls._instances[model]

    def score(self, query: str, texts: list[str]) -> list[float]:
        keys = [hashlib.sha1(f"{query}\x00{t}".encode()).hexdigest() for t in texts]
        todo = [(k, t) for k, t in zip(keys, texts) if k not in self.cache]
        if todo:
            for (k, _), s in zip(todo, self.model.rerank(query, [t for _, t in todo])):
                self.cache[k] = float(s)
        return [self.cache[k] for k in keys]
