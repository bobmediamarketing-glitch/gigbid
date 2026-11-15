"""Shared node plumbing: runtime context, budget checks, tracing and failure handling.

Every agent node is wrapped by `@node(name)`. The wrapper
- skips work once the run has halted (skipped, queued, blocked, ...),
- enforces the step / token / cost budget from config before the node runs,
- turns marketplace outages into status `queued` (degraded mode) and other tool errors into `failed`,
- appends one trace event (latency, model, tokens, cost) and adds usage to the counters.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from langgraph.runtime import Runtime

from agent.llm import LLM, Usage
from agent.settings import ROOT, section
from agent.tools import ToolBox, ToolFailed, ToolNotAllowed

HALTED = {"skipped", "queued", "blocked", "rejected", "budget_exceeded", "failed", "submitted",
          "pending_platform_confirmation"}


@dataclass
class Ctx:
    tools: ToolBox
    llm: LLM = field(default_factory=LLM)
    budget: str = "bid"
    personas_dir: Path = ROOT / "data" / "personas"


def halted(state: dict) -> bool:
    return state.get("status") in HALTED


def over_budget(state: dict, budget: str) -> str | None:
    b = section("budgets")[budget]
    if state.get("steps", 0) >= b["max_steps"]:
        return f"step budget {b['max_steps']}"
    if state.get("tokens", 0) >= b["max_tokens"]:
        return f"token budget {b['max_tokens']}"
    if state.get("usd", 0.0) >= b["max_usd"]:
        return f"cost budget ${b['max_usd']}"
    return None


def node(name: str):
    def deco(fn):
        async def wrapped(state: dict, runtime: Runtime[Ctx]) -> dict:
            if halted(state):
                return {}
            ctx = runtime.context
            why = over_budget(state, ctx.budget)
            if why:
                return {"status": "budget_exceeded", "errors": [f"{name}: {why} reached"],
                        "trace": [{"node": name, "ms": 0.0, "note": f"halted: {why}"}]}
            t0 = time.perf_counter()
            usages: list[Usage] = []
            try:
                out = await fn(state, ctx, usages)
            except ToolFailed as e:
                status = "queued" if e.code in ("marketplace_unavailable", "rate_limited") else "failed"
                out = {"status": status, "errors": [f"{name}: {e}"]}
            except ToolNotAllowed as e:
                out = {"status": "failed", "errors": [f"{name}: {e}"]}
            ms = (time.perf_counter() - t0) * 1000
            ev = {"node": name, "ms": round(ms, 1), "model": ",".join(sorted({u.model for u in usages})) or "rules",
                  "tokens_in": sum(u.tokens_in for u in usages), "tokens_out": sum(u.tokens_out for u in usages),
                  "usd": round(sum(u.usd for u in usages), 6)}
            errs = [f"{name}: llm fallback ({u.error})" for u in usages if u.error]
            out = dict(out or {})
            out["trace"] = [ev] + out.get("trace", [])
            out["steps"] = 1
            out["tokens"] = ev["tokens_in"] + ev["tokens_out"]
            out["usd"] = ev["usd"]
            if errs:
                out["errors"] = out.get("errors", []) + errs
            return out
        # no functools.wraps: LangGraph reads this signature to inject `runtime`
        wrapped.__name__ = wrapped.__qualname__ = name
        wrapped.__doc__ = fn.__doc__
        return wrapped
    return deco


def load_profile(ctx: Ctx, persona: str) -> dict:
    return json.loads((ctx.personas_dir / persona / "profile.json").read_text(encoding="utf-8"))
