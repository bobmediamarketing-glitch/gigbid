"""Deterministic job-post parsing shared by the Analyst (as its rule path) and the Matcher."""
from __future__ import annotations

import re
from functools import lru_cache

from agent.handoffs import Requirement
from rag.ingest.loaders import skill_vocab


@lru_cache(maxsize=1)
def vocab() -> dict[str, str]:
    return {k.lower(): v.lower() for k, v in skill_vocab().items()}


def skills_in(text: str) -> list[str]:
    low = text.lower()
    out = []
    for s, hint in vocab().items():
        if re.search(rf"(?<![\w-]){re.escape(s)}(?![\w-])", low) or hint[:25] in low:
            out.append(s)
    return out


def requirements(job: dict, clean_text: str) -> list[Requirement]:
    lines = [ln.strip()[1:].strip() for ln in clean_text.splitlines() if re.match(r"^\s*[-*•]\s+", ln)]
    reqs = [Requirement(text=ln, skills=skills_in(ln)) for ln in lines if len(ln) > 3]
    if not reqs:  # vague post: fall back to posted tags
        reqs = [Requirement(text=f"Experience with {s}", skills=[s.lower()]) for s in job.get("skills", [])]
    return reqs


def goal(clean_text: str, category: str | None) -> str:
    m = re.search(r"(?i)the goal is ([^.\n]+)", clean_text)
    if m:
        return m.group(1).strip()
    return f"a working {category.lower()} solution" if category else "a working solution"


def is_vague(job: dict, clean_text: str) -> bool:
    return not any(re.match(r"^\s*[-*•]\s+", ln) for ln in clean_text.splitlines()) and len(clean_text) < 300
