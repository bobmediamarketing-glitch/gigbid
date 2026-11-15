"""Configurable retrieval pipeline. Every variant V0..V8 is one `PipelineConfig`
(rag/variants/*.py), so the comparison and the ablation are the same code with switches flipped.

    query transform  ->  units (chunking)  ->  retrieval        ->  rerank      ->  fuse    ->  boost
    whole | decompose    fixed | item |        dense | bm25 |       cross-enc.      RRF over    outcome-aware
    (+ expand)           multivector           hybrid (RRF)         (optional)      queries     (optional)

Units are scored and then aggregated to their evidence item (max), so a repo whose README
looks irrelevant can still be found through its code chunk (multivector, V5).
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field, replace
from typing import Literal

from rag.index.bm25 import BM25Index
from rag.index.dense import Embedder
from rag.index.qdrant_index import make_dense_index
from rag.ingest.loaders import Corpus, EvidenceDoc
from rag.query import decompose, expand
from rag.retriever import Filters, Hit

RRF_K = 60


@dataclass(frozen=True)
class PipelineConfig:
    name: str
    query: Literal["whole", "decompose", "both"] = "whole"   # both: whole post + each requirement
    expand: bool = False                       # add canonical skill names / implied phrasing to each query
    units: Literal["fixed", "item", "multivector"] = "item"
    retrieval: Literal["dense", "bm25", "hybrid"] = "dense"
    rerank: bool = False
    outcome_boost: bool = False
    corrective: bool = False                   # V8: grade, re-query, refuse (rag/corrective.py)
    candidates: int = 30
    rerank_top: int = 15
    chunk_words: int = 60
    boost: dict = field(default_factory=lambda: {"won": 1.3, "replied": 1.15, "ignored": 0.75})
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    reranker_model: str = "Xenova/ms-marco-MiniLM-L-6-v2"
    min_grade: float = 0.0                     # V8: cross-encoder logit a requirement's best hit must reach
    whole_weight: float = 2.0                  # query="both": weight of the whole-post ranking in the fusion

    def without(self, **kw) -> "PipelineConfig":
        return replace(self, **kw)


def _header(d: EvidenceDoc) -> str:
    meta = [d.type.replace("_", " ")]
    if d.industry:
        meta.append(f"{d.industry} client")
    if d.outcome:
        meta.append(f"outcome {d.outcome}")
    return f"{d.title} ({', '.join(meta)}). Skills: {', '.join(d.skills)}."


def build_units(docs: list[EvidenceDoc], mode: str, chunk_words: int) -> list[tuple[str, str]]:
    """(doc_id, text) pairs to index."""
    out: list[tuple[str, str]] = []
    for d in docs:
        if mode == "fixed":   # naive: fixed word windows over raw text, no title or metadata
            w = d.text.split()
            for i in range(0, max(1, len(w)), chunk_words):
                out.append((d.id, " ".join(w[i:i + chunk_words])))
        elif mode == "item":  # one unit per item: header with metadata + body
            out.append((d.id, f"{_header(d)}\n{' '.join(d.text.split())[:1500]}"))
        else:                 # multivector: summary, README and code chunks indexed separately
            out.append((d.id, _header(d)))
            if d.parts:
                for name, body in d.parts.items():
                    w = body.split()
                    for i in range(0, max(1, len(w)), 120):
                        out.append((d.id, f"{d.title} {name}: {' '.join(w[i:i + 120])}"))
            else:
                w = d.text.split()
                for i in range(0, max(1, len(w)), 120):
                    out.append((d.id, f"{d.title}: {' '.join(w[i:i + 120])}"))
    return out


def rrf(rankings: list[list[tuple[str, float]]], weights: list[float] | None = None) -> list[tuple[str, float]]:
    agg: dict[str, float] = {}
    for j, r in enumerate(rankings):
        w = weights[j] if weights else 1.0
        for rank, (i, _) in enumerate(r):
            agg[i] = agg.get(i, 0.0) + w / (RRF_K + rank + 1)
    return sorted(agg.items(), key=lambda x: -x[1])


def _to_docs(unit_hits: list[tuple[int, float]], unit_doc: list[str]) -> list[tuple[str, float]]:
    best: dict[str, float] = {}
    for u, s in unit_hits:
        d = unit_doc[u]
        if d not in best or s > best[d]:
            best[d] = s
    return sorted(best.items(), key=lambda x: -x[1])


class Pipeline:
    def __init__(self, corpus: Corpus, cfg: PipelineConfig) -> None:
        self.corpus, self.cfg, self.name = corpus, cfg, cfg.name
        docs = corpus.all()
        units = build_units(docs, cfg.units, cfg.chunk_words)
        self.unit_doc = [d for d, _ in units]
        uids = [str(i) for i in range(len(units))]
        texts = [t for _, t in units]
        self.bm25 = BM25Index(uids, texts) if cfg.retrieval in ("bm25", "hybrid") else None
        self.dense = make_dense_index(uids, texts, Embedder.get(cfg.embedding_model)) \
            if cfg.retrieval in ("dense", "hybrid") else None
        self.item_text = {d.id: f"{_header(d)}\n{' '.join(d.text.split())[:1200]}" for d in docs}
        self.last_timing: dict[str, float] = {}

    # -- stages --
    def queries(self, query: str) -> list[str]:
        if self.cfg.query == "whole":
            qs = [query]
        else:
            parts = decompose(query)
            qs = parts if self.cfg.query == "decompose" else [query] + [p for p in parts if p != query]
        return [expand(q) for q in qs] if self.cfg.expand else qs

    def retrieve(self, q: str, allowed_units: set[str] | None) -> list[tuple[str, float]]:
        n = self.cfg.candidates * 3  # units -> fewer distinct items after aggregation
        lists = []
        if self.dense:
            lists.append(_to_docs([(int(u), s) for u, s in self.dense.search(q, n, allowed_units)], self.unit_doc))
        if self.bm25:
            lists.append(_to_docs([(int(u), s) for u, s in self.bm25.search(q, n, allowed_units)], self.unit_doc))
        ranked = lists[0] if len(lists) == 1 else rrf(lists)
        return ranked[:self.cfg.candidates]

    def rerank(self, q: str, ranked: list[tuple[str, float]]) -> list[tuple[str, float]]:
        from rag.index.rerank import Reranker
        top = ranked[:self.cfg.rerank_top]
        scores = Reranker.get(self.cfg.reranker_model).score(q, [self.item_text[i] for i, _ in top])
        return sorted(zip([i for i, _ in top], scores), key=lambda x: -x[1]) + ranked[self.cfg.rerank_top:]

    def per_query(self, query: str, filters: Filters | None) -> list[tuple[str, list[tuple[str, float]]]]:
        allowed_docs = {d.id for d in self.corpus.all() if filters.allow(d)} if filters else None
        allowed_units = {str(i) for i, d in enumerate(self.unit_doc) if d in allowed_docs} \
            if allowed_docs is not None else None
        out = []
        for q in self.queries(query):
            r = self.retrieve(q, allowed_units)
            if self.cfg.rerank and r:
                r = self.rerank(q, r)
            out.append((q, r))
        return out

    def fuse(self, per_q: list[tuple[str, list[tuple[str, float]]]], k: int) -> list[Hit]:
        rankings = [r for _, r in per_q if r]
        if not rankings:
            return []
        weights = None
        if self.cfg.query == "both" and per_q and per_q[0][1]:
            weights = [self.cfg.whole_weight] + [1.0] * (len(rankings) - 1)
        fused = rrf(rankings, weights)
        if self.cfg.outcome_boost:
            fused = sorted(((i, s * self.cfg.boost.get(self.corpus.get(i).outcome or "", 1.0)) for i, s in fused),
                           key=lambda x: -x[1])
        hits = []
        for i, s in fused[:k]:
            matched = [q for q, r in per_q if i in {x for x, _ in r[:3]}]
            hits.append(Hit(self.corpus.get(i), s, matched))
        return hits

    def search(self, query: str, k: int = 5, filters: Filters | None = None) -> list[Hit]:
        t0 = time.perf_counter()
        if self.cfg.corrective:
            from rag.corrective import corrective_search
            hits = corrective_search(self, query, k, filters)
        else:
            hits = self.fuse(self.per_query(query, filters), k)
        self.last_timing = {"ms": (time.perf_counter() - t0) * 1000}
        return hits


def clean_post(text: str) -> str:
    """Strip markdown noise so the whole-post query is plain text."""
    return re.sub(r"\s+", " ", text).strip()
