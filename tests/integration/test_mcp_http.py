"""MCP servers as separate HTTP services (the docker-compose topology), without Docker:
GigSim + three MCP servers as real processes; the bid graph talks to them over Streamable HTTP with a signed
per-user token, exactly as the API and worker do in compose."""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx
import pytest

from agent.checkpoint import memory_saver
from agent.graphs.bid_graph import compile
from agent.llm import LLM
from agent.mcp_client import connect_http
from agent.nodes.base import Ctx
from mcp_servers.common.context import Caller

pytestmark = pytest.mark.anyio
ROOT = Path(__file__).resolve().parents[2]
SECRET = "test-caller-secret-" + "x" * 20


@pytest.fixture
def anyio_backend():
    return "asyncio"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def services(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("http")
    ports = {k: free_port() for k in ("gigsim", "marketplace", "portfolio", "workspace")}
    env = {**os.environ, "PYTHONPATH": str(ROOT), "MCP_CALLER_SECRET": SECRET, "GIGSIM_ERROR_RATE": "0",
           "GIGSIM_STATE_FILE": str(tmp / "gs.json"), "GIGSIM_BASE_URL": f"http://127.0.0.1:{ports['gigsim']}",
           "WORKSPACE_DIR": str(tmp / "ws"), "MARKETPLACE_AUDIT_LOG": str(tmp / "audit.jsonl")}
    cmds = {"gigsim": [sys.executable, "-m", "uvicorn", "gigsim.app:app", "--port", str(ports["gigsim"])],
            **{k: [sys.executable, "-m", f"mcp_servers.{k}.server", "--port", str(ports[k])]
               for k in ("marketplace", "portfolio", "workspace")}}
    procs = [subprocess.Popen(c, cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
             for c in cmds.values()]
    deadline = time.time() + 60
    for k, port in ports.items():
        while True:
            try:
                httpx.get(f"http://127.0.0.1:{port}/" + ("health" if k == "gigsim" else "mcp"), timeout=1)
                break
            except httpx.HTTPError:
                if time.time() > deadline:
                    raise RuntimeError(f"{k} did not start")
                time.sleep(0.3)
    urls = {k: f"http://127.0.0.1:{p}/mcp" for k, p in ports.items() if k != "gigsim"}
    yield urls, tmp
    for p in procs:
        p.terminate()
    for p in procs:
        p.wait(timeout=10)


def set_urls(monkeypatch, urls):
    monkeypatch.setenv("MCP_CALLER_SECRET", SECRET)
    monkeypatch.setenv("MCP_MARKETPLACE_URL", urls["marketplace"])
    monkeypatch.setenv("MCP_PORTFOLIO_URL", urls["portfolio"])
    monkeypatch.setenv("MCP_WORKSPACE_URL", urls["workspace"])


async def test_unsigned_and_forged_tokens_are_rejected(services):
    urls, _ = services
    async with httpx.AsyncClient() as c:
        r = await c.post(urls["marketplace"], json={})
        assert r.status_code == 401
        r = await c.post(urls["marketplace"], json={}, headers={"Authorization": "Bearer a.b.c"})
        assert r.status_code == 401


async def test_bid_graph_runs_over_http_with_a_signed_user_token(services, monkeypatch):
    urls, tmp = services
    set_urls(monkeypatch, urls)
    who = Caller("u7-ai_ml", "gigbid", {"gigsim_token": "gigsim-ai_ml-token", "persona": "ai_ml"})
    rid = uuid.uuid4().hex[:12]
    async with connect_http(who, trace_id="trace-http-1") as tb:
        g = compile(memory_saver())
        out = await g.ainvoke({"run_id": rid, "job_id": "j-00010", "persona": "ai_ml"},
                              {"configurable": {"thread_id": rid}}, context=Ctx(tools=tb, llm=LLM(available=False)))
    assert "__interrupt__" in out, out.get("errors")
    assert out["fit"].per_requirement and out["risk"].injection_detected
    # The marketplace server attributed every call to the signed user and the trace id we sent.
    rows = (tmp / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    assert rows and all('"u7-ai_ml"' in r for r in rows) and any('"trace-http-1"' in r for r in rows)
