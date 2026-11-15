"""Bid decision: joins the three parallel reports. Deterministic and explainable on purpose:
every skip names the rule that caused it, and every threshold lives in config."""
from __future__ import annotations

from agent.handoffs import BidDecision
from agent.nodes.base import Ctx, node
from agent.settings import section


def decide_rules(state: dict) -> BidDecision:
    cfg = section("bid_graph")["decision"]
    spec, risk, fit, job, profile = state["spec"], state["risk"], state["fit"], state["job"], state["profile"]
    reasons, bid = [], True
    if risk.scam_score > cfg["max_scam_score"]:
        bid = False
        reasons.append(f"likely scam ({risk.scam_type or 'client signals'}, score {risk.scam_score:.2f})")
    if not fit.in_domain:
        bid = False
        reasons.append(f"outside my categories ({job.get('category')})")
    if fit.coverage < cfg["min_coverage"]:
        bid = False
        reasons.append(f"portfolio covers {fit.coverage:.0%} of requirements (min {cfg['min_coverage']:.0%})")
    floor = profile["hourly_floor"] if spec.budget_type == "hourly" else profile["fixed_floor"]
    if spec.budget_max < floor:
        bid = False
        reasons.append(f"budget max {spec.budget_max:g} is below my floor {floor:g}")
    cost = job.get("connects_cost", 0)
    if state.get("connects_balance", 0) - cost < cfg["min_connects_reserve"]:
        bid = False
        reasons.append(f"not enough Connects ({state.get('connects_balance')} left, job costs {cost})")
    action = "bid" if bid else "skip"
    if bid:
        reasons.append(f"covers {fit.coverage:.0%} of requirements, scam score {risk.scam_score:.2f}")
        if risk.injection_detected:
            reasons.append("post contained a prompt injection; it was removed before drafting")
        conf = 0.5 + 0.5 * fit.coverage * (1 - risk.scam_score)
    else:
        conf = min(0.95, 0.6 + 0.1 * len(reasons))
        # Close calls are watched, not skipped: the only blockers are a coverage or scam score just past
        # the line, nothing hard (off-domain, below floor, out of Connects, a clear scam).
        hard = (not fit.in_domain or spec.budget_max < floor or risk.scam_score > cfg["watch_max_scam_score"]
                or state.get("connects_balance", 0) - cost < cfg["min_connects_reserve"])
        if not hard and fit.coverage >= cfg["watch_min_coverage"]:
            action = "watch"
            reasons.append("close call: watching instead of skipping")
    return BidDecision(job_id=job["id"], action=action, bid=bid, confidence=round(conf, 3), reasons=reasons)


def skip_status(d: BidDecision, risk, autonomy: str) -> str:
    """Scams always close. Other skips close only if the user allowed auto-skip; otherwise they wait
    in the inbox as a suggestion the user confirms. Nothing in GigBid is ever auto-sent."""
    if d.action == "watch":
        return "watching"
    if risk.scam_score > section("bid_graph")["decision"]["max_scam_score"]:
        return "skipped"
    return "skipped" if autonomy == "auto_skip" else "skip_suggested"


@node("decide")
async def decide(state: dict, ctx: Ctx, usages: list) -> dict:
    d = decide_rules(state)
    if d.bid:
        return {"decision": d}
    autonomy = state.get("autonomy") or section("autonomy").get("default", "suggest")
    return {"decision": d, "status": skip_status(d, state["risk"], autonomy)}
