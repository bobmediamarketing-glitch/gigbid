"""Runs: list, full view from the checkpoint (state, trace, history, edits)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from apps.api import db
from apps.api.auth import User
from apps.api.runtime import runtime
import difflib

from agent import tracing
from agent.replay import history
from apps.api.routers.jobs import _summary
from apps.api.schemas import EditRow, HistoryRow, RunSummary, RunView

router = APIRouter(prefix="/api", tags=["runs"])


def _owned(uid: int, thread: str):
    with db.engine().begin() as c:
        row = c.execute(db.select(db.runs).where(db.runs.c.thread_id == thread)).first()
    if not row or row.user_id != uid:
        raise HTTPException(404, "run not found")
    return row


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
    return RunView(
        thread_id=thread_id, kind=row.kind, status=row.status, pending=pending, job=v.get("job"),
        client=v.get("client"), spec=v.get("spec"), risk=v.get("risk"), fit=v.get("fit"), decision=v.get("decision"),
        quote=v.get("quote"), draft=v.get("draft"), critiques=v.get("critiques", []), compliance=v.get("compliance"),
        verification=v.get("verification"), evidence=v.get("evidence", {}), submission=v.get("submission"),
        intent=v.get("intent"), reply=v.get("reply"), client_message=v.get("client_message"), thread=v.get("thread"),
        trace=v.get("trace", []), errors=v.get("errors", []), steps=v.get("steps", 0), tokens=v.get("tokens", 0),
        usd=v.get("usd", 0.0), history=[HistoryRow(**h | {"created_at": str(h["created_at"]) if h["created_at"] else None})
                                        for h in (await history(g, cfg))[:60]],
        edits=edits, trace_url=tracing.trace_url(thread_id))
