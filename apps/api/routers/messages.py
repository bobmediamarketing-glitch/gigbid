"""Messages: client threads and drafting a reply (the conversation graph)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from apps.api import db
from apps.api.auth import User
from apps.api.runtime import runtime
from agent.mcp_client import ToolFailed
from apps.api.schemas import Accepted, Message, ThreadList, ThreadSummary

router = APIRouter(prefix="/api", tags=["messages"])


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
    t = await runtime.start_conversation(u["id"], thread_id, len(res["items"][0]["messages"]))
    return Accepted(thread_id=t, status="running")
