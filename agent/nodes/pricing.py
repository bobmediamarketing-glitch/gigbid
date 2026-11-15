"""Pricing Strategist: market percentiles + persona floor + client budget -> PriceQuote."""
from __future__ import annotations

from agent.handoffs import PriceQuote
from agent.memory import outcomes as outcome_memory
from agent.nodes.base import Ctx, node
from agent.settings import section

HINT_TARGET = {"below_p25": "p25", "p25_p50": "p25", "p50_p75": "p50", "above_p75": "p75"}


def quote(spec, stats: list[dict], profile: dict, connects_cost: int, hint: str | None = None) -> PriceQuote:
    cfg = section("bid_graph")["pricing"]
    floor = profile["hourly_floor"] if spec.budget_type == "hourly" else profile["fixed_floor"]
    st = next((s for s in stats if s["budget_type"] == spec.budget_type), None)
    if st:
        target = HINT_TARGET.get(hint or "", cfg["target_percentile"])
        amount = st[target]
        why = f"market {target} for {spec.category} is {amount:g}"
        if target != cfg["target_percentile"]:
            why += f" (outcome memory: bids at {hint} got the most replies in this category)"
    else:
        amount = (spec.budget_min + spec.budget_max) / 2
        why = "no market data; midpoint of the client's range"
    if cfg.get("stay_inside_budget", True):
        clamped = min(max(amount, spec.budget_min), spec.budget_max)
        if clamped != amount:
            why += f", moved into the client's range {spec.budget_min:g}-{spec.budget_max:g}"
        amount = clamped
    if amount < floor:
        why += f", raised to my floor {floor:g}"
        amount = floor
    step = 1 if spec.budget_type == "hourly" else 25
    amount = max(step, round(amount / step) * step)
    market = {k: st[k] for k in ("p25", "p50", "p75")} if st else {}
    return PriceQuote(job_id=spec.job_id, bid_type=spec.budget_type, amount=amount, market=market, floor=floor,
                      rationale=why, connects_cost=connects_cost)


@node("pricing")
async def pricing(state: dict, ctx: Ctx, usages: list) -> dict:
    spec = state["spec"]
    stats = await ctx.tools.call("pricing", "marketplace.get_price_stats",
                                 {"category": spec.category or "", "budget_type": spec.budget_type}) \
        if spec.category else {"items": []}
    items = stats["items"] if isinstance(stats, dict) else stats
    entry = await outcome_memory.lessons(ctx.store, state.get("user_id") or "local", spec.category)
    return {"quote": quote(spec, items, state["profile"], state["job"].get("connects_cost", 0),
                           outcome_memory.price_hint(entry))}
