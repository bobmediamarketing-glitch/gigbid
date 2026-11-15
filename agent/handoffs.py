"""Typed hand-offs between agents (Part C). Every edge in the bid graph carries one of these.

Agents never pass free text to each other: each node reads the models it needs from state
and writes exactly one model back, so a bad output fails validation at the boundary.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Requirement(BaseModel):
    text: str = Field(description="One requirement as the client wrote it (or a short paraphrase)")
    skills: list[str] = Field(default_factory=list, description="Canonical skill tags it implies")
    must_have: bool = True


class JobSpec(BaseModel):
    """Job Analyst -> everyone. What the client actually needs, including implied skills."""
    job_id: str
    goal: str = Field(description="The client's outcome in one sentence")
    requirements: list[Requirement]
    implied_skills: list[str] = Field(default_factory=list, description="Skills implied but not tagged")
    deliverables: list[str] = Field(default_factory=list)
    screening_questions: list[str] = Field(default_factory=list)
    read_check_word: str | None = Field(None, description="Word the client asked proposals to start with")
    budget_type: Literal["fixed", "hourly"]
    budget_min: float
    budget_max: float
    category: str | None = None
    vague: bool = Field(False, description="True when the post is too thin to scope")


class RiskReport(BaseModel):
    """Risk Assessor -> decision. Scam, injection and client-quality signals."""
    job_id: str
    scam_score: float = Field(ge=0, le=1)
    scam_type: Literal["off_platform", "free_work", "payment", "credentials"] | None = None
    red_flags: list[str] = Field(default_factory=list)
    injection_detected: bool = False
    injection_spans: list[str] = Field(default_factory=list, description="Removed from the text every LLM sees")
    client_signals: dict[str, float | bool | str] = Field(default_factory=dict)


class EvidenceRef(BaseModel):
    id: str
    type: str
    title: str
    snippet: str
    score: float
    uri: str | None = None


class RequirementFit(BaseModel):
    requirement: str
    covered: bool
    evidence: list[EvidenceRef] = Field(default_factory=list)


class FitReport(BaseModel):
    """Fit Matcher -> decision, writer. Which requirements the portfolio can prove, and with what."""
    job_id: str
    coverage: float = Field(ge=0, le=1)
    per_requirement: list[RequirementFit]
    in_domain: bool
    missing: list[str] = Field(default_factory=list)


class BidDecision(BaseModel):
    job_id: str
    bid: bool
    confidence: float = Field(ge=0, le=1)
    reasons: list[str]


class PriceQuote(BaseModel):
    job_id: str
    bid_type: Literal["fixed", "hourly"]
    amount: float = Field(gt=0)
    market: dict[str, float] = Field(default_factory=dict, description="p25/p50/p75 used")
    floor: float
    rationale: str
    connects_cost: int


class Claim(BaseModel):
    text: str = Field(description="One factual sentence from the proposal about the freelancer")
    evidence_ids: list[str] = Field(default_factory=list, description="Portfolio ids that support it")
    supported: bool | None = Field(None, description="Set by claim verification")


class ProposalDraft(BaseModel):
    """Proposal Writer -> verify -> critic -> compliance -> human."""
    job_id: str
    cover_letter: str = Field(description="Text with [evidence-id] markers after grounded claims")
    screening_answers: list[str] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    revision: int = 0
    model: str = "rules"
    prompt_version: str | None = None

    def client_text(self) -> str:
        """What the client sees: citation markers stripped (the UI shows them as hover evidence)."""
        import re
        t = re.sub(r"\s?\[[a-z_]+-(?:cs|repo|rev|prop)-\d+\](?:\[[^\]]+\])*", "", self.cover_letter)
        return re.sub(r"[ \t]+([.,;:])", r"\1", t).strip()


class Critique(BaseModel):
    revision: int
    score: float = Field(ge=0, le=1)
    passed: bool
    issues: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)


class ComplianceVerdict(BaseModel):
    allowed: bool
    policy_version: str
    violations: list[dict] = Field(default_factory=list, description="{rule, action, match}")
    redacted_text: str | None = Field(None, description="Cover letter after automatic redactions")


class Approval(BaseModel):
    """What the human sent back through interrupt()."""
    action: Literal["approve", "edit", "reject"]
    cover_letter: str | None = None
    bid_amount: float | None = None
    note: str | None = None
