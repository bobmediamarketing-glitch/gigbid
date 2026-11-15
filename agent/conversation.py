"""Typed hand-offs and state for the conversation graph (one thread per client conversation)."""
from __future__ import annotations

import operator
from typing import Annotated, Literal, TypedDict

from pydantic import BaseModel, Field

from agent.handoffs import Claim, ComplianceVerdict
from agent.state import TraceEvent, last_wins

IntentKind = Literal["question", "negotiation", "interview_request", "scam_signal", "other"]


class Intent(BaseModel):
    kind: IntentKind
    confidence: float = Field(ge=0, le=1)
    reasons: list[str] = Field(default_factory=list)
    question: str | None = Field(None, description="The client's question, if any")
    counter_offer: float | None = Field(None, description="Price the client proposed, if any")
    scam_type: str | None = None


class ReplyDraft(BaseModel):
    body: str = Field(description="Reply text with [evidence-id] markers after grounded claims")
    claims: list[Claim] = Field(default_factory=list)
    slots_offered: list[dict] = Field(default_factory=list, description="{start, end, timezone}")
    price_position: str | None = None
    model: str = "rules"

    def client_text(self) -> str:
        from agent.handoffs import ProposalDraft
        return ProposalDraft(job_id="-", cover_letter=self.body).client_text()


class ReplyApproval(BaseModel):
    action: Literal["approve", "edit", "reject"]
    body: str | None = None
    slots: list[int] | None = Field(None, description="Indexes of offered slots to keep (default all)")
    note: str | None = None


class ConvState(TypedDict, total=False):
    run_id: str
    thread_id: str
    persona: str
    user_id: str
    thread: dict
    job: dict
    profile: dict
    client_message: str               # latest client message, injection-stripped
    injection_spans: list[str]
    intent: Intent
    evidence: dict[str, str]
    best: dict                        # strongest case study for the question: {id, title, result}
    slots: list[dict]
    reply: ReplyDraft
    verification: dict
    compliance: ComplianceVerdict | None
    approval: ReplyApproval
    sent: dict
    holds: list[dict]
    steps: Annotated[int, operator.add]
    tokens: Annotated[int, operator.add]
    usd: Annotated[float, operator.add]
    trace: Annotated[list[TraceEvent], operator.add]
    errors: Annotated[list[str], operator.add]
    status: Annotated[str, last_wins]
