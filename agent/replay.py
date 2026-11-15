"""Replay a thread from any node (Part C6) using the checkpoint history.

    snap = await checkpoint_before(graph, cfg, "pricing")
    out  = await graph.ainvoke(None, snap.config, context=ctx)   # re-runs pricing onwards as a fork

The original history is untouched: LangGraph writes the replay as a new branch from that checkpoint,
so the run viewer can show both and an operator can compare them.
"""
from __future__ import annotations


async def checkpoint_before(graph, config: dict, node: str):
    """The most recent checkpoint whose next step is `node` (i.e. state just before it ran)."""
    async for snap in graph.aget_state_history(config):
        if node in (snap.next or ()):
            return snap
    raise LookupError(f"no checkpoint before node {node!r} in thread {config['configurable'].get('thread_id')}")


async def history(graph, config: dict) -> list[dict]:
    """Compact history for the run viewer: one row per checkpoint, newest first."""
    rows = []
    async for snap in graph.aget_state_history(config):
        rows.append({"checkpoint_id": snap.config["configurable"].get("checkpoint_id"), "next": list(snap.next or ()),
                     "step": (snap.metadata or {}).get("step"), "status": (snap.values or {}).get("status"),
                     "created_at": snap.created_at})
    return rows
