"""Pipeline board, client threads, analytics and health."""
from __future__ import annotations

from collections import Counter, defaultdict

from fastapi import APIRouter, HTTPException

from agent.llm import profile_name
from agent.tools import ToolFailed
from apps.api import db
from apps.api.runtime import runtime
from apps.api.schemas import (Accepted, Analytics, CategoryStat, Health, Message, Pipeline, PipelineCard, ThreadList,
                              ThreadSummary)
from apps.api.security import User

router = APIRouter(prefix="/api", tags=["work"])
STAGES = ["drafted", "submitted", "viewed", "replied", "interview", "hired", "lost"]
REPLIED = {"replied", "interview", "hired"}


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


@router.get("/threads", response_model=ThreadList)
async def threads(u: dict = User) -> ThreadList:
    with db.engine().begin() as c:
        pend = {r.market_thread_id: r.thread_id for r in c.execute(
            db.select(db.runs.c.market_thread_id, db.runs.c.thread_id).where(
                db.runs.c.user_id == u["id"], db.runs.c.kind == "conversation",
                db.runs.c.status == "awaiting_approval"))}
        titles = {p.market_thread_id: p.title for p in c.execute(
            db.select(db.proposals.c.market_thread_id, db.proposals.c.title).where(db.proposals.c.user_id == u["id"]))}
    try:
        res = await runtime.call(u["id"], "liaison", "marketplace.list_messages", {})
    except ToolFailed as e:
        raise HTTPException(503, str(e))
    out = []
    for t in res["items"]:
        msgs = [Message(id=m["id"], sender=m.get("sender", m.get("from")), body=m["body"], at=m["at"])
                for m in t.get("messages", [])]
        out.append(ThreadSummary(id=t["id"], job_id=t["job_id"], job_title=titles.get(t["id"]), stage=t["stage"],
                                 last_message=msgs[-1] if msgs else None, pending_run=pend.get(t["id"]), messages=msgs))
    return ThreadList(items=sorted(out, key=lambda t: t.last_message.at if t.last_message else "", reverse=True))


@router.post("/threads/{thread_id}/draft", response_model=Accepted, status_code=202)
async def draft_reply(thread_id: str, u: dict = User) -> Accepted:
    try:
        res = await runtime.call(u["id"], "liaison", "marketplace.list_messages", {"thread_id": thread_id})
    except ToolFailed as e:
        raise HTTPException(503, str(e))
    if not res["items"]:
        raise HTTPException(404, "thread not found")
    t = runtime.start_conversation(u["id"], thread_id, len(res["items"][0]["messages"]))
    return Accepted(thread_id=t, status="running")


@router.get("/analytics", response_model=Analytics)
def analytics(u: dict = User) -> Analytics:
    with db.engine().begin() as c:
        props = c.execute(db.select(db.proposals).where(db.proposals.c.user_id == u["id"])).fetchall()
        rejects = c.execute(db.select(db.approvals.c.note).where(db.approvals.c.user_id == u["id"],
                                                                 db.approvals.c.action == "reject")).fetchall()
        skips = c.execute(db.select(db.runs.c.summary).where(db.runs.c.user_id == u["id"], db.runs.c.kind == "bid",
                                                             db.runs.c.status.in_(["skipped", "skip_suggested"]))).fetchall()
    by = defaultdict(list)
    for p in props:
        by[p.category or "other"].append(p)
    cats = []
    for cat, ps in sorted(by.items()):
        rep = sum(p.stage in REPLIED for p in ps)
        hires = sum(p.stage == "hired" for p in ps)
        cats.append(CategoryStat(category=cat, proposals=len(ps), replies=rep, hires=hires,
                                 reply_rate=round(rep / len(ps), 3), hire_rate=round(hires / len(ps), 3),
                                 connects=sum(p.connects or 0 for p in ps)))
    n = len(props)
    reasons = Counter()
    for (s,) in skips:
        for r in (s or {}).get("reasons", [])[:1]:
            reasons[r.split("(")[0].strip()] += 1
    rej = Counter((note or "").strip().lower()[:80] for (note,) in rejects if note)
    return Analytics(
        proposals=n, reply_rate=round(sum(p.stage in REPLIED for p in props) / n, 3) if n else 0.0,
        hire_rate=round(sum(p.stage == "hired" for p in props) / n, 3) if n else 0.0,
        connects_spent=sum(p.connects or 0 for p in props),
        connects_on_replied=sum(p.connects or 0 for p in props if p.stage in REPLIED),
        avg_usd_per_proposal=round(sum(p.usd or 0 for p in props) / n, 5) if n else 0.0,
        avg_latency_s=round(sum(p.latency_ms or 0 for p in props) / n / 1000, 2) if n else 0.0,
        by_category=cats, rejection_reasons=[{"reason": k, "count": v} for k, v in rej.most_common(8)],
        skip_reasons=[{"reason": k, "count": v} for k, v in reasons.most_common(8)])


@router.get("/health", response_model=Health)
async def health(u: dict = User) -> Health:
    s = db.get_settings(u["id"])
    ok, detail = True, None
    try:
        h = await runtime.call(u["id"], "scout", "marketplace.list_events", {"after_id": 10 ** 9})
        ok = h is not None
    except ToolFailed as e:
        ok, detail = False, str(e)[:200]
    except Exception as e:  # any transport problem counts as unavailable for the banner
        ok, detail = False, f"{type(e).__name__}: {e}"[:200]
    with db.engine().begin() as c:
        row = c.execute(db.select(db.sync_state.c.last_run_at).where(db.sync_state.c.user_id == u["id"])).first()
    return Health(marketplace_ok=ok, marketplace_mode=s.get("marketplace", "gigsim"), marketplace_detail=detail,
                  llm_available=runtime.llm.available,
                  model_profile=profile_name() if runtime.llm.available else "rules (no API key)",
                  sync_last_run=row.last_run_at if row else None)
