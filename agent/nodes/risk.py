"""Risk Assessor: scam patterns, client history signals and detected injections -> RiskReport."""
from __future__ import annotations

import json

from pydantic import BaseModel, Field

from agent import prompts
from agent.guards import fence, scam_hits
from agent.handoffs import RiskReport
from agent.nodes.base import Ctx, node
from agent.settings import section

BASE = {"credentials": 0.9, "payment": 0.9, "off_platform": 0.8, "free_work": 0.75}


class _LLMRisk(BaseModel):
    scam_score: float = Field(ge=0, le=1)
    scam_type: str | None = None
    red_flags: list[str] = []


def client_signals(client: dict) -> tuple[float, dict]:
    cfg = section("guardrails")["client_signals"]
    add, sig = 0.0, {}
    if not client.get("payment_verified", True):
        add += cfg["unverified_payment"]
        sig["payment_unverified"] = True
    if client.get("total_spent", 0) == 0 and client.get("hires", 0) == 0:
        add += cfg["new_client_no_spend"]
        sig["no_hire_history"] = True
    lh = cfg["low_hire_rate"]
    if client.get("jobs_posted", 0) >= lh["min_jobs"] and client.get("hire_rate", 1) < lh["below"]:
        add += lh["weight"]
        sig["low_hire_rate"] = client["hire_rate"]
    return add, sig


@node("risk")
async def risk(state: dict, ctx: Ctx, usages: list) -> dict:
    job, clean, client = state["job"], state["job_text_clean"], state["client"]
    hits = scam_hits(clean)
    add, sig = client_signals(client)
    kind = max(hits, key=lambda k: BASE.get(k, 0.5)) if hits else None
    score = min(1.0, (BASE.get(kind, 0.0) if kind else 0.0) + add)
    flags = [f"{k}: {', '.join(v[:2])}" for k, v in hits.items()] + [f"client: {k}" for k in sig]
    spans = state.get("injection_spans", [])
    if spans:
        flags.append(f"prompt injection removed ({len(spans)} span(s))")
    system, _ = prompts.load("risk")
    out, u = await ctx.llm.structured("risk", _LLMRisk, system,
                                      f"Client history: {json.dumps(client)}\nRule flags: {flags}\n\nPost:\n{fence(clean)}")
    usages.append(u)
    if out is not None:
        # Rules catch known patterns precisely; the model adds judgement on new ones.
        if kind:
            score = max(score, out.scam_score)
        else:
            score = max(score, round(0.8 * out.scam_score + add, 3))
            if out.scam_type in BASE and out.scam_score >= 0.5:
                kind = out.scam_type
        flags += [f"llm: {f}" for f in out.red_flags[:3]]
    return {"risk": RiskReport(job_id=job["id"], scam_score=round(min(score, 1.0), 3), scam_type=kind, red_flags=flags,
                               injection_detected=bool(spans), injection_spans=spans, client_signals=sig)}
