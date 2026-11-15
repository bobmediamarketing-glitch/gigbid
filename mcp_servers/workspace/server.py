"""Workspace MCP server (Part A3): free calendar slots, tentative interview holds, email drafts.

Backed by a local mock (one JSON file per user under WORKSPACE_DIR). The agent sees only
MCP tools, so swapping in Google Calendar / Gmail later changes this file, not the graph.
Nothing here sends email: drafts only.
"""
from __future__ import annotations

import argparse
import json
import os
import threading
import uuid
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from mcp_servers.common.audit import AuditLog
from mcp_servers.common.context import BearerAuthMiddleware, Caller, caller, load_token_table

ROOT = Path(__file__).resolve().parents[2]
DIR = Path(os.getenv("WORKSPACE_DIR", ROOT / "data" / "workspace"))
audit = AuditLog(os.getenv("WORKSPACE_AUDIT_LOG", ROOT / "data" / "audit" / "workspace.jsonl"))
_lock = threading.Lock()

mcp = FastMCP("gigbid-workspace", instructions="The freelancer's calendar and email drafts. Holds are tentative "
                                               "and drafts are never sent automatically.")

DEFAULT_PREFS = {"timezone": "Asia/Karachi", "work_start": "10:00", "work_end": "18:00", "work_days": [0, 1, 2, 3, 4],
                 "buffer_min": 15}


def _path() -> Path:
    return DIR / f"{caller().tenant}__{caller().user_id}.json"


def _load() -> dict:
    p = _path()
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {"prefs": DEFAULT_PREFS, "events": [], "drafts": [], "idem": {}}


def _save(d: dict) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=1), encoding="utf-8")
    tmp.replace(p)


class Slot(BaseModel):
    start: str
    end: str
    timezone: str


class SlotList(BaseModel):
    timezone: str
    slots: list[Slot]


class Hold(BaseModel):
    id: str
    title: str
    start: str
    end: str
    status: str
    thread_id: str | None = None


class EmailDraft(BaseModel):
    id: str
    to: str
    subject: str
    body: str
    status: str


IdemKey = Annotated[str, Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9:_\-]+$")]


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False))
def free_slots(
    from_date: Annotated[str | None, Field(description="ISO date to start from; default tomorrow")] = None,
    days: Annotated[int, Field(ge=1, le=14)] = 5,
    duration_min: Annotated[int, Field(ge=15, le=180)] = 30,
    max_slots: Annotated[int, Field(ge=1, le=20)] = 6,
) -> SlotList:
    """Free interview slots inside working hours, avoiding existing events and holds."""
    d = _load()
    pr = d["prefs"]
    tz = ZoneInfo(pr["timezone"])
    start_day = date.fromisoformat(from_date) if from_date else (datetime.now(tz).date() + timedelta(days=1))
    busy = [(datetime.fromisoformat(e["start"]), datetime.fromisoformat(e["end"])) for e in d["events"]
            if e["status"] != "cancelled"]
    buf, dur = timedelta(minutes=pr["buffer_min"]), timedelta(minutes=duration_min)
    ws, we = time.fromisoformat(pr["work_start"]), time.fromisoformat(pr["work_end"])
    out: list[Slot] = []
    for i in range(days):
        day = start_day + timedelta(days=i)
        if day.weekday() not in pr["work_days"]:
            continue
        t, end = datetime.combine(day, ws, tz), datetime.combine(day, we, tz)
        while t + dur <= end and len(out) < max_slots:
            if all(t + dur + buf <= b0 or t >= b1 + buf for b0, b1 in busy):
                out.append(Slot(start=t.isoformat(), end=(t + dur).isoformat(), timezone=pr["timezone"]))
                t += dur + timedelta(hours=2)  # spread suggestions across the day
            else:
                t += timedelta(minutes=30)
    audit.record("workspace", "free_slots", {"from_date": from_date, "days": days}, status="ok",
                 result={"count": len(out)})
    return SlotList(timezone=pr["timezone"], slots=out)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False))
def create_interview_hold(
    start: Annotated[str, Field(description="ISO datetime with offset")],
    duration_min: Annotated[int, Field(ge=15, le=180)],
    title: Annotated[str, Field(min_length=3, max_length=120)],
    idempotency_key: IdemKey,
    thread_id: Annotated[str | None, Field(max_length=64)] = None,
) -> Hold:
    """Put a TENTATIVE hold on the calendar for a proposed interview. Does not invite anyone."""
    with _lock:
        d = _load()
        if idempotency_key in d["idem"]:
            return Hold(**d["idem"][idempotency_key])
        s = datetime.fromisoformat(start)
        if s.tzinfo is None:
            raise ToolError("[invalid] start must include a timezone offset")
        h = {"id": f"hold-{uuid.uuid4().hex[:8]}", "title": title, "start": s.isoformat(),
             "end": (s + timedelta(minutes=duration_min)).isoformat(), "status": "tentative", "thread_id": thread_id}
        d["events"].append(h)
        d["idem"][idempotency_key] = h
        _save(d)
    audit.record("workspace", "create_interview_hold", {"start": start, "title": title}, status="ok", result=h)
    return Hold(**h)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False))
def create_email_draft(
    to: Annotated[str, Field(min_length=3, max_length=200)],
    subject: Annotated[str, Field(min_length=1, max_length=200)],
    body: Annotated[str, Field(min_length=1, max_length=8000)],
    idempotency_key: IdemKey,
) -> EmailDraft:
    """Save an email DRAFT for the freelancer to review and send themselves. Never sends."""
    with _lock:
        d = _load()
        if idempotency_key in d["idem"]:
            return EmailDraft(**d["idem"][idempotency_key])
        e = {"id": f"draft-{uuid.uuid4().hex[:8]}", "to": to, "subject": subject, "body": body, "status": "draft"}
        d["drafts"].append(e)
        d["idem"][idempotency_key] = e
        _save(d)
    audit.record("workspace", "create_email_draft", {"to": to, "subject": subject}, status="ok", result={"id": e["id"]})
    return EmailDraft(**e)


class HoldList(BaseModel):
    items: list[Hold]


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False))
def list_holds() -> HoldList:
    """Tentative interview holds currently on the calendar."""
    return HoldList(items=[Hold(**e) for e in _load()["events"] if e["status"] == "tentative"])


def http_app():
    tokens = load_token_table("WORKSPACE_MCP_TOKENS") or {
        os.getenv("WORKSPACE_MCP_DEV_TOKEN", "dev-workspace-token"): Caller("local", "local", {})}
    return BearerAuthMiddleware(mcp.streamable_http_app(), tokens)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--stdio", action="store_true")
    ap.add_argument("--port", type=int, default=int(os.getenv("WORKSPACE_MCP_PORT", "8203")))
    a = ap.parse_args()
    if a.stdio:
        mcp.run("stdio")
    else:
        import uvicorn
        uvicorn.run(http_app(), host="0.0.0.0", port=a.port)
