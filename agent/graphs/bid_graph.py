"""The bid graph (Part C), hand-written with LangGraph's StateGraph.

    START -> intake -> Send(analyst | risk | matcher)  run in parallel, one state key each
          -> decide --skip / watch--> END
          -> pricing -> writer -> verify -> critic --(fail, < max loops)--> writer
                                               \\--> compliance --(blocked once)--> writer
                                                          \\--> approval [interrupt] --edit--> compliance
                                                                    \\--approve--> submit -> END

Any node can halt the run (skipped / skip_suggested / watching, queued in degraded mode,
needs_attention on a budget, blocked, rejected, dead_letter); every router sends a halted run to END.
"""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from agent.nodes.analyst import analyst
from agent.nodes.approval import approval, submit
from agent.nodes.base import Ctx, halted
from agent.nodes.compliance import compliance
from agent.nodes.critic import critic
from agent.nodes.decide import decide
from agent.nodes.intake import intake
from agent.nodes.matcher import matcher
from agent.nodes.pricing import pricing
from agent.nodes.risk import risk
from agent.nodes.verifier import verify
from agent.nodes.writer import writer
from agent.settings import section
from agent.state import BidState

PARALLEL = ["analyst", "risk", "matcher"]


def after_intake(s: dict):
    """Fan out with Send: each analysis agent gets its own copy of the state and writes one key."""
    return END if halted(s) else [Send(n, s) for n in PARALLEL]


def after_decide(s: dict) -> str:
    return END if halted(s) else "pricing"


def go(target: str):
    def route(s: dict) -> str:
        return END if halted(s) else target
    route.__name__ = f"to_{target}"
    return route


def after_critic(s: dict) -> str:
    if halted(s):
        return END
    last = s["critiques"][-1]
    if not last.passed and len(s["critiques"]) <= section("bid_graph")["critic_max_loops"]:
        return "writer"
    return "compliance"


def after_compliance(s: dict) -> str:
    if halted(s):
        return END
    if s["compliance"].allowed:
        return "approval"
    return "approval" if s.get("approval") else "writer"  # a human edit that breaks policy goes back to the human


def after_approval(s: dict) -> str:
    if halted(s):
        return END
    a = s["approval"]
    return {"approve": "submit", "edit": "compliance"}.get(a.action, END)


def build() -> StateGraph:
    g = StateGraph(BidState, context_schema=Ctx)
    for name, fn in [("intake", intake), ("analyst", analyst), ("risk", risk), ("matcher", matcher),
                     ("decide", decide), ("pricing", pricing), ("writer", writer), ("verify", verify),
                     ("critic", critic), ("compliance", compliance), ("approval", approval), ("submit", submit)]:
        g.add_node(name, fn)
    g.add_edge(START, "intake")
    g.add_conditional_edges("intake", after_intake, PARALLEL + [END])
    for n in PARALLEL:
        g.add_edge(n, "decide")  # decide waits for all three branches
    g.add_conditional_edges("decide", after_decide, ["pricing", END])
    g.add_conditional_edges("pricing", go("writer"), ["writer", END])
    g.add_conditional_edges("writer", go("verify"), ["verify", END])
    g.add_conditional_edges("verify", go("critic"), ["critic", END])
    g.add_conditional_edges("critic", after_critic, ["writer", "compliance", END])
    g.add_conditional_edges("compliance", after_compliance, ["approval", "writer", END])
    g.add_conditional_edges("approval", after_approval, ["submit", "compliance", END])
    g.add_edge("submit", END)
    return g


def compile(checkpointer=None, store=None, **kw):
    """checkpointer = thread state (durability); store = long-term memory (style + outcome)."""
    return build().compile(checkpointer=checkpointer, store=store, **kw)
