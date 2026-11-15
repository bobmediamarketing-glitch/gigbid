"""The conversation graph (Part C1): one thread per client conversation.

    START -> load_thread --(nothing new from the client)--> END
          -> classify (question | negotiation | interview_request | scam_signal | other)
          -> gather (evidence for questions, free slots for interviews)
          -> draft_reply -> verify_reply -> check_reply --(blocked)--> END
          -> approve_reply [interrupt] --edit--> check_reply
                         \\--approve--> send_reply (message + tentative holds) -> END

Nothing is sent without the interrupt: send_reply is only reachable through approve_reply.
"""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from agent.conversation import ConvState
from agent.nodes.base import Ctx, halted
from agent.nodes.liaison import (
    approve_reply,
    check_reply,
    classify,
    draft_reply,
    gather,
    load_thread,
    send_reply,
    verify_reply,
)


def go(target: str):
    def route(s: dict) -> str:
        return END if halted(s) else target
    route.__name__ = f"to_{target}"
    return route


def after_check(s: dict) -> str:
    if halted(s):
        return END
    return "approve_reply"  # a failing human edit goes back to the human with the violations shown


def after_approval(s: dict) -> str:
    if halted(s):
        return END
    return {"approve": "send_reply", "edit": "check_reply"}.get(s["approval"].action, END)


def build() -> StateGraph:
    g = StateGraph(ConvState, context_schema=Ctx)
    for name, fn in [("load_thread", load_thread), ("classify", classify), ("gather", gather),
                     ("draft_reply", draft_reply), ("verify_reply", verify_reply), ("check_reply", check_reply),
                     ("approve_reply", approve_reply), ("send_reply", send_reply)]:
        g.add_node(name, fn)
    g.add_edge(START, "load_thread")
    g.add_conditional_edges("load_thread", go("classify"), ["classify", END])
    g.add_conditional_edges("classify", go("gather"), ["gather", END])
    g.add_conditional_edges("gather", go("draft_reply"), ["draft_reply", END])
    g.add_conditional_edges("draft_reply", go("verify_reply"), ["verify_reply", END])
    g.add_conditional_edges("verify_reply", go("check_reply"), ["check_reply", END])
    g.add_conditional_edges("check_reply", after_check, ["approve_reply", END])
    g.add_conditional_edges("approve_reply", after_approval, ["send_reply", "check_reply", END])
    g.add_edge("send_reply", END)
    return g


def compile(checkpointer=None, store=None, **kw):
    return build().compile(checkpointer=checkpointer, store=store, **kw)
