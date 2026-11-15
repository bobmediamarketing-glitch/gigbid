"""Background worker (E1): Arq on Redis.

    arq worker.tasks.WorkerSettings

- `drive`      runs one graph step for a thread (start, or resume after an approval). The API enqueues it
               with a job id derived from the thread (`run:<thread>`, `resume:<thread>:<approval id>`), and
               Arq refuses a second job with the same id, so a retried request or a restarted API never
               starts the same run twice. The bid thread id itself is derived from the job id, and the
               submit node's writes carry idempotency keys, so a worker killed mid-run resumes from its
               checkpoint and still submits exactly once.
- `sync`       every 15 s: marketplace events -> pipeline stages, outcome memory, reply drafts.
- `scout`      every minute: saved searches whose interval elapsed -> new bid threads.
"""
from __future__ import annotations

import logging
import os

from arq import cron
from arq.connections import RedisSettings

log = logging.getLogger("gigbid.worker")


async def startup(ctx: dict) -> None:
    from apps.api.runtime import Runtime
    rt = Runtime()
    await rt.start(role="worker", redis=ctx["redis"])
    ctx["rt"] = rt
    log.info("worker ready")


async def shutdown(ctx: dict) -> None:
    await ctx["rt"].stop()


async def drive(ctx: dict, uid: int, kind: str, thread: str, inp: dict) -> str:
    await ctx["rt"]._drive(uid, kind, thread, inp)
    return thread


async def sync(ctx: dict) -> int:
    return await ctx["rt"].sync_all()


async def scout(ctx: dict) -> int:
    return len(await ctx["rt"].scout_due())


def _redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(os.getenv("REDIS_URL", "redis://localhost:6379/0"))


class WorkerSettings:
    functions = [drive]
    cron_jobs = [
        cron(sync, second={0, 15, 30, 45}, run_at_startup=True, unique=True, timeout=120),
        cron(scout, second=5, unique=True, timeout=300),
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = _redis_settings()
    max_jobs = int(os.getenv("WORKER_MAX_JOBS", "8"))
    job_timeout = 900          # a full bid run with model calls fits comfortably
    keep_result = 3600         # job ids stay reserved for an hour (duplicate enqueues are dropped)
    max_tries = 3              # Arq retries a job whose worker died; the checkpoint makes that safe
    health_check_interval = 30
