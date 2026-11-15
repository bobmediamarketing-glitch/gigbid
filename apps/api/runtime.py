"""Runs the graphs for the API: per-user MCP access, background runs, live events and marketplace sync.

- Every run gets its own MCP sessions created inside a context where `current_caller` is that user,
  so the three servers see the right GigSim account, portfolio folder and workspace (multi-user safe).
- Runs execute as background tasks (the worker takes this over in Part E) and stream LangGraph
  updates onto a per-user event bus that the browser reads over Server-Sent Events.
- The checkpointer is the source of truth: a page refresh or an API restart never loses a pending
  approval, because the approval is read back from the thread's checkpoint.
- A sync loop turns marketplace events into pipeline stages, feeds outcome memory and starts a
  conversation-graph run whenever a client writes.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import uuid
from collections import defaultdict
from pathlib import Path

from langgraph.types import Command
from mcp.shared.memory import create_connected_server_and_client_session as connect_mem

from agent import tracing
from agent.checkpoint import checkpointer
from agent.graphs import bid_graph, conversation_graph
from agent.llm import LLM
from agent.memory import outcomes as outcome_memory
from agent.memory.store import memory_store
from agent.nodes.base import HALTED, Ctx
from agent.mcp_client import ToolBox, ToolFailed, connect_http, mcp_mode
from apps.api import db
from apps.api.auth import load_secret
from mcp_servers.common.context import Caller, current_caller, current_trace

log = logging.getLogger("gigbid.api")
ROOT = db.ROOT
FINAL = HALTED - {"watching", "skip_suggested", "queued"}  # statuses after which a run is done for good


CHANNEL = "gigbid:events:"


class Bus:
    """Per-user fan-out of live events to every open browser tab (SSE)."""

    def __init__(self) -> None:
        self.subs: dict[int, set[asyncio.Queue]] = defaultdict(set)

    def subscribe(self, uid: int) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        self.subs[uid].add(q)
        return q

    def unsubscribe(self, uid: int, q: asyncio.Queue) -> None:
        self.subs[uid].discard(q)

    redis = None  # set in the worker: events go through Redis pub/sub to whichever API holds the browser

    def publish(self, uid: int, event: dict) -> None:
        if self.redis is not None:
            asyncio.get_running_loop().create_task(self.redis.publish(f"{CHANNEL}{uid}", json.dumps(event, default=str)))
            return
        self.local(uid, event)

    def local(self, uid: int, event: dict) -> None:
        for q in list(self.subs[uid]):
            with contextlib.suppress(asyncio.QueueFull):
                q.put_nowait(event)


def account_of(s: dict) -> str:
    return s.get("gigsim_account") or s.get("persona") or "ai_ml"


def user_dir(uid: int) -> Path:
    return ROOT / "data" / "users" / f"u{uid}"


def persona_for(uid: int, s: dict) -> tuple[str, Path]:
    """(persona name, personas_dir) for load_profile. Own-profile users keep their files under data/users."""
    if s.get("profile_mode") == "own":
        return "portfolio", user_dir(uid)
    return s.get("persona") or "ai_ml", ROOT / "data" / "personas"


def caller_for(uid: int, s: dict) -> Caller:
    acct = account_of(s)
    creds = {"gigsim_token": f"gigsim-{acct}-token", "marketplace_mode": s.get("marketplace", "gigsim")}
    if s.get("profile_mode") == "own":
        creds["portfolio_dir"] = str(user_dir(uid) / "portfolio")
    else:
        creds["persona"] = s.get("persona") or "ai_ml"
    tok = load_secret(uid, "upwork_access_token")
    if tok:
        creds["upwork_access_token"] = tok
    return Caller(user_id=f"u{uid}-{acct}", tenant="gigbid", credentials=creds)


class Runtime:
    def __init__(self) -> None:
        self.bus = Bus()
        self.saver = None
        self.store = None
        self.bid = None
        self.conv = None
        self.tasks: dict[str, asyncio.Task] = {}
        self.locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        # A few runs at a time per user: one marketplace account has one rate limit, and a burst of
        # parallel runs would only queue behind it (and could trip the polite limiter).
        self.user_slots: dict[int, asyncio.Semaphore] = defaultdict(
            lambda: asyncio.Semaphore(int(os.getenv("GIGBID_RUNS_PER_USER", "2"))))
        self._stack: contextlib.AsyncExitStack | None = None
        self._sync_task: asyncio.Task | None = None
        self._sub_task: asyncio.Task | None = None
        self.queue = None   # arq pool when REDIS_URL is set: runs go to the worker
        self.role = "api"
        self.llm = LLM()

    # ---------------------------------------------------------------- lifecycle
    async def start(self, role: str = "api", redis=None) -> None:
        """role="api": serve requests; with REDIS_URL, enqueue runs for the worker and relay its events.
        role="worker": execute runs and scheduled jobs; publish events to Redis.
        With no REDIS_URL the API does everything in-process (dev, tests, single-container deploys)."""
        self.role = role
        self._stack = contextlib.AsyncExitStack()
        self.saver = await self._stack.enter_async_context(checkpointer())
        self.store = await self._stack.enter_async_context(memory_store())
        self.bid = bid_graph.compile(self.saver, store=self.store)
        self.conv = conversation_graph.compile(self.saver, store=self.store)
        url = os.getenv("REDIS_URL")
        if redis is not None or url:
            if redis is None:
                from arq import create_pool
                from arq.connections import RedisSettings
                redis = await create_pool(RedisSettings.from_dsn(url))
            self.queue = redis
            if role == "worker":
                self.bus.redis = self.queue
            else:
                self._sub_task = asyncio.create_task(self._relay_events())
        elif os.getenv("GIGBID_SYNC", "1") == "1":
            self._sync_task = asyncio.create_task(self._sync_forever())

    async def _relay_events(self) -> None:
        """API side: forward worker events from Redis to the browsers connected to this process."""
        ps = self.queue.pubsub()
        await ps.psubscribe(f"{CHANNEL}*")
        try:
            async for msg in ps.listen():
                if msg.get("type") != "pmessage":
                    continue
                ch = msg["channel"].decode() if isinstance(msg["channel"], bytes) else msg["channel"]
                with contextlib.suppress(Exception):
                    self.bus.local(int(ch.rsplit(":", 1)[1]), json.loads(msg["data"]))
        finally:
            await ps.aclose()

    async def stop(self) -> None:
        for t in (self._sync_task, self._sub_task):
            if t:
                t.cancel()
        for t in self.tasks.values():
            t.cancel()
        if self._stack:
            await self._stack.aclose()

    # ---------------------------------------------------------------- MCP access per user
    @contextlib.asynccontextmanager
    async def toolbox(self, uid: int, trace_id: str | None = None):
        from mcp_servers.marketplace import server as mk
        from mcp_servers.portfolio import server as pf
        from mcp_servers.workspace import server as ws
        s = db.get_settings(uid)
        who = caller_for(uid, s)
        tid = trace_id or uuid.uuid4().hex
        if mcp_mode() == "http":  # separate MCP services (docker compose): signed per-user bearer
            async with connect_http(who, tid) as tb:
                yield tb
            return
        tok = current_caller.set(who)
        ttok = current_trace.set(tid)
        try:
            async with contextlib.AsyncExitStack() as st:
                sessions = {"marketplace": await st.enter_async_context(connect_mem(mk.mcp)),
                            "portfolio": await st.enter_async_context(connect_mem(pf.mcp)),
                            "workspace": await st.enter_async_context(connect_mem(ws.mcp))}
                yield ToolBox(sessions)
        finally:
            current_trace.reset(ttok)
            current_caller.reset(tok)

    async def call(self, uid: int, agent: str, tool: str, args: dict | None = None):
        """One tool call for an API request. Errors are caught inside the session and re-raised after it
        closes, so callers see a plain ToolFailed instead of a task-group ExceptionGroup."""
        err, res = None, None
        async with self.toolbox(uid) as tb:
            try:
                res = await tb.call(agent, tool, args)
            except ToolFailed as e:
                err = e
        if err:
            raise err
        return res

    def ctx(self, uid: int, tb: ToolBox, kind: str) -> Ctx:
        _, pdir = persona_for(uid, db.get_settings(uid))
        return Ctx(tools=tb, llm=self.llm, budget="bid" if kind == "bid" else "conversation", personas_dir=pdir,
                   store=self.store)

    def graph(self, kind: str):
        return self.bid if kind == "bid" else self.conv

    # ---------------------------------------------------------------- starting and resuming runs
    async def start_bid(self, uid: int, job_id: str, title: str | None = None) -> str:
        thread = f"bid-u{uid}-{job_id}"
        with db.engine().begin() as c:
            row = c.execute(db.select(db.runs.c.status).where(db.runs.c.thread_id == thread)).first()
        if row and (row.status in FINAL or row.status in ("running", "awaiting_approval")):
            return thread  # one thread per job: never analyse or submit the same job twice
        s = db.get_settings(uid)
        persona, _ = persona_for(uid, s)
        inp = {"run_id": f"u{uid}{job_id.replace('-', '')}", "job_id": job_id, "persona": persona,
               "user_id": f"u{uid}", "autonomy": s.get("autonomy", "suggest")}
        db.upsert_run(thread, uid, "bid", "running", {"title": title, "job_id": job_id}, job_id=job_id)
        await self._dispatch(uid, "bid", thread, inp, key=f"run:{thread}")
        return thread

    async def start_conversation(self, uid: int, market_thread_id: str, n_messages: int) -> str:
        thread = f"conv-u{uid}-{market_thread_id}-{n_messages}"  # one run per new client message
        with db.engine().begin() as c:
            if c.execute(db.select(db.runs.c.thread_id).where(db.runs.c.thread_id == thread)).first():
                return thread
        s = db.get_settings(uid)
        persona, _ = persona_for(uid, s)
        inp = {"run_id": thread.replace("-", "")[:40], "thread_id": market_thread_id, "persona": persona,
               "user_id": f"u{uid}"}
        db.upsert_run(thread, uid, "conversation", "running", {"market_thread_id": market_thread_id},
                      market_thread_id=market_thread_id)
        await self._dispatch(uid, "conversation", thread, inp, key=f"run:{thread}")
        return thread

    async def pending(self, uid: int, thread: str) -> dict | None:
        kind = "bid" if thread.startswith("bid-") else "conversation"
        st = await self.graph(kind).aget_state({"configurable": {"thread_id": thread}})
        for t in st.tasks or ():
            for it in getattr(t, "interrupts", ()) or ():
                return it.value
        return None

    async def resume(self, uid: int, thread: str, payload: dict, approval_id: int | None = None) -> None:
        kind = "bid" if thread.startswith("bid-") else "conversation"
        db.upsert_run(thread, uid, kind, "running", {})
        await self._dispatch(uid, kind, thread, {"__resume__": payload},
                             key=f"resume:{thread}:{approval_id or uuid.uuid4().hex[:8]}")

    async def _dispatch(self, uid: int, kind: str, thread: str, inp: dict, key: str) -> None:
        """To the worker queue when there is one (the job id makes a duplicate enqueue a no-op), else a task."""
        if self.queue is not None:
            await self.queue.enqueue_job("drive", uid, kind, thread, inp, _job_id=key)
        else:
            self.tasks[thread] = asyncio.create_task(self._drive(uid, kind, thread, inp))

    async def _drive(self, uid: int, kind: str, thread: str, inp: dict) -> None:
        if isinstance(inp, dict) and "__resume__" in inp:
            inp = Command(resume=inp["__resume__"])
        cfg = {"configurable": {"thread_id": thread}} | tracing.run_config(thread, f"u{uid}", kind)
        g = self.graph(kind)
        async with self.locks[thread], self.user_slots[uid]:
            try:
                async with self.toolbox(uid, trace_id=tracing.trace_id_for(thread)) as tb:
                    self.bus.publish(uid, {"type": "run", "thread_id": thread, "kind": kind, "status": "running"})
                    async for chunk in g.astream(inp, cfg, context=self.ctx(uid, tb, kind), stream_mode="updates"):
                        for node, upd in chunk.items():
                            if node == "__interrupt__":
                                continue
                            upd = upd or {}
                            ev = (upd.get("trace") or [{}])[0] if isinstance(upd, dict) else {}
                            self.bus.publish(uid, {"type": "node", "thread_id": thread, "kind": kind, "node": node,
                                                   "status": upd.get("status") if isinstance(upd, dict) else None,
                                                   "ms": ev.get("ms"), "model": ev.get("model"),
                                                   "tokens": (ev.get("tokens_in") or 0) + (ev.get("tokens_out") or 0)})
                await self._finish(uid, kind, thread)
                tracing.flush()
            except Exception as e:  # never leave a run silently stuck: dead-letter it with the reason
                log.exception("run %s failed", thread)
                db.upsert_run(thread, uid, kind, "dead_letter", {"error": f"{type(e).__name__}: {e}"[:500]})
                self.bus.publish(uid, {"type": "run", "thread_id": thread, "kind": kind, "status": "dead_letter",
                                       "error": str(e)[:300]})

    async def _finish(self, uid: int, kind: str, thread: str) -> None:
        st = await self.graph(kind).aget_state({"configurable": {"thread_id": thread}})
        v = st.values or {}
        waiting = any(getattr(t, "interrupts", None) for t in (st.tasks or ()))
        status = "awaiting_approval" if waiting else v.get("status") or "done"
        summary = summarize(kind, v) | {"pending": waiting}
        db.upsert_run(thread, uid, kind, status, summary, job_id=v.get("job_id"),
                      market_thread_id=v.get("thread_id") if kind == "conversation" else None)
        if kind == "bid" and v.get("submission"):
            self._record_proposal(uid, thread, v, summary)
        self.bus.publish(uid, {"type": "run", "thread_id": thread, "kind": kind, "status": status,
                               "pending": waiting})

    def _record_proposal(self, uid: int, thread: str, v: dict, summary: dict) -> None:
        p = v["submission"]
        with db.engine().begin() as c:
            if c.execute(db.select(db.proposals.c.proposal_id).where(db.proposals.c.proposal_id == p["id"])).first():
                return
            c.execute(db.insert(db.proposals).values(
                proposal_id=p["id"], user_id=uid, thread_id=thread, job_id=v["job"]["id"], title=v["job"]["title"],
                category=v["job"].get("category"), stage="submitted", bid_amount=p.get("bid_amount"),
                connects=p.get("connects_spent") or v["quote"].connects_cost, usd=summary.get("usd"),
                latency_ms=summary.get("latency_ms"), updated_at=db.now()))
        self.bus.publish(uid, {"type": "pipeline", "proposal_id": p["id"], "stage": "submitted"})

    # ---------------------------------------------------------------- marketplace sync
    async def sync_user(self, uid: int) -> int:
        with db.engine().begin() as c:
            row = c.execute(db.select(db.sync_state).where(db.sync_state.c.user_id == uid)).first()
        after = row.last_event_id if row else 0
        events = (await self.call(uid, "scout", "marketplace.list_events", {"after_id": after}))["items"]
        if not events:
            return 0
        async with self.toolbox(uid) as tb:
            stage_of = {"proposal_viewed": "viewed", "client_replied": "replied", "interview_requested": "interview",
                        "hired": "hired", "proposal_lost": "lost"}
            order = ["submitted", "viewed", "replied", "interview", "hired", "lost"]
            for e in events:
                st = stage_of.get(e["type"])
                if st and e.get("proposal_id"):
                    with db.engine().begin() as c:
                        cur = c.execute(db.select(db.proposals.c.stage).where(
                            db.proposals.c.proposal_id == e["proposal_id"], db.proposals.c.user_id == uid)).first()
                        if cur and (st in ("hired", "lost") or order.index(st) > order.index(cur.stage)):
                            vals = {"stage": st, "updated_at": db.now()}
                            if e.get("thread_id"):
                                vals["market_thread_id"] = e["thread_id"]
                            c.execute(db.update(db.proposals).where(db.proposals.c.proposal_id == e["proposal_id"])
                                      .values(**vals))
                            self.bus.publish(uid, {"type": "pipeline", "proposal_id": e["proposal_id"], "stage": st})
                if e["type"] in ("client_replied", "client_message", "interview_requested") and e.get("thread_id"):
                    try:
                        th = await tb.call("liaison", "marketplace.list_messages", {"thread_id": e["thread_id"]})
                    except ToolFailed:
                        continue  # no auto-draft for this message; the user can still draft one from Messages
                    items = th["items"]
                    if items and items[0]["messages"]:
                        last = items[0]["messages"][-1]
                        if last.get("sender", last.get("from")) == "client":
                            await self.start_conversation(uid, e["thread_id"], len(items[0]["messages"]))
            await outcome_memory.ingest_events(self.store, f"u{uid}", events)
            await outcome_memory.promote(self.store, f"u{uid}")
        last = max([after] + [e["id"] for e in events])
        with db.engine().begin() as c:
            if row:
                c.execute(db.update(db.sync_state).where(db.sync_state.c.user_id == uid)
                          .values(last_event_id=last, last_run_at=db.now()))
            else:
                c.execute(db.insert(db.sync_state).values(user_id=uid, last_event_id=last, last_run_at=db.now()))
        return len(events)

    # ---------------------------------------------------------------- scheduled work (worker cron)
    @staticmethod
    def active_users() -> list[int]:
        with db.engine().begin() as c:
            uids = [r.id for r in c.execute(db.select(db.users.c.id))]
        return [u for u in uids if db.get_settings(u).get("onboarded")]

    async def sync_all(self) -> int:
        n = 0
        for uid in self.active_users():
            try:
                n += await self.sync_user(uid)
            except Exception as e:  # marketplace down: try again next tick, the banner shows it
                log.warning("sync u%s: %s", uid, e)
        return n

    @staticmethod
    def connects_spent_this_week(uid: int) -> int:
        week_start = db.now() - 7 * 86400
        with db.engine().begin() as c:
            rows = c.execute(db.select(db.proposals.c.connects).where(
                db.proposals.c.user_id == uid, db.proposals.c.updated_at >= week_start)).fetchall()
        return sum(r.connects or 0 for r in rows)

    async def scout_due(self, now: float | None = None) -> list[str]:
        """Run every saved search whose interval has elapsed (default: one search per category, hourly).
        Live mode never scouts more often than `marketplace.upwork_live.min_read_interval_s` (RUNBOOK)."""
        from agent.nodes.scout import scout
        from agent.settings import section
        now = now or db.now()
        started: list[str] = []
        wcfg = section("worker")
        for uid in self.active_users():
            s = db.get_settings(uid)
            if self.connects_spent_this_week(uid) >= (s.get("weekly_connects_budget") or 0):
                continue  # weekly Connects budget reached: no new drafts until it resets
            searches = s.get("saved_searches") or [
                {"name": f"category:{c}", "category": c, "interval_min": wcfg["default_interval_min"]}
                for c in (s.get("categories") or [])]
            floor_min = (section("marketplace")["upwork_live"]["min_read_interval_s"] / 60
                         if s.get("marketplace") == "upwork_live" else wcfg["min_interval_min"])
            last = dict(s.get("_scout_last") or {})
            with db.engine().begin() as c:
                seen = {r.job_id for r in c.execute(db.select(db.runs.c.job_id).where(db.runs.c.user_id == uid))}
            for srch in searches:
                every = max(float(srch.get("interval_min") or 60), floor_min) * 60
                if now - float(last.get(srch["name"], 0)) < every:
                    continue
                err, res = None, None
                async with self.toolbox(uid) as tb:
                    try:
                        res = await scout(tb, srch, seen, limit=wcfg["max_new_jobs_per_scout"])
                    except ToolFailed as e:
                        err = e
                if err or res is None:
                    log.warning("scout u%s %s: %s", uid, srch["name"], err)
                    continue
                last[srch["name"]] = now
                for jid in res.new_job_ids:
                    started.append(await self.start_bid(uid, jid))
                    seen.add(jid)
            db.put_settings(uid, {"_scout_last": last})
        return started

    async def _sync_forever(self) -> None:
        interval = float(os.getenv("GIGBID_SYNC_INTERVAL_S", "15"))
        while True:
            await asyncio.sleep(interval)
            with db.engine().begin() as c:
                uids = [r.id for r in c.execute(db.select(db.users.c.id))]
            for uid in uids:
                s = db.get_settings(uid)
                if not s.get("onboarded"):
                    continue
                try:
                    await self.sync_user(uid)
                except Exception as e:  # marketplace down: try again next tick, the banner shows it
                    log.warning("sync u%s: %s", uid, e)


def summarize(kind: str, v: dict) -> dict:
    """Small, JSON-safe digest of a run for the inbox and pipeline lists."""
    def dump(x):
        return x.model_dump() if hasattr(x, "model_dump") else x
    trace = v.get("trace", [])
    out = {"status": v.get("status"), "steps": v.get("steps", 0), "tokens": v.get("tokens", 0),
           "usd": round(v.get("usd", 0.0), 6),
           "latency_ms": round(sum(t.get("ms", 0) for t in trace if t.get("node") not in ("approval", "submit")), 1),
           "errors": v.get("errors", [])[-3:]}
    if kind == "bid":
        job, d, risk, fit, q = v.get("job") or {}, v.get("decision"), v.get("risk"), v.get("fit"), v.get("quote")
        out |= {"title": job.get("title"), "category": job.get("category"), "budget": job.get("budget"),
                "connects_cost": job.get("connects_cost"),
                "action": d.action if d else None, "confidence": d.confidence if d else None,
                "reasons": d.reasons if d else [], "coverage": fit.coverage if fit else None,
                "scam_score": risk.scam_score if risk else None, "scam_type": risk.scam_type if risk else None,
                "injection": risk.injection_detected if risk else False,
                "price": q.amount if q else None, "bid_type": q.bid_type if q else None,
                "critic": v["critiques"][-1].score if v.get("critiques") else None,
                "proposal_id": (v.get("submission") or {}).get("id")}
    else:
        it = v.get("intent")
        out |= {"market_thread_id": v.get("thread_id"), "intent": it.kind if it else None,
                "client_message": (v.get("client_message") or "")[:300], "job_title": (v.get("job") or {}).get("title")}
    return json.loads(db.dumps({k: dump(x) for k, x in out.items()}))


runtime = Runtime()
