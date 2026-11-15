"""Proposals: the pipeline board, paragraph regeneration, and an on-demand marketplace sync."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from apps.api import db
from apps.api.auth import User
from apps.api.runtime import runtime
from agent.mcp_client import ToolFailed
from apps.api.routers.runs import _owned
from apps.api.schemas import Accepted, Pipeline, PipelineCard, RegenerateIn, RegenerateOut

router = APIRouter(prefix="/api", tags=["proposals"])
STAGES = ["drafted", "submitted", "viewed", "replied", "interview", "hired", "lost"]


@router.get("/pipeline", response_model=Pipeline)
def pipeline(u: dict = User) -> Pipeline:
    cards = []
    with db.engine().begin() as c:
        for r in c.execute(db.select(db.runs).where(db.runs.c.user_id == u["id"], db.runs.c.kind == "bid",
                                                    db.runs.c.status == "awaiting_approval")):
            s = r.summary or {}
            cards.append(PipelineCard(id=r.job_id, title=s.get("title") or r.job_id, stage="drafted",
                                      category=s.get("category"), bid_amount=s.get("price"),
                                      connects=s.get("connects_cost"), thread_id=r.thread_id, updated_at=r.updated_at))
        for p in c.execute(db.select(db.proposals).where(db.proposals.c.user_id == u["id"])):
            cards.append(PipelineCard(id=p.proposal_id, title=p.title or p.job_id, stage=p.stage, category=p.category,
                                      bid_amount=p.bid_amount, connects=p.connects, thread_id=p.thread_id,
                                      market_thread_id=p.market_thread_id, updated_at=p.updated_at))
    return Pipeline(stages=STAGES, cards=sorted(cards, key=lambda x: -x.updated_at))


@router.post("/sync", response_model=Accepted)
async def sync_now(u: dict = User) -> Accepted:
    """Pull marketplace events now (the background loop does this every few seconds)."""
    try:
        n = await runtime.sync_user(u["id"])
    except ToolFailed as e:
        raise HTTPException(503, str(e))
    return Accepted(thread_id="-", status=f"{n} events")


@router.post("/runs/{thread_id}/regenerate", response_model=RegenerateOut)
async def regenerate(thread_id: str, body: RegenerateIn, u: dict = User) -> RegenerateOut:
    """Rewrite one paragraph of the pending draft with the writer model, grounded in the same evidence.
    The result is returned for the editor; it is only used if the user saves it as an edit."""
    _owned(u["id"], thread_id)
    pending = await runtime.pending(u["id"], thread_id)
    if not pending or pending.get("type") != "approve_proposal":
        raise HTTPException(409, "no draft is waiting for approval")
    if not runtime.llm.available:
        raise HTTPException(409, "regenerating needs a model: set GROQ_API_KEY (rule mode cannot rewrite)")
    from pydantic import BaseModel

    from agent.guards import fence

    class Para(BaseModel):
        text: str
    paras = pending["cover_letter_with_citations"].split("\n\n")
    if body.paragraph >= len(paras):
        raise HTTPException(422, "no such paragraph")
    ev = "\n".join(f"[{k}] {v}" for k, v in (pending.get("evidence") or {}).items())
    from agent import prompts
    tmpl, _ = prompts.load("regenerate")
    system = tmpl.replace("{instruction}", f"Extra instruction from the freelancer: {body.instruction}"
                          if body.instruction else "")
    out, usage = await runtime.llm.structured(
        "writer", Para, system,
        f"EVIDENCE:\n{ev}\n\nFULL DRAFT:\n{fence(pending['cover_letter_with_citations'])}\n\n"
        f"PARAGRAPH TO REWRITE:\n{paras[body.paragraph]}")
    if out is None:
        raise HTTPException(502, f"model failed: {usage.error}")
    from rag.verify import verify_text
    text, _ = verify_text(out.text, pending.get("evidence") or {})
    return RegenerateOut(paragraph=body.paragraph, text=text, model=usage.model)
