"""Shared node plumbing: runtime context, budget checks, tracing and failure handling.

Every agent node is wrapped by `@node(name)`. The wrapper
- skips work once the run has halted (skipped, queued, blocked, ...),
- enforces the step / token / cost budget from config before the node runs,
- runs the node with a per-node timeout and retries transient failures (timeouts, dropped connections)
  with backoff; when retries run out the run moves to `dead_letter` with the reason (C7),
- turns marketplace outages into status `queued` (degraded mode) and other tool errors into `dead_letter`,
- moves the run to `needs_attention` when a step / token / cost budget is reached (C4),
- appends one trace event (latency, model, tokens, cost) and adds usage to the counters.
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from langgraph.runtime import Runtime

from agent.llm import LLM, Usage
from agent.settings import ROOT, section
from agent.tools import ToolBox, ToolFailed, ToolNotAllowed

HALTED = {"skipped", "skip_suggested", "watching", "queued", "blocked", "rejected", "needs_attention",
          "dead_letter", "submitted", "pending_platform_confirmation", "sent", "no_action"}


class Transient(Exception):
    """Raise from a node for a failure worth retrying."""


TRANSIENT = (TimeoutError, asyncio.TimeoutError, ConnectionError, Transient)
try:  # network errors from httpx / anyio count as transient too
    import anyio
    import httpx
    TRANSIENT = TRANSIENT + (httpx.TransportError, anyio.ClosedResourceError, anyio.BrokenResourceError)
except ImportError:  # pragma: no cover
    pass


@dataclass
class Ctx:
    tools: ToolBox
    llm: LLM = field(default_factory=LLM)
    budget: str = "bid"
    personas_dir: Path = ROOT / "data" / "personas"
    store: object | None = None           # LangGraph store (long-term memory); set from the runtime


def _per_node(key: str, name: str, default):
    cfg = section("bid_graph").get(key, {})
    return cfg.get(name, cfg.get("default", default))


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
            if runtime.store is not None:
                ctx.store = runtime.store
            why = over_budget(state, ctx.budget)
            if why:
                return {"status": "needs_attention", "errors": [f"{name}: {why} reached"],
                        "trace": [{"node": name, "ms": 0.0, "note": f"needs attention: {why}"}]}
            t0 = time.perf_counter()
            usages: list[Usage] = []
            timeout = _per_node("timeouts_s", name, 60)
            retries = _per_node("retries", name, 2)
            attempt, out = 0, None
            while True:
                try:
                    out = await asyncio.wait_for(fn(state, ctx, usages), timeout)
                    break
                except ToolFailed as e:
                    status = "queued" if e.code in ("marketplace_unavailable", "rate_limited") else "dead_letter"
                    out = {"status": status, "errors": [f"{name}: {e}"]}
                    break
                except ToolNotAllowed as e:
                    out = {"status": "dead_letter", "errors": [f"{name}: {e}"]}
                    break
                except TRANSIENT as e:
                    attempt += 1
                    if attempt > retries:
                        out = {"status": "dead_letter",
                               "errors": [f"{name}: gave up after {attempt} attempts ({type(e).__name__}: {e})"]}
                        break
                    await asyncio.sleep(min(8.0, 0.5 * 2 ** (attempt - 1)))
            ms = (time.perf_counter() - t0) * 1000
            ev = {"node": name, "ms": round(ms, 1), "model": ",".join(sorted({u.model for u in usages})) or "rules",
                  "tokens_in": sum(u.tokens_in for u in usages), "tokens_out": sum(u.tokens_out for u in usages),
                  "usd": round(sum(u.usd for u in usages), 6)}
            errs = [f"{name}: llm fallback ({u.error})" for u in usages if u.error]
            if attempt:
                ev["retries"] = attempt
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
