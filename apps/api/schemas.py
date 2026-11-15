"""API request/response models. Agent hand-off models are reused as-is, so the TypeScript client
generated from OpenAPI has exactly the shapes the graph produces (JobSpec, RiskReport, ...)."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field

from agent.conversation import Intent, ReplyDraft
from agent.handoffs import (BidDecision, ComplianceVerdict, Critique, FitReport, JobSpec, PriceQuote, ProposalDraft,
                            RiskReport)


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)
    name: str = Field(min_length=1, max_length=120)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class OwnProfile(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=200)
    skills: list[str] = Field(default_factory=list, max_length=60)
    categories: list[str] = Field(default_factory=list, max_length=20)


class SavedSearch(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    query: str | None = Field(None, max_length=200)
    category: str | None = Field(None, max_length=80)
    interval_min: int = Field(60, ge=15, le=24 * 60, description="How often the worker scouts this search")


class Settings(BaseModel):
    onboarded: bool = False
    profile_mode: Literal["persona", "own"] = "persona"
    persona: str | None = None
    own_profile: OwnProfile | None = None
    marketplace: Literal["gigsim", "upwork_live"] = "gigsim"
    gigsim_account: str | None = None
    autonomy: Literal["suggest", "auto_skip"] = "suggest"
    weekly_connects_budget: int = Field(60, ge=0, le=1000)
    hourly_floor: float | None = Field(None, ge=0)
    fixed_floor: float | None = Field(None, ge=0)
    categories: list[str] = Field(default_factory=list)
    saved_searches: list[SavedSearch] = Field(default_factory=list)
    upwork_connected: bool = False


class SettingsIn(BaseModel):
    """Partial update; omitted fields keep their value."""
    profile_mode: Literal["persona", "own"] | None = None
    persona: str | None = None
    own_profile: OwnProfile | None = None
    marketplace: Literal["gigsim", "upwork_live"] | None = None
    gigsim_account: str | None = None
    autonomy: Literal["suggest", "auto_skip"] | None = None
    weekly_connects_budget: int | None = Field(None, ge=0, le=1000)
    hourly_floor: float | None = Field(None, ge=0)
    fixed_floor: float | None = Field(None, ge=0)
    categories: list[str] | None = None
    saved_searches: list[SavedSearch] | None = None
    onboarded: bool | None = None


class Me(BaseModel):
    id: int
    email: str
    name: str
    settings: Settings


class Persona(BaseModel):
    id: str
    name: str
    title: str
    skills: list[str]
    categories: list[str]
    hourly_floor: float
    fixed_floor: float


class RunSummary(BaseModel):
    thread_id: str
    kind: Literal["bid", "conversation"]
    status: str
    updated_at: float
    job_id: str | None = None
    market_thread_id: str | None = None
    title: str | None = None
    category: str | None = None
    action: str | None = None
    confidence: float | None = None
    reasons: list[str] = []
    coverage: float | None = None
    scam_score: float | None = None
    scam_type: str | None = None
    injection: bool = False
    price: float | None = None
    bid_type: str | None = None
    connects_cost: int | None = None
    critic: float | None = None
    pending: bool = False
    intent: str | None = None
    client_message: str | None = None
    usd: float = 0.0
    latency_ms: float = 0.0
    errors: list[str] = []


class Budget(BaseModel):
    type: Literal["fixed", "hourly"]
    min: float
    max: float


class JobCard(BaseModel):
    id: str
    title: str
    category: str | None = None
    skills: list[str] = []
    budget: Budget
    posted_at: str
    proposals_count: int | None = None
    connects_cost: int
    run: RunSummary | None = None


class JobList(BaseModel):
    items: list[JobCard]
    analysed: int
    marketplace_ok: bool = True


class HistoryRow(BaseModel):
    checkpoint_id: str | None
    next: list[str]
    step: int | None
    status: str | None
    created_at: str | None


class EditRow(BaseModel):
    action: str
    note: str | None
    diff: str | None
    at: float


class RunView(BaseModel):
    thread_id: str
    kind: Literal["bid", "conversation"]
    status: str
    pending: dict[str, Any] | None = None
    job: dict[str, Any] | None = None
    client: dict[str, Any] | None = None
    spec: JobSpec | None = None
    risk: RiskReport | None = None
    fit: FitReport | None = None
    decision: BidDecision | None = None
    quote: PriceQuote | None = None
    draft: ProposalDraft | None = None
    critiques: list[Critique] = []
    compliance: ComplianceVerdict | None = None
    verification: dict[str, Any] | None = None
    evidence: dict[str, str] = {}
    submission: dict[str, Any] | None = None
    intent: Intent | None = None
    reply: ReplyDraft | None = None
    client_message: str | None = None
    thread: dict[str, Any] | None = None
    trace: list[dict[str, Any]] = []
    errors: list[str] = []
    steps: int = 0
    tokens: int = 0
    usd: float = 0.0
    history: list[HistoryRow] = []
    edits: list[EditRow] = []
    trace_url: str | None = None


class ResumeIn(BaseModel):
    action: Literal["approve", "edit", "reject"]
    cover_letter: str | None = Field(None, max_length=5000)
    bid_amount: float | None = Field(None, gt=0, le=100_000)
    body: str | None = Field(None, max_length=4000)
    slots: list[int] | None = None
    note: str | None = Field(None, max_length=500, description="Reason, required when rejecting")


class Accepted(BaseModel):
    thread_id: str
    status: str


class RegenerateIn(BaseModel):
    paragraph: int = Field(ge=0, le=20)
    instruction: str | None = Field(None, max_length=300)


class RegenerateOut(BaseModel):
    paragraph: int
    text: str
    model: str


class PipelineCard(BaseModel):
    id: str
    title: str
    stage: str
    category: str | None = None
    bid_amount: float | None = None
    connects: int | None = None
    thread_id: str | None = None
    market_thread_id: str | None = None
    updated_at: float


class Pipeline(BaseModel):
    stages: list[str]
    cards: list[PipelineCard]


class Message(BaseModel):
    id: str
    sender: str
    body: str
    at: str


class ThreadSummary(BaseModel):
    id: str
    job_id: str
    job_title: str | None = None
    stage: str
    last_message: Message | None = None
    pending_run: str | None = None
    messages: list[Message] = []


class ThreadList(BaseModel):
    items: list[ThreadSummary]


class CategoryStat(BaseModel):
    category: str
    proposals: int
    replies: int
    hires: int
    reply_rate: float
    hire_rate: float
    connects: int


class Analytics(BaseModel):
    proposals: int
    reply_rate: float
    hire_rate: float
    connects_spent: int
    connects_on_replied: int
    avg_usd_per_proposal: float
    avg_latency_s: float
    by_category: list[CategoryStat]
    rejection_reasons: list[dict[str, Any]]
    skip_reasons: list[dict[str, Any]]


class StyleRule(BaseModel):
    key: str
    kind: str
    value: str
    count: int
    examples: list[str] = []
    promoted_at: str | None = None


class OutcomeEntry(BaseModel):
    category: str
    n: int
    reply_rate: float
    won: int
    lessons: list[dict[str, Any]]
    updated_at: str | None = None


class MemoryView(BaseModel):
    style: list[StyleRule]
    style_pending: list[StyleRule]
    outcome: list[OutcomeEntry]


class PortfolioFile(BaseModel):
    path: str
    size: int


class Health(BaseModel):
    api: bool = True
    marketplace_ok: bool
    marketplace_mode: str
    marketplace_detail: str | None = None
    llm_available: bool
    model_profile: str
    sync_last_run: float | None = None
