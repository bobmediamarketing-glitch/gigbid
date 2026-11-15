"""Run the bid graph for one job from the terminal, over the real (stdio) MCP servers.

    python -m agent.run_bid --job j-00010 --persona ai_ml            # stops at the approval step
    python -m agent.run_bid --job j-00010 --resume approve           # same thread, approve it

Needs GigSim running (make gigsim). The thread id defaults to "<persona>-<job>", and
checkpoints go to DATABASE_URL (Postgres) or data/checkpoints.sqlite.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import uuid

from langgraph.types import Command

from agent.checkpoint import checkpointer
from agent.memory.store import memory_store
from agent.graphs.bid_graph import compile
from agent.nodes.base import Ctx
from agent.tools import connect


async def main(a) -> None:
    os.environ.setdefault("PORTFOLIO_PERSONA", a.persona)
    os.environ.setdefault("GIGSIM_TOKEN", f"gigsim-{a.persona}-token")
    thread = a.thread or f"{a.persona}-{a.job}"
    cfg = {"configurable": {"thread_id": thread}}
    async with checkpointer() as saver, memory_store() as store, connect() as tools:
        g = compile(saver, store=store)
        ctx = Ctx(tools=tools)
        if a.resume:
            out = await g.ainvoke(Command(resume={"action": a.resume}), cfg, context=ctx)
        else:
            out = await g.ainvoke({"run_id": uuid.uuid5(uuid.NAMESPACE_URL, thread).hex[:16], "job_id": a.job,
                                   "persona": a.persona}, cfg, context=ctx)
    if "__interrupt__" in out:
        req = out["__interrupt__"][0].value
        print("AWAITING APPROVAL\n")
        print(req["cover_letter"], "\n")
        print(f"bid {req['bid_amount']:g} ({req['bid_type']}), {req['connects_cost']} Connects;",
              f"critic {req['critique']['score'] if req['critique'] else '-'}")
        print(f"\nresume with: python -m agent.run_bid --job {a.job} --persona {a.persona} --resume approve|reject")
    else:
        print("status:", out.get("status"))
        for k in ("decision", "submission"):
            if out.get(k):
                v = out[k]
                print(k, json.dumps(v if isinstance(v, dict) else v.model_dump(), indent=1)[:800])
    if out.get("errors"):
        print("errors:", out["errors"])
    print("trace:", " -> ".join(f"{t['node']}({t['ms']:.0f}ms)" for t in out.get("trace", [])))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", required=True)
    ap.add_argument("--persona", default="ai_ml")
    ap.add_argument("--thread")
    ap.add_argument("--resume", choices=["approve", "reject"])
    asyncio.run(main(ap.parse_args()))
