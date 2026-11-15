"""API end to end over ASGI: sign-up, onboarding, inbox, analyse, approve, pipeline, reject, memory."""
from __future__ import annotations

import asyncio
import os

os.environ["GIGBID_OFFLINE"] = "1"
os.environ["GIGBID_SYNC"] = "0"

import httpx  # noqa: E402
import pytest  # noqa: E402

from tests.integration.harness import SIM, use_inprocess_gigsim  # noqa: E402

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DATABASE_URL", f"sqlite:///{tmp_path / 'app.sqlite'}")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'ck.sqlite'}")
    monkeypatch.setenv("MEMORY_DATABASE_URL", f"sqlite:///{tmp_path / 'mem.sqlite'}")
    from mcp_servers.workspace import server as ws
    monkeypatch.setattr(ws, "DIR", tmp_path / "ws")
    from apps.api import db
    db.reset_engine()
    from apps.api.main import app
    from apps.api.runtime import runtime
    SIM.reset()
    use_inprocess_gigsim()
    await runtime.start()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c
    await runtime.stop()
    db.reset_engine()


async def onboard(c, email="sara@example.com"):
    r = await c.post("/api/auth/register", json={"email": email, "password": "correct-horse", "name": "Sara"})
    assert r.status_code == 201, r.text
    r = await c.put("/api/settings", json={"persona": "ai_ml", "gigsim_account": "ai_ml", "onboarded": True,
                                           "categories": ["LLM agent"]})
    assert r.json()["onboarded"]


async def wait_status(c, thread, want: set[str], timeout=60):
    for _ in range(timeout * 4):
        r = (await c.get(f"/api/runs/{thread}")).json()
        if r["status"] in want:
            return r
        await asyncio.sleep(0.25)
    raise AssertionError(f"{thread} stuck in {r['status']}: {r.get('errors')}")


async def test_auth_is_required_and_sessions_work(client):
    assert (await client.get("/api/jobs")).status_code == 401
    await onboard(client)
    me = (await client.get("/api/auth/me")).json()
    assert me["email"] == "sara@example.com" and me["settings"]["persona"] == "ai_ml"
    assert (await client.post("/api/auth/login", json={"email": "sara@example.com", "password": "wrong"})).status_code == 401
    assert (await client.post("/api/auth/register", json={"email": "sara@example.com", "password": "x" * 9,
                                                          "name": "dup"})).status_code == 409


async def test_inbox_analyse_approve_pipeline(client):
    await onboard(client)
    jobs = (await client.get("/api/jobs", params={"category": "LLM agent"})).json()
    assert jobs["marketplace_ok"] and jobs["items"]
    t = (await client.post("/api/jobs/j-00010/analyze")).json()["thread_id"]
    run = await wait_status(client, t, {"awaiting_approval"})
    assert run["pending"]["type"] == "approve_proposal" and run["spec"]["requirements"]
    assert run["risk"]["injection_detected"] and run["fit"]["per_requirement"] and run["history"]
    # Analysing the same job again reuses the thread (never double-analyses or double-submits).
    assert (await client.post("/api/jobs/j-00010/analyze")).json()["thread_id"] == t
    inbox = (await client.get("/api/jobs", params={"category": "LLM agent"})).json()
    card = next(i for i in inbox["items"] if i["id"] == "j-00010")
    assert card["run"]["pending"] and card["run"]["action"] == "bid"
    assert (await client.post(f"/api/runs/{t}/resume", json={"action": "approve"})).status_code == 202
    run = await wait_status(client, t, {"submitted"})
    assert run["submission"]["status"] == "submitted"
    pipe = (await client.get("/api/pipeline")).json()
    assert any(c["stage"] == "submitted" for c in pipe["cards"])
    assert (await client.post(f"/api/runs/{t}/resume", json={"action": "approve"})).status_code == 409


async def test_reject_needs_a_reason_and_edit_feeds_memory(client):
    await onboard(client)
    t = (await client.post("/api/jobs/j-00001/analyze")).json()["thread_id"]
    run = await wait_status(client, t, {"awaiting_approval"})
    assert (await client.post(f"/api/runs/{t}/resume", json={"action": "reject"})).status_code == 422
    edited = run["pending"]["cover_letter"] + " Best, Sara"
    assert (await client.post(f"/api/runs/{t}/resume", json={"action": "edit", "cover_letter": edited})).status_code == 202
    run = await wait_status(client, t, {"awaiting_approval"})
    for _ in range(40):  # the resumed run pauses again for approval of the edited text
        if run["pending"] and run["pending"]["cover_letter"].endswith("Best, Sara"):
            break
        await asyncio.sleep(0.25)
        run = (await client.get(f"/api/runs/{t}")).json()
    assert run["edits"] and run["edits"][0]["diff"] and "+" in run["edits"][0]["diff"]
    mem = (await client.get("/api/memory")).json()
    assert any(r["kind"] == "closing_line" for r in mem["style_pending"])   # staged, not yet a rule
    r = await client.post(f"/api/runs/{t}/resume", json={"action": "reject", "note": "client looks unresponsive"})
    assert r.status_code == 202
    await wait_status(client, t, {"rejected"})
    an = (await client.get("/api/analytics")).json()
    assert an["rejection_reasons"][0]["reason"] == "client looks unresponsive"


async def test_degraded_mode_keeps_analysed_jobs_visible(client):
    await onboard(client)
    t = (await client.post("/api/jobs/j-00016/analyze")).json()["thread_id"]
    await wait_status(client, t, {"skipped"})
    SIM.outage = True
    try:
        jobs = (await client.get("/api/jobs")).json()
        health = (await client.get("/api/health")).json()
    finally:
        SIM.outage = False
    assert not jobs["marketplace_ok"] and any(j["id"] == "j-00016" for j in jobs["items"])
    assert not health["marketplace_ok"]


async def test_users_are_isolated(client):
    await onboard(client)
    t = (await client.post("/api/jobs/j-00016/analyze")).json()["thread_id"]
    await wait_status(client, t, {"skipped"})
    client.cookies.clear()
    await onboard(client, "other@example.com")
    assert (await client.get(f"/api/runs/{t}")).status_code == 404
    assert (await client.get("/api/runs")).json() == []
