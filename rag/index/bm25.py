"""BM25 keyword index over evidence documents. Exact tool names ("Celery", "dbt") survive here."""
from __future__ import annotations

import re

from rank_bm25 import BM25Okapi

_TOKEN = re.compile(r"[a-z0-9][a-z0-9.+#/-]*")
_STOP = set("a an and are as at be by for from has have i in is it of on or our that the this to we with you your "
            "will can need looking someone experience".split())


def tokenize(text: str) -> list[str]:
    return [t.strip(".") for t in _TOKEN.findall(text.lower()) if t not in _STOP]


class BM25Index:
    def __init__(self, ids: list[str], texts: list[str]) -> None:
        self.ids = ids
        self._bm25 = BM25Okapi([tokenize(t) or ["_"] for t in texts]) if ids else None

    def search(self, query: str, k: int = 10, allowed: set[str] | None = None) -> list[tuple[str, float]]:
        if not self._bm25:
            return []
        scores = self._bm25.get_scores(tokenize(query))
        ranked = sorted(((self.ids[i], float(s)) for i, s in enumerate(scores)
                         if (allowed is None or self.ids[i] in allowed) and s > 0), key=lambda x: -x[1])
        return ranked[:k]
