"""Job inbox: list jobs ranked by fit, analyse one, scout new ones, confirm a skip."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from apps.api import db
from apps.api.auth import User
from apps.api.runtime import runtime
from agent.mcp_client import ToolFailed
from apps.api.schemas import Accepted, JobCard, JobList, RunSummary

router = APIRouter(prefix="/api", tags=["jobs"])


def _summary(row) -> RunSummary:
    s = row.summary or {}
    keep = {k: v for k, v in s.items() if k in RunSummary.model_fields}
    return RunSummary(**keep | {"thread_id": row.thread_id, "kind": row.kind, "status": row.status,
                                "updated_at": row.updated_at, "job_id": row.job_id,
                                "market_thread_id": row.market_thread_id})


def _onboarded(uid: int) -> None:
    if not db.get_settings(uid).get("onboarded"):
        raise HTTPException(409, "finish onboarding first")


@router.get("/jobs", response_model=JobList)
async def jobs(category: str | None = None, q: str | None = None, limit: int = 40, u: dict = User) -> JobList:
    _onboarded(u["id"])
    with db.engine().begin() as c:
        rows = {r.job_id: r for r in c.execute(db.select(db.runs).where(db.runs.c.user_id == u["id"],
                                                                         db.runs.c.kind == "bid"))}
    ok, items = True, []
    try:
        res = await runtime.call(u["id"], "scout", "marketplace.search_jobs",
                                 {"category": category, "query": q, "limit": max(1, min(limit, 100))})
        items = res["items"]
    except ToolFailed as e:
        if e.code != "marketplace_unavailable":
            raise HTTPException(502, str(e))
        ok = False  # degraded mode: show what we already analysed, with the banner
    cards = [JobCard(**{k: j[k] for k in JobCard.model_fields if k in j and k != "run"},
                     run=_summary(rows[j["id"]]) if j["id"] in rows else None) for j in items]
    seen = {c.id for c in cards}
    for jid, r in rows.items():  # analysed jobs stay visible even if they dropped off the feed
        if jid not in seen and r.summary.get("budget"):
            s = r.summary
            cards.append(JobCard(id=jid, title=s.get("title") or jid, category=s.get("category"), budget=s["budget"],
                                 posted_at="", connects_cost=s.get("connects_cost") or 0, run=_summary(r)))
    rank = {"bid": 0, "watch": 1, None: 2, "skip": 3}

    def key(c: JobCard):
        r = c.run
        return (rank.get(r.action if r else None, 2), -(r.coverage or 0) if r else 0, c.posted_at and -len(c.posted_at))
    cards.sort(key=key)
    return JobList(items=cards, analysed=sum(1 for c in cards if c.run), marketplace_ok=ok)


@router.post("/jobs/{job_id}/analyze", response_model=Accepted, status_code=202)
async def analyze(job_id: str, u: dict = User) -> Accepted:
    _onboarded(u["id"])
    t = await runtime.start_bid(u["id"], job_id)
    return Accepted(thread_id=t, status="running")


@router.post("/scout", response_model=list[Accepted], status_code=202)
async def scout(limit: int = 8, category: str | None = None, u: dict = User) -> list[Accepted]:
    """Analyse the newest jobs not seen yet (the worker does this on each saved search's schedule)."""
    _onboarded(u["id"])
    s = db.get_settings(u["id"])
    cats = [category] if category else (s.get("categories") or [None])
    per_cat = []
    try:
        for cat in cats:
            res = await runtime.call(u["id"], "scout", "marketplace.search_jobs", {"category": cat, "limit": 20})
            per_cat.append(res["items"])
    except ToolFailed as e:
        raise HTTPException(503, str(e))
    with db.engine().begin() as c:
        done = {r.job_id for r in c.execute(db.select(db.runs.c.job_id).where(db.runs.c.user_id == u["id"]))}
    # Round-robin across the user's categories so one busy category doesn't take every slot.
    queues = [[j for j in items if j["id"] not in done] for items in per_cat]
    todo, n = [], max(1, min(limit, 25))
    while len(todo) < n and any(queues):
        for q in queues:
            if q and len(todo) < n:
                todo.append(q.pop(0))
    return [Accepted(thread_id=await runtime.start_bid(u["id"], j["id"], j["title"]), status="running") for j in todo]


@router.post("/jobs/{job_id}/skip", response_model=Accepted)
def confirm_skip(job_id: str, u: dict = User) -> Accepted:
    """The user confirms a skip suggestion (or skips a job by hand)."""
    t = f"bid-u{u['id']}-{job_id}"
    db.upsert_run(t, u["id"], "bid", "skipped", {"skipped_by_user": True}, job_id=job_id)
    runtime.bus.publish(u["id"], {"type": "run", "thread_id": t, "kind": "bid", "status": "skipped"})
    return Accepted(thread_id=t, status="skipped")
