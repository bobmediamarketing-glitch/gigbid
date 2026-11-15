"""In-process harness: GigSim + the three MCP servers over in-memory MCP sessions.

Used by graph tests and evals so a full bid run needs no network, no subprocesses and no keys.
"""
from __future__ import annotations

import contextlib
import os
from pathlib import Path

os.environ.setdefault("GIGSIM_ERROR_RATE", "0")
os.environ.setdefault("GIGSIM_STATE_FILE", str(Path(__file__).with_name(".gigsim_test_state.json")))

import httpx  # noqa: E402
from mcp.shared.memory import create_connected_server_and_client_session as connect  # noqa: E402

from agent.tools import ToolBox  # noqa: E402
from gigsim.app import SIM, _buckets, app as gigsim_app  # noqa: E402
from mcp_servers.marketplace import server as mk  # noqa: E402
from mcp_servers.marketplace.adapters.gigsim import GigSimAdapter  # noqa: E402
from mcp_servers.portfolio import server as pf  # noqa: E402
from mcp_servers.workspace import server as ws  # noqa: E402


def use_inprocess_gigsim(audit_dir: Path | None = None) -> None:
    if audit_dir:
        mk.audit.path = audit_dir / "marketplace.jsonl"
    mk.set_port_factory(lambda who: GigSimAdapter("http://gigsim", who.credentials["gigsim_token"],
                                                  transport=httpx.ASGITransport(app=gigsim_app),
                                                  max_retries=1, backoff_base=0.01))


def lift_rate_limits() -> None:
    """Eval runs only: lift GigSim's and the server's politeness limits (in memory) so latency
    numbers measure the agents, not deliberate waiting. Production keeps both limits."""
    from mcp_servers.common.ratelimit import PoliteLimiter
    mk.limiter = PoliteLimiter(requests=100_000, per_seconds=1, max_wait_s=1)
    SIM.policy["rate_limit"] = {"requests": 100_000, "per_seconds": 1}


@contextlib.asynccontextmanager
async def toolbox(persona: str = "ai_ml"):
    os.environ["PORTFOLIO_PERSONA"] = persona
    os.environ["GIGSIM_TOKEN"] = f"gigsim-{persona}-token"
    use_inprocess_gigsim()
    _buckets.clear()
    async with contextlib.AsyncExitStack() as st:
        sessions = {"marketplace": await st.enter_async_context(connect(mk.mcp)),
                    "portfolio": await st.enter_async_context(connect(pf.mcp)),
                    "workspace": await st.enter_async_context(connect(ws.mcp))}
        yield ToolBox(sessions)


__all__ = ["SIM", "lift_rate_limits", "toolbox", "use_inprocess_gigsim"]
