"""MCP access for agents, with per-agent allowlists (least privilege).

Agents never import servers or adapters: they call `tools.call(agent, "server.tool", args)`.
The allowlist in config decides which agent may call which tool; anything else raises
`ToolNotAllowed` before a request leaves the process. In production the sessions come from
langchain-mcp-adapters' MultiServerMCPClient (stdio or streamable HTTP per config); tests pass
in-memory sessions.
"""
from __future__ import annotations

import contextlib
import os
import re
import sys
import time
from dataclasses import dataclass, field
from typing import Any

from mcp import ClientSession

from agent.settings import ROOT, section


class ToolNotAllowed(PermissionError):
    pass


class ToolFailed(RuntimeError):
    def __init__(self, tool: str, message: str) -> None:
        super().__init__(f"{tool}: {message}")
        self.tool = tool
        m = re.search(r"\[([a-z_]+)\]", message)  # FastMCP prefixes "Error executing tool ...:"
        self.code = m.group(1) if m else "error"


@dataclass
class ToolBox:
    sessions: dict[str, ClientSession]
    allowlists: dict[str, list[str]] = field(default_factory=lambda: section("mcp").get("allowlists", {}))
    calls: list[dict] = field(default_factory=list)  # local log, surfaced in the run viewer

    def allowed(self, agent: str, tool: str) -> bool:
        return tool in self.allowlists.get(agent, [])

    async def call(self, agent: str, tool: str, args: dict | None = None) -> Any:
        if not self.allowed(agent, tool):
            raise ToolNotAllowed(f"agent {agent!r} may not call {tool!r}")
        server, name = tool.split(".", 1)
        t0 = time.perf_counter()
        res = await self.sessions[server].call_tool(name, args or {})
        ms = (time.perf_counter() - t0) * 1000
        self.calls.append({"agent": agent, "tool": tool, "ms": round(ms, 1), "error": bool(res.isError)})
        if res.isError:
            raise ToolFailed(tool, " ".join(getattr(c, "text", "") for c in res.content))
        sc = res.structuredContent or {}
        return sc["result"] if list(sc) == ["result"] else sc


def _connections() -> dict:
    conns = {}
    for name, s in section("mcp").get("servers", {}).items():
        if s.get("transport", "stdio") == "stdio":
            cmd = sys.executable if s["command"] == "python" else s["command"]
            conns[name] = {"transport": "stdio", "command": cmd, "args": s["args"], "cwd": str(ROOT),
                           "env": {**os.environ, "PYTHONPATH": str(ROOT)}}
        else:
            conns[name] = {"transport": "streamable_http", "url": s["url"],
                           "headers": {"Authorization": f"Bearer {os.getenv(s.get('token_env', ''), '')}"}}
    return conns


@contextlib.asynccontextmanager
async def connect(servers: list[str] | None = None):
    """Open one MCP session per configured server for the lifetime of a run."""
    from langchain_mcp_adapters.client import MultiServerMCPClient

    conns = _connections()
    client = MultiServerMCPClient({k: v for k, v in conns.items() if servers is None or k in servers})
    async with contextlib.AsyncExitStack() as stack:
        sessions = {}
        for name in client.connections:
            sessions[name] = await stack.enter_async_context(client.session(name))
        yield ToolBox(sessions)
