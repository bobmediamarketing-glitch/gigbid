"""Approvals: resume an interrupted run with approve / edit / reject (a reason is required)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from apps.api import db
from apps.api.auth import User
from apps.api.runtime import runtime
from apps.api.routers.runs import _owned
from apps.api.schemas import Accepted, ResumeIn

router = APIRouter(prefix="/api", tags=["approvals"])


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
        aid = c.execute(db.insert(db.approvals).values(user_id=u["id"], thread_id=thread_id, action=body.action,
                                                       note=body.note, before=before if edited else None,
                                                       after=edited, at=db.now())).inserted_primary_key[0]
    payload = body.model_dump(exclude_none=True)
    await runtime.resume(u["id"], thread_id, payload, approval_id=aid)  # one queue job per approval click
    return Accepted(thread_id=thread_id, status="running")
