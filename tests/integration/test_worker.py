"""Worker (Arq) end to end on an in-memory Redis: the API enqueues, a worker runs the graph, events reach the
API's SSE bus, duplicate enqueues are dropped, and scheduled scouting starts bid threads."""
from __future__ import annotations

import asyncio
import os

os.environ["GIGBID_OFFLINE"] = "1"
os.environ["GIGBID_SYNC"] = "0"

import fakeredis  # noqa: E402
import pytest  # noqa: E402
from arq.connections import ArqRedis  # noqa: E402
from arq.worker import Worker, func  # noqa: E402

from tests.integration.harness import SIM, use_inprocess_gigsim  # noqa: E402

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def env(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DATABASE_URL", f"sqlite:///{tmp_path / 'app.sqlite'}")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'ck.sqlite'}")
    monkeypatch.setenv("MEMORY_DATABASE_URL", f"sqlite:///{tmp_path / 'mem.sqlite'}")
    from mcp_servers.workspace import server as ws
    monkeypatch.setattr(ws, "DIR", tmp_path / "ws")
    from apps.api import db
    from apps.api.auth import hash_password
    db.reset_engine()
    SIM.reset()
    use_inprocess_gigsim()
    with db.engine().begin() as c:
        uid = c.execute(db.insert(db.users).values(email="w@example.com", name="W", password_hash=hash_password("x" * 10),
                                                   created_at=db.now())).inserted_primary_key[0]
    db.put_settings(uid, {"persona": "ai_ml", "gigsim_account": "ai_ml", "onboarded": True,
                          "categories": ["LLM agent"], "weekly_connects_budget": 60})
    server = fakeredis.FakeServer()
    pool = ArqRedis(connection_pool=fakeredis.aioredis.FakeRedis(server=server).connection_pool)
    from apps.api.runtime import Runtime
    api = Runtime()
    await api.start(role="api", redis=pool)
    yield api, pool, uid, db
    await api.stop()
    db.reset_engine()


async def _no_info(*_a, **_k):  # fakeredis has no INFO command; arq only logs it
    return None


async def run_worker(pool) -> None:
    import arq.worker
    arq.worker.log_redis_info = _no_info
    from worker.tasks import drive, shutdown, startup
    w = Worker(functions=[func(drive, name="drive")], redis_pool=pool, burst=True, on_startup=startup,
               handle_signals=False, poll_delay=0.05, max_jobs=4, job_timeout=120)
    await w.main()
    await shutdown(w.ctx)  # Worker.close() sends SIGUSR1, which Windows lacks; production runs on Linux


def status(db, thread):
    with db.engine().begin() as c:
        return c.execute(db.select(db.runs.c.status).where(db.runs.c.thread_id == thread)).scalar()


async def test_api_enqueues_worker_runs_and_events_reach_the_browser_bus(env):
    api, pool, uid, db = env
    inbox = api.bus.subscribe(uid)
    t = await api.start_bid(uid, "j-00010")
    assert status(db, t) == "running" and not api.tasks          # nothing ran in the API process
    assert await api.start_bid(uid, "j-00010") == t               # same job: same thread, no second job
    await run_worker(pool)
    assert status(db, t) == "awaiting_approval"
    await asyncio.sleep(0.3)  # let the relay forward the pub/sub messages
    kinds = []
    while not inbox.empty():
        kinds.append(inbox.get_nowait()["type"])
    assert "node" in kinds and "run" in kinds
    assert await api.pending(uid, t)
    await api.resume(uid, t, {"action": "approve"}, approval_id=1)
    await api.resume(uid, t, {"action": "approve"}, approval_id=1)  # double click: same job id, dropped
    await run_worker(pool)
    assert status(db, t) == "submitted"
    with db.engine().begin() as c:
        assert c.execute(db.select(db.proposals.c.proposal_id).where(db.proposals.c.user_id == uid)).fetchall().__len__() == 1


async def test_duplicate_job_ids_are_dropped_by_the_queue(env):
    api, pool, uid, db = env
    first = await pool.enqueue_job("drive", uid, "bid", "bid-x", {}, _job_id="run:bid-x")
    second = await pool.enqueue_job("drive", uid, "bid", "bid-x", {}, _job_id="run:bid-x")
    assert first is not None and second is None


async def test_scheduled_scout_starts_threads_and_respects_the_interval(env):
    api, pool, uid, db = env
    started = await api.scout_due(now=1_000_000.0)
    assert 0 < len(started) <= 5 and all(t.startswith(f"bid-u{uid}-") for t in started)
    assert await api.scout_due(now=1_000_000.0 + 60) == []        # interval not elapsed yet
    db.put_settings(uid, {"weekly_connects_budget": 0})
    assert await api.scout_due(now=1_000_000.0 + 10 * 3600) == []  # weekly Connects budget reached
