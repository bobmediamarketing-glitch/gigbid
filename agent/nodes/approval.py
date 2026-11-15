"""Human approval (R4) and submission.

`approval` pauses the graph with `interrupt()` and shows the human exactly what would be sent:
the cleaned cover letter, price, Connects cost (from a dry-run of the real write), evidence per
claim, the Critic's notes and the compliance verdict. The run resumes with an Approval
(approve / edit / reject). `submit` is a separate node and both of its writes carry
idempotency keys derived from the run id, so resuming after a crash submits exactly once.
"""
from __future__ import annotations

from langgraph.types import interrupt

from agent.handoffs import Approval
from agent.memory import outcomes as outcome_memory
from agent.memory import style as style_memory
from agent.nodes.base import Ctx, node


def _client_text(state: dict) -> str:
    v = state.get("compliance")
    return (v.redacted_text if v and v.redacted_text else None) or state["draft"].client_text()


@node("approval")
async def approval(state: dict, ctx: Ctx, usages: list) -> dict:
    d, q, job = state["draft"], state["quote"], state["job"]
    text = _client_text(state)
    prev = await ctx.tools.call("approval", "marketplace.create_proposal_draft", {
        "job_id": job["id"], "cover_letter": text, "bid_amount": q.amount, "bid_type": q.bid_type,
        "screening_answers": d.screening_answers, "idempotency_key": f"{state['run_id']}-preview", "dry_run": True})
    p = prev.get("preview") or {}
    c = state.get("compliance")
    answer = interrupt({
        "type": "approve_proposal", "run_id": state["run_id"], "job_id": job["id"], "job_title": job["title"],
        "cover_letter": text, "cover_letter_with_citations": d.cover_letter,
        "screening_questions": state["spec"].screening_questions, "screening_answers": d.screening_answers,
        "bid_amount": q.amount, "bid_type": q.bid_type, "price_rationale": q.rationale,
        "connects_cost": p.get("connects_cost") or q.connects_cost, "connects_balance_after": p.get("connects_balance_after"),
        "claims": [cl.model_dump() for cl in d.claims],
        "evidence": {i: (state.get("evidence") or {}).get(i, "")[:600] for cl in d.claims for i in cl.evidence_ids},
        "risk": state["risk"].model_dump() if state.get("risk") else None,
        "verification": state.get("verification"),
        "critique": state["critiques"][-1].model_dump() if state.get("critiques") else None,
        "compliance": c.model_dump() if c else None,
        "decision": state["decision"].model_dump(),
    })
    a = Approval.model_validate(answer)
    if a.action == "reject":
        return {"approval": a, "status": "rejected"}
    if a.action == "edit":
        upd, learned = {}, []
        if a.cover_letter:
            upd["cover_letter"] = a.cover_letter
            # The edit is diffed and staged for style memory; a pattern becomes a rule only after repeats.
            learned = await style_memory.record_edit(ctx.store, state.get("user_id") or "local", text, a.cover_letter)
        out = {"approval": a, "draft": d.model_copy(update=upd), "compliance": None}
        if learned:
            out["trace"] = [{"node": "approval", "ms": 0.0,
                             "note": "style memory learned: " + "; ".join(r["value"] for r in learned)}]
        if a.bid_amount:
            out["quote"] = q.model_copy(update={"amount": a.bid_amount})
        return out
    return {"approval": a}


@node("submit")
async def submit(state: dict, ctx: Ctx, usages: list) -> dict:
    d, q, job, rid = state["draft"], state["quote"], state["job"], state["run_id"]
    draft = await ctx.tools.call("submit", "marketplace.create_proposal_draft", {
        "job_id": job["id"], "cover_letter": _client_text(state), "bid_amount": q.amount, "bid_type": q.bid_type,
        "screening_answers": d.screening_answers, "idempotency_key": f"{rid}-draft"})
    pid = draft["proposal"]["id"]
    sub = await ctx.tools.call("submit", "marketplace.submit_proposal",
                               {"proposal_id": pid, "idempotency_key": f"{rid}-submit"})
    prop = sub["proposal"]
    status = "pending_platform_confirmation" if prop["status"] == "pending_platform_confirmation" else "submitted"
    # Stage what was sent (features only) so outcome memory can learn once the client reacts.
    await outcome_memory.stage_submission(ctx.store, state.get("user_id") or "local", prop["id"],
                                          outcome_memory.features(state))
    return {"submission": prop, "status": status}
