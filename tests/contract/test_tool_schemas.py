"""Schema snapshot test: fails when an MCP tool signature changes unintentionally.

After an intentional change, regenerate with:  UPDATE_SNAPSHOTS=1 pytest tests/contract
"""
import json
import os
from pathlib import Path

import pytest
from mcp.shared.memory import create_connected_server_and_client_session as connect

from mcp_servers.marketplace.server import mcp as marketplace
from mcp_servers.portfolio.server import mcp as portfolio
from mcp_servers.workspace.server import mcp as workspace

SNAP = Path(__file__).parent / "snapshots"
pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def surface(server) -> dict:
    async with connect(server) as c:
        tools = (await c.list_tools()).tools
    return {t.name: {"description": t.description, "input": t.inputSchema, "output": t.outputSchema,
                     "annotations": t.annotations.model_dump(exclude_none=True) if t.annotations else None}
            for t in sorted(tools, key=lambda t: t.name)}


@pytest.mark.parametrize("name,server", [("marketplace", marketplace), ("portfolio", portfolio),
                                         ("workspace", workspace)])
async def test_tool_schema_snapshot(name, server):
    current = await surface(server)
    path = SNAP / f"{name}.json"
    if os.getenv("UPDATE_SNAPSHOTS") or not path.exists():
        path.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        pytest.skip(f"snapshot written: {path.name}")
    expected = json.loads(path.read_text(encoding="utf-8"))
    changed = sorted(k for k in set(current) | set(expected) if current.get(k) != expected.get(k))
    assert not changed, f"tool schemas changed: {changed}. If intended, run UPDATE_SNAPSHOTS=1 pytest tests/contract"
