"""Intake: fetch the job, client, policy and Connects, then strip injections before any LLM sees the text."""
from __future__ import annotations

from agent.guards import strip_injections
from agent.nodes.base import Ctx, load_profile, node


@node("intake")
async def intake(state: dict, ctx: Ctx, usages: list) -> dict:
    t = ctx.tools
    job = await t.call("intake", "marketplace.get_job", {"job_id": state["job_id"]})
    client = await t.call("intake", "marketplace.get_client_history", {"client_id": job["client_id"]})
    policy = await t.call("intake", "marketplace.get_platform_policy")
    bal = await t.call("intake", "marketplace.get_connects_balance")
    clean, removed = strip_injections(f"{job['title']}\n\n{job['description']}")
    return {"job": job, "client": client, "policy": policy, "connects_balance": bal["balance"],
            "profile": load_profile(ctx, state["persona"]), "job_text_clean": clean, "injection_spans": removed,
            "status": "running"}
