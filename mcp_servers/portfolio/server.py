"""Portfolio MCP server (Part A1): read-only access to a freelancer's evidence.

Built to be useful on its own: point it at your portfolio folder and plug it into
Claude Desktop or Cursor.

    PORTFOLIO_DIR=~/my-portfolio python -m mcp_servers.portfolio.server --stdio

Inside GigBid each caller's portfolio is resolved server-side (persona or uploaded folder),
so one deployment serves many users without mixing their evidence.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from mcp_servers.common.context import BearerAuthMiddleware, Caller, caller, load_token_table
from mcp_servers.portfolio import prompts, resources, tools
from mcp_servers.portfolio.store import PortfolioStore

ROOT = Path(__file__).resolve().parents[2]

mcp = FastMCP(
    "gigbid-portfolio",
    instructions="Read-only access to one freelancer's portfolio: CV, case studies, repos, client reviews and past "
                 "proposals with their outcomes. Use search_evidence to find proof for a job requirement and cite the "
                 "returned ids. Never claim experience these tools do not return.",
)


def _resolve_dir() -> Path:
    who = caller()
    if who.credentials.get("portfolio_dir"):
        return Path(who.credentials["portfolio_dir"])
    if who.credentials.get("persona"):
        return ROOT / "data" / "personas" / who.credentials["persona"]
    return Path(os.getenv("PORTFOLIO_DIR", ROOT / "data" / "personas" / os.getenv("PORTFOLIO_PERSONA", "ai_ml")))


store = PortfolioStore(_resolve_dir)
tools.register(mcp, store)
resources.register(mcp, store)
prompts.register(mcp)


def http_app():
    tokens = load_token_table("PORTFOLIO_MCP_TOKENS") or {
        os.getenv("PORTFOLIO_MCP_DEV_TOKEN", "dev-portfolio-token"): Caller("local", "local", {})}
    return BearerAuthMiddleware(mcp.streamable_http_app(), tokens)


def main() -> None:
    ap = argparse.ArgumentParser(description="GigBid Portfolio MCP server")
    ap.add_argument("--stdio", action="store_true", help="serve over stdio (Claude Desktop, Cursor, Inspector)")
    ap.add_argument("--dir", help="portfolio folder (overrides PORTFOLIO_DIR)")
    ap.add_argument("--port", type=int, default=int(os.getenv("PORTFOLIO_MCP_PORT", "8202")))
    a = ap.parse_args()
    if a.dir:
        os.environ["PORTFOLIO_DIR"] = a.dir
    if a.stdio:
        mcp.run("stdio")
    else:
        import uvicorn
        uvicorn.run(http_app(), host="0.0.0.0", port=a.port)


if __name__ == "__main__":
    main()
