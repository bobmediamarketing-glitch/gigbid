"""Retriever factory: the variant is chosen by config (`rag.variant` in agent/config.yaml), never in code.

Variants live in rag/variants/ and register themselves in VARIANTS. Until the
measured choice is made (R6), the default is the keyword baseline below.
"""
from __future__ import annotations

import os

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol

import yaml

from rag.index.bm25 import BM25Index
from rag.ingest.loaders import Corpus, EvidenceDoc

CONFIG = Path(__file__).resolve().parents[1] / "agent" / "config.yaml"


@dataclass
class Filters:
    types: list[str] | None = None
    outcomes: list[str] | None = None
    skills: list[str] | None = None
    industry: str | None = None
    since: str | None = None

    def allow(self, d: EvidenceDoc) -> bool:
        if self.types and d.type not in self.types:
            return False
        if self.outcomes and d.outcome not in self.outcomes:
            return False
        if self.skills and not {s.lower() for s in self.skills} & {s.lower() for s in d.skills}:
            return False
        if self.industry and (d.industry or "").lower() != self.industry.lower():
            return False
        if self.since and (d.date or "") < self.since:
            return False
        return True


@dataclass
class Hit:
    doc: EvidenceDoc
    score: float
    matched: list[str] = field(default_factory=list)  # requirement(s) this hit was retrieved for


class Retriever(Protocol):
    name: str

    def search(self, query: str, k: int = 5, filters: Filters | None = None) -> list[Hit]: ...


class KeywordRetriever:
    """Interim default: BM25 over whole documents."""
    name = "keyword"

    def __init__(self, corpus: Corpus) -> None:
        self.corpus = corpus
        docs = corpus.all()
        self.index = BM25Index([d.id for d in docs], [f"{d.title}\n{' '.join(d.skills)}\n{d.text}" for d in docs])

    def search(self, query: str, k: int = 5, filters: Filters | None = None) -> list[Hit]:
        allowed = {d.id for d in self.corpus.all() if filters.allow(d)} if filters else None
        return [Hit(self.corpus.get(i), s, [query]) for i, s in self.index.search(query, k, allowed)]


VARIANTS: dict[str, Callable[[Corpus], Retriever]] = {"keyword": KeywordRetriever}


def configured_variant() -> str:
    """RAG_VARIANT env (used by the eval runner) beats `rag.variant` in config."""
    if os.getenv("RAG_VARIANT"):
        return os.environ["RAG_VARIANT"]
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    return (cfg.get("rag") or {}).get("variant", "keyword")


def get_retriever(corpus: Corpus, variant: str | None = None) -> Retriever:
    name = variant or configured_variant()
    if name in VARIANTS:
        return VARIANTS[name](corpus)
    from rag.pipeline import Pipeline
    from rag.variants import all_configs
    configs = all_configs()
    if name not in configs:
        raise ValueError(f"unknown retriever variant {name!r}; known: {sorted(VARIANTS) + sorted(configs)}")
    return Pipeline(corpus, configs[name])
