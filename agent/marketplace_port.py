"""The single marketplace interface (requirement R1).

Every marketplace read and write in GigBid goes through `MarketplacePort`. Two
adapters implement it, selected by `MARKETPLACE_MODE`:

- `gigsim`      -> mcp_servers/marketplace/adapters/gigsim.py (REST simulator)
- `upwork_live` -> mcp_servers/marketplace/adapters/upwork_live.py (official Upwork MCP server)

The Marketplace MCP server is the only caller of this port; agents see MCP tools,
so the graph cannot tell which marketplace it is talking to.
"""
from __future__ import annotations

import os
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Errors. Adapters translate transport failures into these three.
# ---------------------------------------------------------------------------
class MarketplaceError(Exception):
    code = "marketplace_error"


class MarketplaceUnavailable(MarketplaceError):
    """The marketplace cannot be reached after retries. Callers queue the work (degraded mode)."""
    code = "marketplace_unavailable"


class RateLimited(MarketplaceError):
    code = "rate_limited"

    def __init__(self, retry_after: float, msg: str = "rate limited") -> None:
        super().__init__(msg)
        self.retry_after = retry_after


class NotFound(MarketplaceError):
    code = "not_found"


class Conflict(MarketplaceError):
    """The write is not allowed in the current state (already submitted, not enough Connects, ...)."""
    code = "conflict"


class RequiresPlatformConfirmation(MarketplaceError):
    """Live mode: the draft exists on the platform and the user must confirm it there."""
    code = "requires_platform_confirmation"


# ---------------------------------------------------------------------------
# Domain models shared by both adapters
# ---------------------------------------------------------------------------
class Budget(BaseModel):
    type: Literal["fixed", "hourly"]
    min: float
    max: float


class Job(BaseModel):
    id: str
    title: str
    description: str
    category: str | None = None
    skills: list[str] = []
    budget: Budget
    duration: str | None = None
    experience_level: str | None = None
    posted_at: str
    client_id: str
    screening_questions: list[str] = []
    proposals_count: int | None = None
    connects_cost: int


class JobPage(BaseModel):
    total: int
    items: list[Job]


class ClientHistory(BaseModel):
    id: str
    name: str | None = None
    country: str | None = None
    industry: str | None = None
    payment_verified: bool
    total_spent: float
    jobs_posted: int
    hires: int
    hire_rate: float
    avg_rating_given: float | None = None
    member_since: str | None = None
    open_job_ids: list[str] = []


class PriceStat(BaseModel):
    category: str
    budget_type: Literal["fixed", "hourly"]
    p25: float
    p50: float
    p75: float
    n: int


class ConnectsBalance(BaseModel):
    freelancer_id: str
    balance: int
    weekly_allowance: int


class Proposal(BaseModel):
    id: str
    job_id: str
    status: str
    cover_letter: str
    bid_amount: float
    bid_type: Literal["fixed", "hourly"]
    screening_answers: list[str] = []
    connects_spent: int | None = None
    created_at: str | None = None
    submitted_at: str | None = None
    idempotent_replay: bool = False


class Message(BaseModel):
    id: str
    sender: Literal["client", "freelancer"] = Field(alias="from")
    body: str
    at: str

    model_config = {"populate_by_name": True}


class Thread(BaseModel):
    id: str
    client_id: str
    job_id: str
    proposal_id: str | None = None
    stage: str
    messages: list[Message] = []


class MarketEvent(BaseModel):
    id: int
    type: str
    at: str
    proposal_id: str | None = None
    job_id: str | None = None
    thread_id: str | None = None


class WritePreview(BaseModel):
    """What a write would send and what it costs (dry_run). Shown on the approval screen."""
    action: Literal["create_proposal_draft", "submit_proposal", "send_message"]
    payload: dict
    connects_cost: int = 0
    connects_balance_after: int | None = None
    target: str


class PlatformPolicy(BaseModel):
    version: int
    raw: dict


# ---------------------------------------------------------------------------
# The port
# ---------------------------------------------------------------------------
@runtime_checkable
class MarketplacePort(Protocol):
    mode: str

    async def health(self) -> bool: ...
    async def get_policy(self) -> PlatformPolicy: ...

    # reads
    async def search_jobs(self, query: str | None = None, category: str | None = None,
                          skills: list[str] | None = None, posted_after: str | None = None,
                          limit: int = 20) -> JobPage: ...
    async def get_job(self, job_id: str) -> Job: ...
    async def get_client_history(self, client_id: str) -> ClientHistory: ...
    async def get_price_stats(self, category: str, budget_type: str | None = None) -> list[PriceStat]: ...
    async def get_connects_balance(self) -> ConnectsBalance: ...
    async def list_threads(self) -> list[Thread]: ...
    async def get_thread(self, thread_id: str) -> Thread: ...
    async def list_events(self, after_id: int = 0) -> list[MarketEvent]: ...

    # writes: every write carries an idempotency key and supports dry_run
    async def create_proposal_draft(self, job_id: str, cover_letter: str, bid_amount: float,
                                    bid_type: str, screening_answers: list[str], idempotency_key: str,
                                    dry_run: bool = False) -> Proposal | WritePreview: ...
    async def submit_proposal(self, proposal_id: str, idempotency_key: str,
                              dry_run: bool = False) -> Proposal | WritePreview: ...
    async def send_message(self, thread_id: str, body: str, idempotency_key: str,
                           dry_run: bool = False) -> Message | WritePreview: ...


def get_port(mode: str | None = None, **kwargs) -> MarketplacePort:
    """Build the adapter named by config. The only place that knows both adapters exist."""
    mode = mode or os.getenv("MARKETPLACE_MODE", "gigsim")
    if mode == "gigsim":
        from mcp_servers.marketplace.adapters.gigsim import GigSimAdapter
        return GigSimAdapter(**kwargs)
    if mode == "upwork_live":
        from mcp_servers.marketplace.adapters.upwork_live import UpworkLiveAdapter
        return UpworkLiveAdapter(**kwargs)
    raise ValueError(f"unknown MARKETPLACE_MODE {mode!r}")
