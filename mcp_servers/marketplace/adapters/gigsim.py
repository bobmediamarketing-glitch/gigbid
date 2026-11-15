"""GigSim adapter for the marketplace port.

Timeouts, bounded retries with exponential backoff on 5xx/connection errors,
Retry-After on 429, and translation of every failure into a port error.
"""
from __future__ import annotations

import asyncio
import os
import random

import httpx

from agent.marketplace_port import (
    ClientHistory, Conflict, ConnectsBalance, Job, JobPage, MarketEvent, MarketplaceError,
    MarketplaceUnavailable, Message, NotFound, PlatformPolicy, PriceStat, Proposal, RateLimited,
    Thread, WritePreview,
)


class GigSimAdapter:
    mode = "gigsim"

    def __init__(self, base_url: str | None = None, token: str | None = None, *,
                 transport: httpx.AsyncBaseTransport | None = None, timeout: float = 10.0,
                 max_retries: int = 3, backoff_base: float = 0.5, max_retry_after: float = 15.0) -> None:
        self.base_url = (base_url or os.getenv("GIGSIM_BASE_URL", "http://localhost:8100")).rstrip("/")
        self.token = token or os.getenv("GIGSIM_TOKEN", "gigsim-ai_ml-token")
        self.max_retries, self.backoff_base, self.max_retry_after = max_retries, backoff_base, max_retry_after
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=timeout, transport=transport,
                                         headers={"Authorization": f"Bearer {self.token}"})

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _req(self, method: str, path: str, *, idem: str | None = None, **kw) -> dict:
        headers = {"Idempotency-Key": idem} if idem else {}
        last: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                r = await self._client.request(method, path, headers=headers, **kw)
            except (httpx.TransportError, httpx.TimeoutException) as e:
                last = e
            else:
                if r.status_code < 400:
                    return r.json()
                detail = _detail(r)
                if r.status_code == 429:
                    wait = float(r.headers.get("Retry-After", "1"))
                    if wait > self.max_retry_after or attempt == self.max_retries:
                        raise RateLimited(wait, detail)
                    await asyncio.sleep(wait)
                    continue
                if r.status_code == 404:
                    raise NotFound(detail)
                if r.status_code in (402, 409):
                    raise Conflict(detail)
                if r.status_code >= 500:
                    last = MarketplaceUnavailable(f"{r.status_code}: {detail}")
                else:
                    raise MarketplaceError(f"{r.status_code}: {detail}")
            if attempt < self.max_retries:
                # Writes are safe to retry because the idempotency key travels with them.
                await asyncio.sleep(self.backoff_base * (2 ** attempt) * (1 + random.random() * 0.2))
        raise MarketplaceUnavailable(str(last) if last else "unavailable")

    # ---- reads ----
    async def health(self) -> bool:
        try:
            r = await self._client.get("/health", timeout=3.0)
            return r.status_code == 200 and r.json().get("ok", False)
        except httpx.HTTPError:
            return False

    async def get_policy(self) -> PlatformPolicy:
        raw = await self._req("GET", "/policy")
        return PlatformPolicy(version=raw.get("version", 0), raw=raw)

    async def search_jobs(self, query=None, category=None, skills=None, posted_after=None, limit=20) -> JobPage:
        params = {k: v for k, v in {"q": query, "category": category, "posted_after": posted_after,
                                    "skills": ",".join(skills) if skills else None, "limit": limit}.items() if v}
        return JobPage.model_validate(await self._req("GET", "/jobs", params=params))

    async def get_job(self, job_id: str) -> Job:
        return Job.model_validate(await self._req("GET", f"/jobs/{job_id}"))

    async def get_client_history(self, client_id: str) -> ClientHistory:
        return ClientHistory.model_validate(await self._req("GET", f"/clients/{client_id}"))

    async def get_price_stats(self, category: str, budget_type: str | None = None) -> list[PriceStat]:
        params = {"category": category} | ({"budget_type": budget_type} if budget_type else {})
        return [PriceStat.model_validate(x) for x in (await self._req("GET", "/market/price-stats", params=params))["items"]]

    async def get_connects_balance(self) -> ConnectsBalance:
        return ConnectsBalance.model_validate(await self._req("GET", "/me/connects"))

    async def list_threads(self) -> list[Thread]:
        items = (await self._req("GET", "/threads"))["items"]
        return [Thread.model_validate(t | {"messages": [t["last_message"]] if t.get("last_message") else []}) for t in items]

    async def get_thread(self, thread_id: str) -> Thread:
        return Thread.model_validate(await self._req("GET", f"/threads/{thread_id}"))

    async def list_events(self, after_id: int = 0) -> list[MarketEvent]:
        return [MarketEvent.model_validate(e) for e in (await self._req("GET", "/events", params={"after_id": after_id}))["items"]]

    # ---- writes ----
    async def create_proposal_draft(self, job_id, cover_letter, bid_amount, bid_type, screening_answers,
                                    idempotency_key, dry_run=False):
        body = {"job_id": job_id, "cover_letter": cover_letter, "bid_amount": bid_amount, "bid_type": bid_type,
                "screening_answers": screening_answers}
        if dry_run:
            r = await self._req("POST", "/proposals", json=body | {"dry_run": True})
            w = r["would_create"]
            return WritePreview(action="create_proposal_draft", payload=w["payload"], target=f"job {job_id}",
                                connects_cost=0, connects_balance_after=w["connects_balance"])
        return Proposal.model_validate(await self._req("POST", "/proposals", json=body, idem=idempotency_key))

    async def submit_proposal(self, proposal_id, idempotency_key, dry_run=False):
        if dry_run:
            r = await self._req("POST", f"/proposals/{proposal_id}/submit", json={"dry_run": True})
            p = r["would_submit"]
            return WritePreview(action="submit_proposal", target=f"job {p['job_id']}", connects_cost=r["connects_cost"],
                                connects_balance_after=r["connects_balance_after"],
                                payload={k: p[k] for k in ("job_id", "cover_letter", "bid_amount", "bid_type", "screening_answers")})
        return Proposal.model_validate(await self._req("POST", f"/proposals/{proposal_id}/submit", json={},
                                                       idem=idempotency_key))

    async def send_message(self, thread_id, body, idempotency_key, dry_run=False):
        if dry_run:
            await self._req("POST", f"/threads/{thread_id}/messages", json={"body": body, "dry_run": True})
            return WritePreview(action="send_message", target=f"thread {thread_id}", payload={"body": body})
        return Message.model_validate(await self._req("POST", f"/threads/{thread_id}/messages", json={"body": body},
                                                      idem=idempotency_key))


def _detail(r: httpx.Response) -> str:
    try:
        return str(r.json().get("detail", r.text))
    except ValueError:
        return r.text[:200]
