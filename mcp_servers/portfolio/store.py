"""Caches one corpus + retriever per portfolio folder and re-indexes when files change."""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable

from rag.ingest.loaders import Corpus
from rag.retriever import Retriever, get_retriever


class PortfolioStore:
    def __init__(self, resolve_dir: Callable[[], Path]) -> None:
        self.resolve_dir = resolve_dir
        self._cache: dict[str, tuple[Corpus, Retriever, int]] = {}
        self._lock = threading.Lock()

    def get(self) -> tuple[Corpus, Retriever]:
        d = self.resolve_dir()
        key = str(d.resolve())
        with self._lock:
            if key not in self._cache:
                if not d.is_dir():
                    raise FileNotFoundError(f"portfolio folder not found: {d}")
                c = Corpus(d)
                self._cache[key] = (c, get_retriever(c), c.version)
            c, r, v = self._cache[key]
            if c.refresh() or c.version != v:  # incremental: rebuild only when files changed
                r = get_retriever(c)
                self._cache[key] = (c, r, c.version)
            return c, r
