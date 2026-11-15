"""Typed graph state and reducers (Part C).

Parallel branches (analyst, risk, matcher) each own one key, so they never conflict.
List keys that several nodes append to use `operator.add`; counters use `add` too, so
the budget sums correctly no matter which branch finished first.
"""
from __future__ import annotations

import operator
from typing import Annotated, Any, Literal, TypedDict

from agent.handoffs import (Approval, BidDecision, ComplianceVerdict, Critique, FitReport, JobSpec, PriceQuote,
                            ProposalDraft, RiskReport)

Status = Literal["running", "skipped", "skip_suggested", "watching", "awaiting_approval", "submitted",
                 "pending_platform_confirmation", "rejected", "blocked", "queued", "needs_attention", "dead_letter"]


def last_wins(_old: Any, new: Any) -> Any:
    return new


class TraceEvent(TypedDict, total=False):
    node: str
    ms: float
    model: str
    tokens_in: int
    tokens_out: int
    usd: float
    note: str


class BidState(TypedDict, total=False):
    # inputs
    run_id: str
    job_id: str
    persona: str
    user_id: str                       # memory namespace owner (defaults to "local")
    autonomy: str                      # suggest | auto_skip (never auto-send)
    # context gathered at intake (raw job text is untrusted; LLMs only see job_text_clean)
    job: dict
    job_text_clean: str
    injection_spans: list[str]
    client: dict
    policy: dict
    connects_balance: int
    profile: dict
    # one key per agent
    spec: JobSpec
    risk: RiskReport
    fit: FitReport
    decision: BidDecision
    quote: PriceQuote
    draft: ProposalDraft
    evidence: dict[str, str]          # id -> text the writer was given (claim verification checks against it)
    verification: dict
    critiques: Annotated[list[Critique], operator.add]
    compliance: ComplianceVerdict
    approval: Approval
    submission: dict
    # control
    revisions: Annotated[int, operator.add]
    compliance_retries: Annotated[int, operator.add]
    steps: Annotated[int, operator.add]
    tokens: Annotated[int, operator.add]
    usd: Annotated[float, operator.add]
    trace: Annotated[list[TraceEvent], operator.add]
    errors: Annotated[list[str], operator.add]
    status: Annotated[Status, last_wins]
