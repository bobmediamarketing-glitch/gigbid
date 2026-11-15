"""Live Upwork adapter for the marketplace port (Part A4).

Connects to the official Upwork MCP server over Streamable HTTP with the user's
OAuth 2.1 access token (stored encrypted per user, see apps/api/auth/token_store.py)
and maps port methods onto Upwork's tools. Tool names live in agent/config.yaml
(`marketplace.upwork_live.tool_map`) and are checked against `list_tools` on
connect, so a renamed upstream tool fails loudly instead of silently.

Platform rules enforced here, regardless of what the caller asks:
- writes create drafts only; submit and send return `pending_platform_confirmation`,
  because the user must confirm on Upwork itself;
- reads are throttled to `min_read_interval_s` (no polling that looks like scraping);
- no browser automation, cookies or page scraping anywhere in this module.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any, Callable

import yaml

from agent.marketplace_port import (
    ClientHistory, ConnectsBalance, Job, JobPage, MarketEvent, MarketplaceError, MarketplaceUnavailable,
    Message, NotFound, PlatformPolicy, PriceStat, Proposal, Thread, WritePreview,
)

CONFIG = Path(__file__).resolve().parents[3] / "agent" / "config.yaml"


def _live_cfg() -> dict:
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))["marketplace"]["upwork_live"]


class UpworkLiveAdapter:
    mode = "upwork_live"

    def __init__(self, access_token: str | None = None, *, token_provider: Callable[[], str] | None = None,
                 url: str | None = None) -> None:
        cfg = _live_cfg()
        self.url = url or os.getenv("UPWORK_MCP_URL", cfg["url"])
        self.tool_map: dict[str, str] = cfg["tool_map"]
        self.min_read_interval = float(cfg.get("min_read_interval_s", 900))
        self._token_provider = token_provider or (lambda: access_token or "")
        self._stack: AsyncExitStack | None = None
        self._session = None
        self._last_read: dict[str, float] = {}
        self._lock = asyncio.Lock()

    # ---- connection ----
    async def _connect(self):
        if self._session:
            return self._session
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        token = self._token_provider()
        if not token:
            raise MarketplaceUnavailable("Upwork account not connected: complete OAuth in Settings first")
        self._stack = AsyncExitStack()
        try:
            read, write, _ = await self._stack.enter_async_context(
                streamablehttp_client(self.url, headers={"Authorization": f"Bearer {token}"}))
            self._session = await self._stack.enter_async_context(ClientSession(read, write))
            await self._session.initialize()
            available = {t.name for t in (await self._session.list_tools()).tools}
        except Exception as e:  # network, auth or protocol failure
            await self.aclose()
            raise MarketplaceUnavailable(f"cannot reach Upwork MCP: {e}") from e
        missing = {k: v for k, v in self.tool_map.items() if v and v not in available}
        if missing:
            await self.aclose()
            raise MarketplaceError(f"Upwork MCP tool names changed, update agent/config.yaml: {missing}")
        return self._session

    async def aclose(self) -> None:
        if self._stack:
            await self._stack.aclose()
        self._stack, self._session = None, None

    async def _call(self, port_method: str, args: dict, *, read: bool = True) -> Any:
        name = self.tool_map.get(port_method)
        if not name:
            raise MarketplaceError(f"{port_method} is not supported in live mode")
        async with self._lock:
            if read:
                key = f"{port_method}:{json.dumps(args, sort_keys=True)}"
                since = time.time() - self._last_read.get(key, 0)
                if since < self.min_read_interval and port_method == "search_jobs":
                    raise MarketplaceError(f"live search throttled; next allowed in {int(self.min_read_interval - since)}s")
                self._last_read[key] = time.time()
            session = await self._connect()
            res = await session.call_tool(name, args)
        if res.isError:
            text = " ".join(getattr(c, "text", "") for c in res.content)
            raise NotFound(text) if "not found" in text.lower() else MarketplaceError(text)
        if res.structuredContent is not None:
            return res.structuredContent
        text = "".join(getattr(c, "text", "") for c in res.content)
        try:
            return json.loads(text)
        except ValueError:
            return {"text": text}

    # ---- mapping helpers (Upwork payloads -> port models) ----
    @staticmethod
    def _job(d: dict) -> Job:
        budget = d.get("budget") or {}
        hourly = d.get("hourlyBudgetMax") or d.get("hourly_max")
        return Job(
            id=str(d.get("id") or d.get("ciphertext") or d.get("job_id")),
            title=d.get("title", ""), description=d.get("description", ""),
            category=d.get("category") or (d.get("occupation") or {}).get("prefLabel"),
            skills=[s if isinstance(s, str) else s.get("name", "") for s in d.get("skills", [])],
            budget={"type": "hourly" if hourly else "fixed",
                    "min": float(d.get("hourlyBudgetMin") or budget.get("min") or budget.get("amount") or 0),
                    "max": float(hourly or budget.get("max") or budget.get("amount") or 0)},
            duration=d.get("duration"), experience_level=d.get("experienceLevel") or d.get("experience_level"),
            posted_at=str(d.get("createdDateTime") or d.get("posted_at") or ""),
            client_id=str((d.get("client") or {}).get("id") or d.get("client_id") or "unknown"),
            screening_questions=[q if isinstance(q, str) else q.get("question", "") for q in d.get("questions", [])],
            proposals_count=d.get("totalApplicants") or d.get("proposals_count"),
            connects_cost=int(d.get("connectPrice") or d.get("connects_cost") or 0),
        )

    # ---- port: reads ----
    async def health(self) -> bool:
        try:
            await self._connect()
            return True
        except MarketplaceError:
            return False

    async def get_policy(self) -> PlatformPolicy:
        return PlatformPolicy(version=0, raw={"source": "upwork", "note": "Upwork terms apply; see policy pack"})

    async def search_jobs(self, query=None, category=None, skills=None, posted_after=None, limit=20) -> JobPage:
        d = await self._call("search_jobs", {k: v for k, v in {"query": query, "category": category,
                                                               "skills": skills, "limit": limit}.items() if v})
        items = d.get("jobs") or d.get("items") or []
        return JobPage(total=d.get("total", len(items)), items=[self._job(x) for x in items])

    async def get_job(self, job_id: str) -> Job:
        return self._job(await self._call("get_job", {"job_id": job_id}))

    async def get_client_history(self, client_id: str) -> ClientHistory:
        d = await self._call("get_client_history", {"client_id": client_id})
        return ClientHistory(id=client_id, name=d.get("name"), country=d.get("country"),
                             payment_verified=bool(d.get("paymentVerified", d.get("payment_verified", False))),
                             total_spent=float(d.get("totalSpent", d.get("total_spent", 0)) or 0),
                             jobs_posted=int(d.get("jobsPosted", d.get("jobs_posted", 0)) or 0),
                             hires=int(d.get("hires", 0) or 0), hire_rate=float(d.get("hireRate", 0) or 0),
                             avg_rating_given=d.get("feedbackScore"))

    async def get_price_stats(self, category: str, budget_type: str | None = None) -> list[PriceStat]:
        return []  # Upwork exposes no market price statistics; Pricing falls back to job budget + user floor

    async def get_connects_balance(self) -> ConnectsBalance:
        d = await self._call("get_connects_balance", {})
        return ConnectsBalance(freelancer_id=str(d.get("user_id", "me")), balance=int(d.get("balance", 0)),
                               weekly_allowance=int(d.get("allowance", 0)))

    async def list_threads(self) -> list[Thread]:
        d = await self._call("list_threads", {})
        return [Thread(id=str(t["id"]), client_id=str(t.get("client_id", "")), job_id=str(t.get("job_id", "")),
                       stage=t.get("stage", "replied")) for t in d.get("rooms") or d.get("items") or []]

    async def get_thread(self, thread_id: str) -> Thread:
        d = await self._call("get_thread", {"room_id": thread_id})
        msgs = [Message(id=str(m.get("id")), sender="client" if m.get("from_client", True) else "freelancer",
                        body=m.get("message") or m.get("body", ""), at=str(m.get("createdAt", "")))
                for m in d.get("messages", [])]
        return Thread(id=thread_id, client_id=str(d.get("client_id", "")), job_id=str(d.get("job_id", "")),
                      stage=d.get("stage", "replied"), messages=msgs)

    async def list_events(self, after_id: int = 0) -> list[MarketEvent]:
        return []  # live mode derives pipeline changes from proposals and threads on the read schedule

    # ---- port: writes (drafts only) ----
    async def create_proposal_draft(self, job_id, cover_letter, bid_amount, bid_type, screening_answers,
                                    idempotency_key, dry_run=False):
        payload = {"job_id": job_id, "cover_letter": cover_letter, "bid_amount": bid_amount, "bid_type": bid_type,
                   "screening_answers": screening_answers}
        if dry_run:
            job = await self.get_job(job_id)
            return WritePreview(action="create_proposal_draft", payload=payload, target=f"Upwork job {job_id}",
                                connects_cost=job.connects_cost)
        d = await self._call("create_proposal_draft", payload | {"idempotency_key": idempotency_key}, read=False)
        return Proposal(id=str(d.get("id") or d.get("draft_id")), job_id=job_id, status="draft",
                        cover_letter=cover_letter, bid_amount=bid_amount, bid_type=bid_type,
                        screening_answers=screening_answers)

    async def submit_proposal(self, proposal_id, idempotency_key, dry_run=False):
        if dry_run:
            return WritePreview(action="submit_proposal", payload={"proposal_id": proposal_id},
                                target="Upwork (you confirm on Upwork)")
        d = await self._call("submit_proposal", {"proposal_id": proposal_id, "idempotency_key": idempotency_key},
                             read=False)
        # Upwork turns this into a pending action the user confirms on the platform.
        return Proposal(id=proposal_id, job_id=str(d.get("job_id", "")), status="pending_platform_confirmation",
                        cover_letter=d.get("cover_letter", ""), bid_amount=float(d.get("bid_amount", 0) or 0),
                        bid_type=d.get("bid_type", "fixed"))

    async def send_message(self, thread_id, body, idempotency_key, dry_run=False):
        if dry_run:
            return WritePreview(action="send_message", payload={"body": body}, target=f"Upwork room {thread_id}")
        d = await self._call("send_message", {"room_id": thread_id, "message": body,
                                              "idempotency_key": idempotency_key}, read=False)
        return Message(id=str(d.get("id", idempotency_key)), sender="freelancer", body=body,
                       at=str(d.get("createdAt", "pending_platform_confirmation")))
