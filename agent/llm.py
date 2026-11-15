"""Per-node model routing (open / paid profiles from config) with token and cost accounting.

`structured(node, Schema, system, user)` returns (parsed | None, usage). It returns None when
no API key is configured or the call fails after retries; every node then falls back to its
deterministic rule path, so CI and offline demos run with no keys and the graph never stalls.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import TypeVar

from pydantic import BaseModel

from agent.settings import section

log = logging.getLogger("gigbid.llm")
T = TypeVar("T", bound=BaseModel)
KEYS = {"groq": "GROQ_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}


@dataclass
class Usage:
    model: str = "rules"
    tokens_in: int = 0
    tokens_out: int = 0
    usd: float = 0.0
    ms: float = 0.0
    error: str | None = None

    @property
    def tokens(self) -> int:
        return self.tokens_in + self.tokens_out


def profile_name() -> str:
    return os.getenv("GIGBID_MODEL_PROFILE") or section("models").get("profile", "open")


def model_for(node: str) -> tuple[str, str]:
    m = section("models")
    p = m["profiles"][profile_name()]
    return p["provider"], p.get("nodes", {}).get(node, p["default"])


def enabled() -> bool:
    if os.getenv("GIGBID_OFFLINE") == "1":
        return False
    provider, _ = model_for("writer")
    return bool(os.getenv(KEYS.get(provider, "")))


def _chat(node: str, model_override: str | None = None):
    provider, model = model_for(node)
    if model_override:
        provider, model = "groq", model_override  # the fallback is an open model on Groq
    m = section("models")
    temp = m.get("temperature", {})
    kw = dict(model=model, temperature=temp.get(node, temp.get("default", 0.2)),
              timeout=m.get("timeout_s", 45), max_retries=m.get("max_retries", 2))
    if provider == "groq":
        from langchain_groq import ChatGroq
        return ChatGroq(**kw), model
    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic  # optional dependency for the paid profile
        return ChatAnthropic(**kw), model
    raise ValueError(f"unknown provider {provider}")


def cost(model: str, tin: int, tout: int) -> float:
    pin, pout = section("models").get("prices", {}).get(model, [0, 0])
    return (tin * pin + tout * pout) / 1e6


@dataclass
class LLM:
    """Injected into the graph through the runtime context; tests swap in a fake."""
    available: bool = field(default_factory=enabled)

    async def structured(self, node: str, schema: type[T], system: str, user: str) -> tuple[T | None, Usage]:
        if not self.available:
            return None, Usage()
        t0 = time.perf_counter()
        fb = section("models").get("fallback", {})
        attempts = [None] + ([fb["model"]] if node in fb.get("nodes", []) and fb.get("model") else [])
        out, err, model = None, None, model_for(node)[1]
        for override in attempts:
            try:
                chat, model = _chat(node, override)
                runnable = chat.with_structured_output(schema, include_raw=True)
                out = await runnable.ainvoke([("system", system), ("user", user)])
                break
            except Exception as e:  # network, quota, invalid JSON: try the fallback model, then the rule path
                log.warning("llm %s (%s) failed: %s", node, model, e)
                err = f"{model}: {str(e)[:180]}"
        if out is None:
            return None, Usage(model=model, error=err, ms=(time.perf_counter() - t0) * 1000)
        raw, parsed = out.get("raw"), out.get("parsed")
        um = getattr(raw, "usage_metadata", None) or {}
        tin, tout = um.get("input_tokens", 0), um.get("output_tokens", 0)
        u = Usage(model=model, tokens_in=tin, tokens_out=tout, usd=cost(model, tin, tout),
                  ms=(time.perf_counter() - t0) * 1000, error=None if parsed else "unparsed")
        return parsed, u
