"""Durable checkpointer for the graphs (Part C).

Postgres in production (`DATABASE_URL=postgresql://...`), SQLite for local runs and tests.
Every super-step is checkpointed, so a crashed worker resumes from the last completed node,
and the idempotency keys on marketplace writes make the resumed submit happen exactly once.
"""
from __future__ import annotations

import contextlib
import os
from pathlib import Path

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from agent.settings import ROOT

# Hand-off models are stored in checkpoints. They are allow-listed explicitly: LangGraph is moving to
# refuse unregistered types on load, which would otherwise break resume after an upgrade.
HANDOFF_TYPES = ["JobSpec", "Requirement", "RiskReport", "FitReport", "RequirementFit", "EvidenceRef", "BidDecision",
                 "PriceQuote", "ProposalDraft", "Claim", "Critique", "ComplianceVerdict", "Approval"]
SERDE = JsonPlusSerializer(allowed_msgpack_modules=[("agent.handoffs", t) for t in HANDOFF_TYPES]
                           + [("agent.conversation", t) for t in ("Intent", "ReplyDraft", "ReplyApproval")])


def memory_saver():
    """In-process checkpointer (tests, evals) with the same serializer as production."""
    from langgraph.checkpoint.memory import InMemorySaver
    return InMemorySaver(serde=SERDE)


@contextlib.asynccontextmanager
async def checkpointer(url: str | None = None):
    url = url or os.getenv("DATABASE_URL", "")
    if url.startswith("postgres"):
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        async with AsyncPostgresSaver.from_conn_string(url, serde=SERDE) as saver:
            await saver.setup()
            yield saver
    else:
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        path = url.removeprefix("sqlite:///") if url.startswith("sqlite") else str(ROOT / "data" / "checkpoints.sqlite")
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        async with AsyncSqliteSaver.from_conn_string(path) as saver:
            saver.serde = SERDE
            yield saver
