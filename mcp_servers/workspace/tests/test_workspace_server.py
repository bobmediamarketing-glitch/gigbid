"""Workspace MCP server through an in-memory MCP client."""
import pytest
from mcp.shared.memory import create_connected_server_and_client_session as connect

from mcp_servers.workspace import server as ws

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def tmpdir(tmp_path, monkeypatch):
    monkeypatch.setattr(ws, "DIR", tmp_path)
    ws.audit.path = tmp_path / "audit.jsonl"


async def test_slots_holds_and_drafts():
    async with connect(ws.mcp) as c:
        slots = (await c.call_tool("free_slots", {"from_date": "2026-11-16", "days": 3})).structuredContent["slots"]
        assert slots
        first = slots[0]["start"]
        h1 = (await c.call_tool("create_interview_hold", {"start": first, "duration_min": 30, "title": "Interview: Acme",
                                                          "idempotency_key": "hold-key-1"})).structuredContent
        h2 = (await c.call_tool("create_interview_hold", {"start": first, "duration_min": 30, "title": "Interview: Acme",
                                                          "idempotency_key": "hold-key-1"})).structuredContent
        assert h1["id"] == h2["id"] and h1["status"] == "tentative"
        again = (await c.call_tool("free_slots", {"from_date": "2026-11-16", "days": 3})).structuredContent["slots"]
        assert first not in {s["start"] for s in again}
        d = (await c.call_tool("create_email_draft", {"to": "client@example.com", "subject": "Interview",
                                                      "body": "Hi", "idempotency_key": "draft-key-1"})).structuredContent
        assert d["status"] == "draft"
        assert len((await c.call_tool("list_holds", {})).structuredContent["items"]) == 1
