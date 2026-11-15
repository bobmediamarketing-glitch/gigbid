"""Query-side transforms: requirement decomposition (V1) and skill-hint expansion (V8 re-query)."""
from __future__ import annotations

import re

from rag.ingest.loaders import skill_vocab

BULLET = re.compile(r"^\s*[-*•]\s+(.+)$", re.M)


def decompose(text: str, max_parts: int = 8) -> list[str]:
    """One query per requirement. Bulleted lists first; otherwise sentences that name a known
    skill; otherwise the whole post (vague posts cannot be decomposed)."""
    parts = [b.strip() for b in BULLET.findall(text) if len(b.strip()) > 3]
    if not parts:
        vocab = {k.lower() for k in skill_vocab()}
        sents = re.split(r"(?<=[.!?])\s+|\n+", text)
        parts = [s.strip() for s in sents if any(re.search(rf"(?<![\w-]){re.escape(v)}(?![\w-])", s.lower())
                                                  for v in vocab)]
    return parts[:max_parts] or [text]


def skills_in(text: str) -> list[str]:
    low = text.lower()
    return [s for s, hint in skill_vocab().items()
            if re.search(rf"(?<![\w-]){re.escape(s.lower())}(?![\w-])", low) or hint.lower()[:25] in low]


def expand(query: str) -> str:
    """Add the canonical skill names and their implied phrasing, so 'an async python api with
    automatic docs' also searches for 'fastapi' and vice versa."""
    vocab = skill_vocab()
    found = skills_in(query)
    extra = [f"{s} {vocab[s]}" for s in found]
    return query + (" | " + " | ".join(extra) if extra else "")
