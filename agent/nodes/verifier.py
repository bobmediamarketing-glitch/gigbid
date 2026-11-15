"""Claim verification node: every factual sentence must be backed by the evidence the writer was given."""
from __future__ import annotations

from agent.nodes.base import Ctx, node
from rag.verify import verify_text


@node("verify")
async def verify(state: dict, ctx: Ctx, usages: list) -> dict:
    d, ev = state["draft"], state.get("evidence", {})
    text, v = verify_text(d.cover_letter, ev)
    answers = []
    for a in d.screening_answers:
        t, va = verify_text(a, ev)
        answers.append(t or a)
        v.merge(va)
    removed_set = {r["sentence"] for r in v.removed}
    claims = [c.model_copy(update={"supported": c.text not in removed_set and all(i in ev for i in c.evidence_ids)})
              for c in d.claims]
    return {"draft": d.model_copy(update={"cover_letter": text, "screening_answers": answers, "claims": claims}),
            "verification": v.summary()}


