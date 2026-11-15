"""SSE bridge: LangGraph stream updates (published by the runtime or the worker) to the browser."""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

from apps.api.auth import User
from apps.api.runtime import runtime

router = APIRouter(prefix="/api", tags=["streaming"])


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
