"""Per-user sliding-window limiter that waits politely instead of hammering the upstream."""
from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque


class RateLimitExceeded(Exception):
    pass


class PoliteLimiter:
    def __init__(self, requests: int, per_seconds: float, max_wait_s: float = 20.0) -> None:
        self.requests, self.per, self.max_wait = requests, per_seconds, max_wait_s
        self._hits: dict[str, deque] = defaultdict(deque)
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def acquire(self, key: str) -> None:
        async with self._locks[key]:
            q = self._hits[key]
            deadline = time.monotonic() + self.max_wait
            while True:
                now = time.monotonic()
                while q and q[0] <= now - self.per:
                    q.popleft()
                if len(q) < self.requests:
                    q.append(now)
                    return
                wait = q[0] + self.per - now
                if now + wait > deadline:
                    raise RateLimitExceeded(f"per-user limit of {self.requests}/{self.per}s reached")
                await asyncio.sleep(wait)
