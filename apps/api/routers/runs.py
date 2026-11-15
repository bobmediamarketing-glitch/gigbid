"""Jobs inbox, job detail, runs, approvals and the live event stream (SSE)."""
from __future__ import annotations

import asyncio
import difflib
import json
import os

from fastapi import APIRouter, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

from agent.replay import history
from agent.tools import ToolFailed
from apps.api import db
from apps.api.runtime import runtime
from apps.api.schemas import (Accepted, EditRow, HistoryRow, JobCard, JobList, RegenerateIn, RegenerateOut, ResumeIn,
                              RunSummary, RunView)
from apps.api.security import User

router = APIRouter(prefix="/api", tags=["runs"])


def _summary(row) -> RunSummary:
    s = row.summary or {}
    keep = {k: v for k, v in s.items() if k in RunSummary.model_fields}
    return RunSummary(**keep | {"thread_id": row.thread_id, "kind": row.kind, "status": row.status,
                                "updated_at": row.updated_at, "job_id": row.job_id,
                                "market_thread_id": row.market_thread_id})


def _owned(uid: int, thread: str):
    with db.engine().begin() as c:
        row = c.execute(db.select(db.runs).where(db.runs.c.thread_id == thread)).first()
    if not row or row.user_id != uid:
        raise HTTPException(404, "run not found")
    return row


def _onboarded(uid: int) -> None:
    if not db.get_settings(uid).get("onboarded"):
        raise HTTPException(409, "finish onboarding first")


# ---------------------------------------------------------------- jobs
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
    t = runtime.start_bid(u["id"], job_id)
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
    return [Accepted(thread_id=runtime.start_bid(u["id"], j["id"], j["title"]), status="running") for j in todo]


@router.post("/jobs/{job_id}/skip", response_model=Accepted)
def confirm_skip(job_id: str, u: dict = User) -> Accepted:
    """The user confirms a skip suggestion (or skips a job by hand)."""
    t = f"bid-u{u['id']}-{job_id}"
    db.upsert_run(t, u["id"], "bid", "skipped", {"skipped_by_user": True}, job_id=job_id)
    runtime.bus.publish(u["id"], {"type": "run", "thread_id": t, "kind": "bid", "status": "skipped"})
    return Accepted(thread_id=t, status="skipped")


# ---------------------------------------------------------------- runs
@router.get("/runs", response_model=list[RunSummary])
def list_runs(kind: str | None = None, status: str | None = None, u: dict = User) -> list[RunSummary]:
    q = db.select(db.runs).where(db.runs.c.user_id == u["id"])
    if kind:
        q = q.where(db.runs.c.kind == kind)
    if status:
        q = q.where(db.runs.c.status == status)
    with db.engine().begin() as c:
        return [_summary(r) for r in c.execute(q.order_by(db.runs.c.updated_at.desc()).limit(200))]


@router.get("/runs/{thread_id}", response_model=RunView)
async def run_view(thread_id: str, u: dict = User) -> RunView:
    row = _owned(u["id"], thread_id)
    g = runtime.graph(row.kind)
    cfg = {"configurable": {"thread_id": thread_id}}
    st = await g.aget_state(cfg)
    v = st.values or {}
    pending = next((it.value for t in (st.tasks or ()) for it in (getattr(t, "interrupts", ()) or ())), None)
    with db.engine().begin() as c:
        eds = c.execute(db.select(db.approvals).where(db.approvals.c.thread_id == thread_id)
                        .order_by(db.approvals.c.at)).fetchall()
    edits = [EditRow(action=e.action, note=e.note, at=e.at,
                     diff="\n".join(difflib.unified_diff((e.before or "").splitlines(), (e.after or "").splitlines(),
                                                         "draft", "your edit", lineterm="")) if e.after else None)
             for e in eds]
    trace_base = os.getenv("TRACE_URL_TEMPLATE")  # e.g. https://cloud.langfuse.com/trace/{thread_id}
    return RunView(
        thread_id=thread_id, kind=row.kind, status=row.status, pending=pending, job=v.get("job"),
        client=v.get("client"), spec=v.get("spec"), risk=v.get("risk"), fit=v.get("fit"), decision=v.get("decision"),
        quote=v.get("quote"), draft=v.get("draft"), critiques=v.get("critiques", []), compliance=v.get("compliance"),
        verification=v.get("verification"), evidence=v.get("evidence", {}), submission=v.get("submission"),
        intent=v.get("intent"), reply=v.get("reply"), client_message=v.get("client_message"), thread=v.get("thread"),
        trace=v.get("trace", []), errors=v.get("errors", []), steps=v.get("steps", 0), tokens=v.get("tokens", 0),
        usd=v.get("usd", 0.0), history=[HistoryRow(**h | {"created_at": str(h["created_at"]) if h["created_at"] else None})
                                        for h in (await history(g, cfg))[:60]],
        edits=edits, trace_url=trace_base.format(thread_id=thread_id) if trace_base else None)


@router.post("/runs/{thread_id}/resume", response_model=Accepted, status_code=202)
async def resume(thread_id: str, body: ResumeIn, u: dict = User) -> Accepted:
    row = _owned(u["id"], thread_id)
    pending = await runtime.pending(u["id"], thread_id)
    if not pending:
        raise HTTPException(409, "this run is not waiting for approval")
    if body.action == "reject" and not (body.note or "").strip():
        raise HTTPException(422, "say why you are rejecting (it feeds the analytics and future drafts)")
    edited = body.cover_letter if row.kind == "bid" else body.body
    if body.action == "edit" and not edited:
        raise HTTPException(422, "an edit needs the new text")
    before = pending.get("cover_letter") if row.kind == "bid" else pending.get("reply")
    with db.engine().begin() as c:
        c.execute(db.insert(db.approvals).values(user_id=u["id"], thread_id=thread_id, action=body.action,
                                                 note=body.note, before=before if edited else None,
                                                 after=edited, at=db.now()))
    payload = body.model_dump(exclude_none=True)
    runtime.resume(u["id"], thread_id, payload)
    return Accepted(thread_id=thread_id, status="running")


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
    out, usage = await runtime.llm.structured(
        "writer", Para, "Rewrite ONE paragraph of a freelance proposal. Keep every factual claim grounded in the "
        "EVIDENCE with [id] markers; never add facts. Return only the new paragraph. "
        + (f"Instruction: {body.instruction}" if body.instruction else ""),
        f"EVIDENCE:\n{ev}\n\nFULL DRAFT:\n{fence(pending['cover_letter_with_citations'])}\n\n"
        f"PARAGRAPH TO REWRITE:\n{paras[body.paragraph]}")
    if out is None:
        raise HTTPException(502, f"model failed: {usage.error}")
    from rag.verify import verify_text
    text, _ = verify_text(out.text, pending.get("evidence") or {})
    return RegenerateOut(paragraph=body.paragraph, text=text, model=usage.model)


# ---------------------------------------------------------------- live events
@router.get("/stream")
async def stream(request: Request, u: dict = User):
    """Server-Sent Events: node progress, run status, pipeline moves. One stream per browser tab."""
    q = runtime.bus.subscribe(u["id"])

    async def gen():
        try:
            yield {"event": "hello", "data": json.dumps({"user": u["id"]})}
            while True:
                if await request.is_disconnected():
                    break
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=15)
                    yield {"event": ev.get("type", "message"), "data": json.dumps(ev, default=str)}
                except asyncio.TimeoutError:
                    yield {"event": "ping", "data": "{}"}
        finally:
            runtime.bus.unsubscribe(u["id"], q)
    return EventSourceResponse(gen())
