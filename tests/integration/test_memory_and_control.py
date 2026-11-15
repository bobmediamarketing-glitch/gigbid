"""Long-term memory (style + outcome), autonomy, watch, dead-letter and replay-from-any-node."""
from __future__ import annotations

import os
import uuid

os.environ["GIGBID_OFFLINE"] = "1"

import httpx  # noqa: E402
import pytest  # noqa: E402
from langgraph.store.memory import InMemoryStore  # noqa: E402
from langgraph.types import Command  # noqa: E402

from agent.checkpoint import memory_saver  # noqa: E402
from agent.graphs.bid_graph import compile  # noqa: E402
from agent.handoffs import FitReport, JobSpec, RiskReport  # noqa: E402
from agent.llm import LLM  # noqa: E402
from agent.memory import outcomes, style  # noqa: E402
from agent.nodes.base import Ctx  # noqa: E402
from agent.nodes.decide import decide_rules  # noqa: E402
from agent.nodes.pricing import quote  # noqa: E402
from agent.replay import checkpoint_before, history  # noqa: E402
from tests.integration.harness import SIM, toolbox  # noqa: E402

pytestmark = pytest.mark.anyio
BID_JOBS = ["j-00010", "j-00001", "j-00002", "j-00003"]


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def fresh():
    SIM.reset()
    yield


def start(job_id, **extra):
    rid = uuid.uuid4().hex[:12]
    return {"run_id": rid, "job_id": job_id, "persona": "ai_ml", "user_id": "u1", **extra}, \
        {"configurable": {"thread_id": rid}}


# ---------------------------------------------------------------- style memory
async def test_style_rule_is_promoted_after_two_edits_and_applied_to_the_next_draft():
    store = InMemoryStore()
    g = compile(memory_saver(), store=store)
    async with toolbox() as tb:
        ctx = Ctx(tools=tb, llm=LLM(available=False))
        for job in BID_JOBS[:2]:  # the user cuts the generic second sentence ("You want ...") twice
            inp, cfg = start(job)
            out = await g.ainvoke(inp, cfg, context=ctx)
            text = out["__interrupt__"][0].value["cover_letter"]
            edited = text.replace("and that is the kind of system I build and hand over", "and I have built this before")
            edited = edited.replace("Would a short call this week to confirm the scope suit you?",
                                    "Happy to share a one-page plan.")
            out = await g.ainvoke(Command(resume={"action": "edit", "cover_letter": edited}), cfg, context=ctx)
            await g.ainvoke(Command(resume={"action": "approve"}), cfg, context=ctx)
        rules = await style.rules(store, "u1")
        kinds = {r["kind"] for r in rules}
        assert "closing_line" in kinds, rules          # same closing line added in two separate edits
        inp, cfg = start(BID_JOBS[2])
        out = await g.ainvoke(inp, cfg, context=ctx)
        assert out["__interrupt__"][0].value["cover_letter"].rstrip().endswith("Happy to share a one-page plan.")
        assert any("memory:" in t.get("note", "") for t in out["trace"])
        # The user deletes the rule in the memory viewer: it stops applying and is not re-learned.
        for r in rules:
            await style.forget(store, "u1", r["key"])
        assert await style.rules(store, "u1") == []


def test_observe_ignores_single_word_noise_and_whole_sentence_rewrites():
    assert style.observe("Your goal is clear. I ship fast.", "Your goal is clear. I ship fast.") == []
    obs = style.observe("I am passionate about data. Your goal is a dashboard. I built one in dbt.",
                        "Your goal is a dashboard. I built one in dbt.")
    assert [o["kind"] for o in obs] == ["cut_first_sentence"]


# ---------------------------------------------------------------- outcome memory
async def test_outcome_memory_promotes_only_with_enough_evidence_and_steers_pricing():
    store = InMemoryStore()
    feats = lambda pos: {"category": "RAG chatbot", "price_position": pos, "length": "medium",  # noqa: E731
                         "opens_with_read_check": False, "evidence_types": "cs", "job_id": "j"}
    plan = [("p25_p50", "client_replied")] * 4 + [("p50_p75", "proposal_lost")] * 4
    for i, (pos, ev) in enumerate(plan):
        await outcomes.stage_submission(store, "u1", f"p-{i}", feats(pos))
    assert await outcomes.promote(store, "u1") == {}           # nothing resolved yet: nothing remembered
    await outcomes.ingest_events(store, "u1", [{"type": ev, "proposal_id": f"p-{i}"} for i, (_, ev) in enumerate(plan)]
                                 + [{"type": "client_replied", "proposal_id": "not-ours"}])
    mem = await outcomes.promote(store, "u1")
    entry = mem["RAG chatbot"]
    assert entry["n"] == 8 and entry["reply_rate"] == 0.5
    assert {"feature": "price_position", "value": "p25_p50", "reply_rate": 1.0, "n": 4} in entry["lessons"]
    assert outcomes.price_hint(entry) == "p25_p50"
    spec = JobSpec(job_id="j", goal="g", requirements=[], budget_type="fixed", budget_min=100, budget_max=9000,
                   category="RAG chatbot")
    stats = [{"budget_type": "fixed", "p25": 1000, "p50": 2000, "p75": 3000}]
    prof = {"fixed_floor": 400, "hourly_floor": 30}
    assert quote(spec, stats, prof, 6).amount == 2000
    q = quote(spec, stats, prof, 6, outcomes.price_hint(entry))
    assert q.amount == 1000 and "outcome memory" in q.rationale


async def test_submitted_proposal_is_staged_and_learns_from_gigsim_events():
    store = InMemoryStore()
    g = compile(memory_saver(), store=store)
    async with toolbox() as tb:
        ctx = Ctx(tools=tb, llm=LLM(available=False))
        inp, cfg = start(BID_JOBS[0])
        await g.ainvoke(inp, cfg, context=ctx)
        out = await g.ainvoke(Command(resume={"action": "approve"}), cfg, context=ctx)
        pid = out["submission"]["id"]
        staged = await store.aget(("proposal_features", "u1"), pid)
        assert staged and staged.value["outcome"] is None and "cover_letter" not in staged.value  # features only
        SIM.offset_sim_s += 80 * 3600
        SIM.process_due()
        ev = await tb.call("scout", "marketplace.list_events", {"after_id": 0})
        await outcomes.ingest_events(store, "u1", ev["items"])
        assert (await store.aget(("proposal_features", "u1"), pid)).value["outcome"] is not None


# ---------------------------------------------------------------- autonomy, watch
async def test_low_fit_skip_waits_for_the_user_unless_auto_skip_is_on():
    g = compile(memory_saver())
    async with toolbox() as tb:
        ctx = Ctx(tools=tb, llm=LLM(available=False))
        inp, cfg = start("j-00005")
        assert (await g.ainvoke(inp, cfg, context=ctx))["status"] == "skip_suggested"
        inp, cfg = start("j-00005", autonomy="auto_skip")
        assert (await g.ainvoke(inp, cfg, context=ctx))["status"] == "skipped"
        inp, cfg = start("j-00016")  # scams close regardless of autonomy
        assert (await g.ainvoke(inp, cfg, context=ctx))["status"] == "skipped"


def test_close_call_is_watched_not_skipped():
    spec = JobSpec(job_id="j", goal="g", requirements=[], budget_type="fixed", budget_min=500, budget_max=2000,
                   category="RAG chatbot")
    state = {"spec": spec, "job": {"id": "j", "category": "RAG chatbot", "connects_cost": 4},
             "risk": RiskReport(job_id="j", scam_score=0.1), "connects_balance": 80,
             "fit": FitReport(job_id="j", coverage=0.4, per_requirement=[], in_domain=True),
             "profile": {"fixed_floor": 400, "hourly_floor": 30}}
    assert decide_rules(state).action == "watch"
    state["fit"] = FitReport(job_id="j", coverage=0.1, per_requirement=[], in_domain=True)
    assert decide_rules(state).action == "skip"


# ---------------------------------------------------------------- failure handling, replay
async def test_transient_failures_are_retried_then_dead_lettered():
    g = compile(memory_saver())
    async with toolbox() as tb:
        real, calls = tb.call, {"n": 0}

        async def flaky(agent, tool, args=None):
            if tool == "marketplace.get_price_stats":
                calls["n"] += 1
                raise httpx.ConnectError("connection reset")
            return await real(agent, tool, args)
        tb.call = flaky
        inp, cfg = start(BID_JOBS[0])
        out = await g.ainvoke(inp, cfg, context=Ctx(tools=tb, llm=LLM(available=False)))
    assert out["status"] == "dead_letter" and calls["n"] == 3      # first try + 2 retries (config)
    assert any("gave up after 3 attempts" in e for e in out["errors"])


async def test_replay_any_job_from_any_node():
    g = compile(memory_saver())
    async with toolbox() as tb:
        ctx = Ctx(tools=tb, llm=LLM(available=False))
        inp, cfg = start(BID_JOBS[0])
        first = await g.ainvoke(inp, cfg, context=ctx)
        snap = await checkpoint_before(g, cfg, "pricing")
        assert snap.values.get("decision") and not snap.values.get("quote")
        again = await g.ainvoke(None, snap.config, context=ctx)
        assert again["__interrupt__"][0].value["cover_letter"] == first["__interrupt__"][0].value["cover_letter"]
        rows = await history(g, cfg)
        assert len(rows) > 10 and any(r["next"] == ["approval"] for r in rows)
