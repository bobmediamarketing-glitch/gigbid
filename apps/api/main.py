"""GigBid API (FastAPI). Serves /api/* and, in production, the built web app from apps/web/dist.

    uvicorn apps.api.main:app --port 8000
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from apps.api import streaming
from apps.api.routers import account, analytics, approvals, auth, jobs, messages, proposals, runs
from apps.api.runtime import runtime

DIST = Path(__file__).resolve().parents[1] / "web" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    await runtime.start()
    yield
    await runtime.stop()


app = FastAPI(title="GigBid API", version="0.1.0", lifespan=lifespan,
              description="Multi-agent freelancer copilot. Every write to a marketplace waits for human approval.")
for r in (auth.router, account.router, jobs.router, runs.router, approvals.router, proposals.router, messages.router,
          analytics.router, streaming.router):
    app.include_router(r)


if os.getenv("GIGBID_EMBED_GIGSIM") == "1":
    # Single-container deployments: serve the (unmodified) simulator from this process at /gigsim and point
    # GIGSIM_BASE_URL at it. Compose runs GigSim as its own service instead.
    from gigsim.app import app as gigsim_app
    app.mount("/gigsim", gigsim_app)


@app.get("/api/ping", tags=["health"])
def ping() -> dict:
    return {"ok": True}


if DIST.exists() and os.getenv("GIGBID_SERVE_WEB", "1") == "1":
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        f = DIST / path
        return FileResponse(f if path and f.is_file() else DIST / "index.html")
