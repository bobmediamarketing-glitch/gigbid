"""Versioned prompts. Each file starts with a `version:` line; the version is logged on every run."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

DIR = Path(__file__).parent


@lru_cache(maxsize=None)
def load(name: str) -> tuple[str, str]:
    raw = (DIR / f"{name}.md").read_text(encoding="utf-8")
    first, _, body = raw.partition("\n")
    version = first.split(":", 1)[1].strip() if first.lower().startswith("version:") else "0"
    return body.strip(), f"{name}@{version}"
