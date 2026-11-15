"""Marketplace MCP server through an in-memory MCP client, with GigSim running in-process."""
import json
import os

os.environ["GIGSIM_ERROR_RATE"] = "0"
os.environ.setdefault("GIGSIM_STATE_FILE", os.path.join(os.path.dirname(__file__), ".gigsim_test_state.json"))

import httpx  # noqa: E402
import pytest  # noqa: E402
from mcp.shared.memory import create_connected_server_and_client_session as connect  # noqa: E402

from gigsim.app import SIM, app as gigsim_app  # noqa: E402
from mcp_servers.marketplace import server as mk  # noqa: E402
from mcp_servers.marketplace.adapters.gigsim import GigSimAdapter  # noqa: E402

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def fresh(tmp_path):
    SIM.reset()
    SIM.outage = False
    mk.audit.path = tmp_path / "audit.jsonl"
    mk.set_port_factory(lambda who: GigSimAdapter("http://gigsim", who.credentials["gigsim_token"],
                                                  transport=httpx.ASGITransport(app=gigsim_app),
                                                  max_retries=1, backoff_base=0.01))
    yield


def data(res):
    assert not res.isError, res.content
    return res.structuredContent


async def test_tool_surface_and_annotations():
    async with connect(mk.mcp) as c:
        tools = {t.name: t for t in (await c.list_tools()).tools}
    assert {"search_jobs", "get_job", "get_client_history", "get_connects_balance", "list_messages",
            "create_proposal_draft", "submit_proposal", "send_message"} <= set(tools)
    assert tools["search_jobs"].annotations.readOnlyHint is True
    assert tools["submit_proposal"].annotations.destructiveHint is True
    assert tools["create_proposal_draft"].annotations.destructiveHint is False
    for t in tools.values():
        assert t.outputSchema, f"{t.name} has no output schema"
    assert "idempotency_key" in tools["submit_proposal"].inputSchema["required"]


async def test_draft_dry_run_submit_exactly_once():
    async with connect(mk.mcp) as c:
        job = data(await c.call_tool("search_jobs", {"category": "RAG chatbot", "limit": 1}))["items"][0]
        bal0 = data(await c.call_tool("get_connects_balance", {}))["balance"]
        args = {"job_id": job["id"], "cover_letter": "Grounded proposal text. " * 10,
                "bid_amount": job["budget"]["max"], "bid_type": job["budget"]["type"], "idempotency_key": "draft-0001"}
        prev = data(await c.call_tool("create_proposal_draft", args | {"dry_run": True}))
        assert prev["dry_run"] and prev["preview"]["payload"]["job_id"] == job["id"]
        d1 = data(await c.call_tool("create_proposal_draft", args))["proposal"]
        d2 = data(await c.call_tool("create_proposal_draft", args))["proposal"]
        assert d1["id"] == d2["id"]
        sp = data(await c.call_tool("submit_proposal", {"proposal_id": d1["id"], "idempotency_key": "submit-0001",
                                                       "dry_run": True}))
        assert sp["preview"]["connects_cost"] == job["connects_cost"]
        for _ in range(3):  # retried submit with the same key
            data(await c.call_tool("submit_proposal", {"proposal_id": d1["id"], "idempotency_key": "submit-0001"}))
        bal1 = data(await c.call_tool("get_connects_balance", {}))["balance"]
    assert bal0 - bal1 == job["connects_cost"]
    rows = [json.loads(x) for x in mk.audit.path.read_text().splitlines()]
    assert sum(r["tool"] == "submit_proposal" and r["status"] == "ok" for r in rows) == 4


async def test_input_constraints_rejected():
    async with connect(mk.mcp) as c:
        r = await c.call_tool("create_proposal_draft", {"job_id": "j-00001", "cover_letter": "too short",
                                                        "bid_amount": -5, "bid_type": "fixed", "idempotency_key": "x"})
    assert r.isError


async def test_outage_reports_unavailable_code():
    SIM.outage = True
    async with connect(mk.mcp) as c:
        r = await c.call_tool("search_jobs", {"limit": 1})
        h = data(await c.call_tool("marketplace_health", {}))
    assert r.isError and "[marketplace_unavailable]" in r.content[0].text
    assert h["available"] is False


async def test_audit_masks_pii():
    async with connect(mk.mcp) as c:
        await c.call_tool("send_message", {"thread_id": "t-none", "body": "mail me at a.b@example.com or +92 300 1234567",
                                           "idempotency_key": "msg-00001"})
    row = json.loads(mk.audit.path.read_text().splitlines()[-1])
    assert "example.com" not in json.dumps(row) and "1234567" not in json.dumps(row)
