"""Scout: turns saved searches into new jobs to analyse. Runs on the worker's schedule (E1).

The Scout only reads (search_jobs, list_events) and hands each new job id to the bid graph,
one thread per job. It never re-hands a job it has already seen, so a worker restart cannot
double-analyse anything (the bid thread id is derived from the job id as well).
"""
from __future__ import annotations

from dataclasses import dataclass

from agent.mcp_client import ToolBox


@dataclass
class ScoutResult:
    search: str
    found: int
    new_job_ids: list[str]


async def scout(tools: ToolBox, search: dict, seen: set[str], limit: int = 10) -> ScoutResult:
    """One saved search -> the newest jobs not seen yet (at most `limit`)."""
    args = {"limit": 25}
    if search.get("category"):
        args["category"] = search["category"]
    if search.get("query"):
        args["query"] = search["query"]
    if search.get("posted_after"):
        args["posted_after"] = search["posted_after"]
    res = await tools.call("scout", "marketplace.search_jobs", args)
    items = res["items"]
    new = [j["id"] for j in items if j["id"] not in seen][:limit]
    return ScoutResult(search=search.get("name", "default"), found=len(items), new_job_ids=new)
