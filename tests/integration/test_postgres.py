"""The production storage path on a real Postgres (embedded via `pgserver`; skipped if it is not installed):
the Postgres checkpointer resumes a crashed submit exactly once, the memory store promotes style rules, and the
app tables work through SQLAlchemy + psycopg."""
from __future__ import annotations

import asyncio
import os
import sys
import uuid

os.environ["GIGBID_OFFLINE"] = "1"

import pytest  # noqa: E402

pgserver = pytest.importorskip("pgserver")

from langgraph.types import Command  # noqa: E402

from agent.checkpoint import checkpointer  # noqa: E402
from agent.graphs.bid_graph import compile  # noqa: E402
from agent.llm import LLM  # noqa: E402
from agent.memory import style  # noqa: E402
from agent.memory.store import memory_store  # noqa: E402
from agent.nodes.base import Ctx  # noqa: E402
from tests.integration.harness import SIM, toolbox  # noqa: E402

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    # psycopg's async driver needs a selector loop on Windows (the default Proactor loop is unsupported).
    if sys.platform == "win32":
        return ("asyncio", {"loop_factory": asyncio.SelectorEventLoop})
    return "asyncio"


@pytest.fixture(scope="module")
def pg_url(tmp_path_factory):
    srv = pgserver.get_server(str(tmp_path_factory.mktemp("pg")), cleanup_mode="stop")
    yield srv.get_uri()


async def test_crash_resume_exactly_once_on_postgres(pg_url):
    SIM.reset()
    async with checkpointer(pg_url) as saver, memory_store(pg_url) as store, toolbox() as tb:
        g = compile(saver, store=store)
        ctx = Ctx(tools=tb, llm=LLM(available=False))
        rid = uuid.uuid4().hex[:12]
        cfg = {"configurable": {"thread_id": rid}}
        bal = lambda: tb.call("intake", "marketplace.get_connects_balance")  # noqa: E731
        b0 = (await bal())["balance"]
        out = await g.ainvoke({"run_id": rid, "job_id": "j-00010", "persona": "ai_ml", "user_id": "pg"}, cfg, context=ctx)
        cost = out["__interrupt__"][0].value["connects_cost"]
        real, crashed = tb.call, {"n": 0}

        async def crash_after_submit(agent, tool, args=None):
            res = await real(agent, tool, args)
            if tool == "marketplace.submit_proposal" and not crashed["n"]:
                crashed["n"] = 1
                raise RuntimeError("worker killed after the platform accepted the submit")
            return res
        tb.call = crash_after_submit
        with pytest.raises(RuntimeError):
            await g.ainvoke(Command(resume={"action": "approve"}), cfg, context=ctx)
        tb.call = real
        g2 = compile(saver, store=store)   # a restarted worker: fresh graph, same Postgres
        assert (await g2.aget_state(cfg)).next == ("submit",)
        out = await g2.ainvoke(None, cfg, context=ctx)
        assert out["status"] == "submitted" and (await bal())["balance"] == b0 - cost
        assert len([s async for s in g2.aget_state_history(cfg)]) > 10   # replayable history in Postgres
        # outcome features were staged in the Postgres memory store at submit
        assert await store.aget(("proposal_features", "pg"), out["submission"]["id"])


async def test_style_memory_on_postgres(pg_url):
    async with memory_store(pg_url) as store:
        for _ in range(2):
            await style.record_edit(store, "pg-user", "Your goal is clear. I ship fast.",
                                    "Your goal is clear. I ship fast. Best, Sara")
        assert [r["kind"] for r in await style.rules(store, "pg-user")] == ["closing_line"]


def test_app_tables_on_postgres(pg_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", pg_url)
    monkeypatch.delenv("APP_DATABASE_URL", raising=False)
    from apps.api import db
    db.reset_engine()
    try:
        with db.engine().begin() as c:
            uid = c.execute(db.insert(db.users).values(email=f"{uuid.uuid4().hex[:6]}@example.com", name="P",
                                                       password_hash="x", created_at=db.now())).inserted_primary_key[0]
        db.put_settings(uid, {"persona": "ai_ml", "onboarded": True})
        db.upsert_run("t-pg", uid, "bid", "running", {"title": "x"}, job_id="j-1")
        db.upsert_run("t-pg", uid, "bid", "submitted", {"price": 100})
        assert db.get_settings(uid)["persona"] == "ai_ml"
        with db.engine().begin() as c:
            row = c.execute(db.select(db.runs).where(db.runs.c.thread_id == "t-pg")).first()
        assert row.status == "submitted" and row.summary == {"title": "x", "price": 100}
    finally:
        db.reset_engine()
