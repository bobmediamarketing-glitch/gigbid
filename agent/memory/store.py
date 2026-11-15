"""LangGraph store for long-term memory, kept apart from the checkpointer (which holds thread state)."""
from __future__ import annotations

import contextlib
import os
from pathlib import Path

from agent.settings import ROOT


@contextlib.asynccontextmanager
async def memory_store(url: str | None = None):
    url = url or os.getenv("DATABASE_URL", "")
    if url.startswith("postgres"):
        from langgraph.store.postgres.aio import AsyncPostgresStore

        async with AsyncPostgresStore.from_conn_string(url) as store:
            await store.setup()
            yield store
    else:
        from langgraph.store.sqlite.aio import AsyncSqliteStore

        path = url.removeprefix("sqlite:///") if url.startswith("sqlite") else str(ROOT / "data" / "memory.sqlite")
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        async with AsyncSqliteStore.from_conn_string(path) as store:
            await store.setup()
            yield store
