"""Bid graph end to end: real MCP servers (in memory) + in-process GigSim, rule path (no LLM keys)."""
from __future__ import annotations

import os
import uuid

os.environ["GIGBID_OFFLINE"] = "1"

import pytest  # noqa: E402
from langgraph.types import Command  # noqa: E402

from agent import settings  # noqa: E402
from agent.checkpoint import checkpointer, memory_saver  # noqa: E402
from agent.graphs.bid_graph import compile  # noqa: E402
from agent.handoffs import ProposalDraft  # noqa: E402
from agent.llm import LLM, Usage  # noqa: E402
from agent.nodes.base import Ctx  # noqa: E402
from agent.mcp_client import ToolNotAllowed  # noqa: E402
from tests.integration.harness import SIM, toolbox  # noqa: E402

pytestmark = pytest.mark.anyio
INJECTION_JOB, SCAM_JOB, PLAIN_JOB = "j-00010", "j-00016", "j-00001"


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def fresh():
    SIM.reset()
    SIM.outage = False
    yield
    SIM.outage = False


@pytest.fixture
def cfg_override(monkeypatch):
    """Patch one config value for a test without touching the file."""
    import copy
    base = copy.deepcopy(settings.config())

    def set_(path: str, value):
        d = base
        *head, last = path.split(".")
        for k in head:
            d = d[k]
        d[last] = value
        monkeypatch.setattr(settings, "config", lambda: base)
    return set_


def start(job_id: str) -> tuple[dict, dict]:
    rid = uuid.uuid4().hex[:12]
    return {"run_id": rid, "job_id": job_id, "persona": "ai_ml"}, {"configurable": {"thread_id": rid}}


async def balance(tb) -> int:
    return (await tb.call("intake", "marketplace.get_connects_balance"))["balance"]


async def test_injection_job_pauses_for_approval_then_submits_once():
    g = compile(memory_saver())
    async with toolbox() as tb:
        ctx = Ctx(tools=tb, llm=LLM(available=False))
        inp, cfg = start(INJECTION_JOB)
        b0 = await balance(tb)
        out = await g.ainvoke(inp, cfg, context=ctx)
        assert "__interrupt__" in out, out.get("errors")
        req = out["__interrupt__"][0].value
        assert out["risk"].injection_detected and out["risk"].injection_spans
        text = req["cover_letter"].lower()
        assert text.startswith("pineapple")             # legitimate read-check honoured
        assert "submit immediately" not in text and "[" not in text  # injection gone, citations stripped
        assert await balance(tb) == b0                  # nothing spent before approval
        assert {"analyst", "risk", "matcher"} <= {t["node"] for t in out["trace"]}
        out = await g.ainvoke(Command(resume={"action": "approve"}), cfg, context=ctx)
        assert out["status"] == "submitted"
        cost = req["connects_cost"]
        assert await balance(tb) == b0 - cost
        # Replaying the submit node (e.g. a retried worker) does not spend Connects again.
        from agent.nodes.approval import submit
        from types import SimpleNamespace
        await submit(await _state(g, cfg) | {"status": "running"}, SimpleNamespace(context=ctx, store=None))
        assert await balance(tb) == b0 - cost


async def _state(g, cfg) -> dict:
    return dict((await g.aget_state(cfg)).values)


async def test_scam_is_skipped_with_reason():
    g = compile(memory_saver())
    async with toolbox() as tb:
        inp, cfg = start(SCAM_JOB)
        out = await g.ainvoke(inp, cfg, context=Ctx(tools=tb, llm=LLM(available=False)))
    assert out["status"] == "skipped"
    assert out["risk"].scam_type == "free_work"
    assert any("scam" in r for r in out["decision"].reasons)
    assert "writer" not in {t["node"] for t in out["trace"]}


async def test_edit_is_rechecked_by_compliance_and_reject_spends_nothing():
    g = compile(memory_saver())
    async with toolbox() as tb:
        ctx = Ctx(tools=tb, llm=LLM(available=False))
        inp, cfg = start(PLAIN_JOB)
        b0 = await balance(tb)
        out = await g.ainvoke(inp, cfg, context=ctx)
        edited = out["__interrupt__"][0].value["cover_letter"] + " Reach me at sara.dev@example.com any time."
        out = await g.ainvoke(Command(resume={"action": "edit", "cover_letter": edited}), cfg, context=ctx)
        req = out["__interrupt__"][0].value                 # back to the human, with the redaction shown
        assert "example.com" not in req["cover_letter"]
        assert any(v["rule"] == "no_contact_details" for v in req["compliance"]["violations"])
        out = await g.ainvoke(Command(resume={"action": "reject"}), cfg, context=ctx)
        assert out["status"] == "rejected"
        assert await balance(tb) == b0


async def test_critic_loop_is_bounded(cfg_override):
    cfg_override("bid_graph.critic_pass_score", 1.01)   # nothing can pass
    g = compile(memory_saver())
    async with toolbox() as tb:
        inp, cfg = start(INJECTION_JOB)
        out = await g.ainvoke(inp, cfg, context=Ctx(tools=tb, llm=LLM(available=False)))
    assert len(out["critiques"]) == 3 and out["revisions"] == 2   # first draft + at most 2 revisions
    assert "__interrupt__" in out


async def test_step_budget_halts_the_run(cfg_override):
    cfg_override("budgets.bid.max_steps", 4)
    g = compile(memory_saver())
    async with toolbox() as tb:
        inp, cfg = start(INJECTION_JOB)
        out = await g.ainvoke(inp, cfg, context=Ctx(tools=tb, llm=LLM(available=False)))
    assert out["status"] == "needs_attention"
    assert "submission" not in out


async def test_marketplace_outage_queues_the_run():
    g = compile(memory_saver())
    async with toolbox() as tb:
        SIM.outage = True
        inp, cfg = start(PLAIN_JOB)
        out = await g.ainvoke(inp, cfg, context=Ctx(tools=tb, llm=LLM(available=False)))
    assert out["status"] == "queued"
    assert any("marketplace_unavailable" in e for e in out["errors"])


async def test_crash_during_submit_resumes_exactly_once(tmp_path):
    async with checkpointer(f"sqlite:///{tmp_path / 'ck.sqlite'}") as saver, toolbox() as tb:
        g = compile(saver)
        ctx = Ctx(tools=tb, llm=LLM(available=False))
        inp, cfg = start(INJECTION_JOB)
        b0 = await balance(tb)
        out = await g.ainvoke(inp, cfg, context=ctx)
        cost = out["__interrupt__"][0].value["connects_cost"]

        real_call = tb.call
        crashed = {"n": 0}

        async def crash_after_submit(agent, tool, args=None):
            res = await real_call(agent, tool, args)
            if tool == "marketplace.submit_proposal" and not crashed["n"]:
                crashed["n"] += 1
                raise RuntimeError("worker killed after the platform accepted the submit")
            return res
        tb.call = crash_after_submit
        with pytest.raises(RuntimeError):
            await g.ainvoke(Command(resume={"action": "approve"}), cfg, context=ctx)
        tb.call = real_call

        # A fresh graph object on the same checkpoint store, as a restarted worker would have.
        g2 = compile(saver)
        assert (await g2.aget_state(cfg)).next == ("submit",)
        out = await g2.ainvoke(None, cfg, context=ctx)
        assert out["status"] == "submitted"
        assert await balance(tb) == b0 - cost           # charged once, not twice


async def test_tool_allowlist_is_enforced():
    async with toolbox() as tb:
        with pytest.raises(ToolNotAllowed):
            await tb.call("risk", "marketplace.submit_proposal", {"proposal_id": "x", "idempotency_key": "x" * 8})
        with pytest.raises(ToolNotAllowed):
            await tb.call("writer", "marketplace.create_proposal_draft", {})


class FabricatingLLM(LLM):
    """Writer invents a metric and an evidence id; every other node falls back to rules."""

    def __init__(self):
        super().__init__(available=True)

    async def structured(self, node, schema, system, user):
        if node != "writer":
            return None, Usage()
        cl = ("Your goal is close to work I have shipped. I cut latency by 63% for a fintech client [ai_ml-cs-99]. "
              "I also built agents with langgraph, redis, docker and fastapi, and I have 12 years of experience. "
              "In week one I would review your setup and ship a first slice. Would a short call suit you?")
        return ProposalDraft(job_id="x", cover_letter=cl), Usage(model="fake", tokens_in=1000, tokens_out=200)


async def test_fabricated_claims_are_removed_before_the_human_sees_them():
    g = compile(memory_saver())
    async with toolbox() as tb:
        inp, cfg = start(INJECTION_JOB)
        out = await g.ainvoke(inp, cfg, context=Ctx(tools=tb, llm=FabricatingLLM()))
    text = out["draft"].cover_letter
    assert "63%" not in text and "12 years" not in text
    reasons = " ".join(r["reason"] for r in out["verification"]["removed"])
    assert "unknown evidence" in reasons and "not in any evidence" in reasons
    assert out["tokens"] >= 1200                         # usage from the model is counted against the budget
