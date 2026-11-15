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

from apps.api.routers import account, auth, runs, work
from apps.api.runtime import runtime

DIST = Path(__file__).resolve().parents[1] / "web" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    await runtime.start()
    yield
    await runtime.stop()


app = FastAPI(title="GigBid API", version="0.1.0", lifespan=lifespan,
              description="Multi-agent freelancer copilot. Every write to a marketplace waits for human approval.")
for r in (auth.router, account.router, runs.router, work.router):
    app.include_router(r)


@app.get("/api/ping", tags=["health"])
def ping() -> dict:
    return {"ok": True}


if DIST.exists() and os.getenv("GIGBID_SERVE_WEB", "1") == "1":
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        f = DIST / path
        return FileResponse(f if path and f.is_file() else DIST / "index.html")
