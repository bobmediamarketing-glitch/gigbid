"""Application database (users, settings, run index, pipeline, approvals). SQLAlchemy Core, so the
same code runs on SQLite locally and Postgres in production (APP_DATABASE_URL / DATABASE_URL).

LangGraph's checkpointer and memory store keep their own tables; this database only indexes runs so
the inbox and pipeline can list them quickly. The checkpoint stays the source of truth for run state.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from sqlalchemy import (JSON, Column, Float, ForeignKey, Integer, MetaData, String, Table, Text, create_engine,
                        delete, insert, select, update)
from sqlalchemy.engine import Engine

ROOT = Path(__file__).resolve().parents[2]
meta = MetaData()

users = Table("users", meta,
              Column("id", Integer, primary_key=True, autoincrement=True),
              Column("email", String(200), unique=True, nullable=False),
              Column("name", String(120), nullable=False),
              Column("password_hash", String(300), nullable=False),
              Column("created_at", Float, nullable=False))

settings = Table("settings", meta,
                 Column("user_id", Integer, ForeignKey("users.id"), primary_key=True),
                 Column("data", JSON, nullable=False))

secrets = Table("secrets", meta,  # encrypted OAuth tokens (Fernet), never returned by the API
                Column("user_id", Integer, ForeignKey("users.id"), primary_key=True),
                Column("kind", String(40), primary_key=True),
                Column("ciphertext", Text, nullable=False),
                Column("updated_at", Float, nullable=False))

runs = Table("runs", meta,
             Column("thread_id", String(80), primary_key=True),
             Column("user_id", Integer, ForeignKey("users.id"), nullable=False, index=True),
             Column("kind", String(20), nullable=False),            # bid | conversation
             Column("job_id", String(40), index=True),
             Column("market_thread_id", String(80), index=True),
             Column("status", String(40), nullable=False),
             Column("summary", JSON, nullable=False),               # decision, fit, risk, price, title ...
             Column("created_at", Float, nullable=False),
             Column("updated_at", Float, nullable=False))

proposals = Table("proposals", meta,
                  Column("proposal_id", String(40), primary_key=True),
                  Column("user_id", Integer, ForeignKey("users.id"), nullable=False, index=True),
                  Column("thread_id", String(80)),
                  Column("job_id", String(40)),
                  Column("title", String(300)),
                  Column("category", String(80)),
                  Column("stage", String(20), nullable=False),     # submitted viewed replied interview hired lost
                  Column("bid_amount", Float),
                  Column("connects", Integer),
                  Column("usd", Float),
                  Column("latency_ms", Float),
                  Column("market_thread_id", String(80)),
                  Column("updated_at", Float, nullable=False))

approvals = Table("approvals", meta,
                  Column("id", Integer, primary_key=True, autoincrement=True),
                  Column("user_id", Integer, ForeignKey("users.id"), nullable=False, index=True),
                  Column("thread_id", String(80), nullable=False, index=True),
                  Column("action", String(10), nullable=False),
                  Column("note", Text),
                  Column("before", Text),
                  Column("after", Text),
                  Column("at", Float, nullable=False))

sync_state = Table("sync_state", meta,
                   Column("user_id", Integer, ForeignKey("users.id"), primary_key=True),
                   Column("last_event_id", Integer, nullable=False, default=0),
                   Column("last_run_at", Float))

_engine: Engine | None = None


def engine() -> Engine:
    global _engine
    if _engine is None:
        pg = os.getenv("DATABASE_URL", "")
        url = os.getenv("APP_DATABASE_URL") or (pg if pg.startswith("postgres") else "")
        if url.startswith("postgres"):
            url = url.replace("postgresql://", "postgresql+psycopg://", 1).replace("postgres://", "postgresql+psycopg://", 1)
        else:
            path = url.removeprefix("sqlite:///") if url.startswith("sqlite") else str(ROOT / "data" / "app.sqlite")
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            url = f"sqlite:///{path}"
        _engine = create_engine(url, future=True, pool_pre_ping=True,
                                connect_args={"check_same_thread": False} if url.startswith("sqlite") else {})
        meta.create_all(_engine)
    return _engine


def reset_engine() -> None:
    global _engine
    _engine = None


def now() -> float:
    return time.time()


DEFAULT_SETTINGS = {
    "onboarded": False, "profile_mode": "persona", "persona": None, "own_profile": None,
    "marketplace": "gigsim", "gigsim_account": None, "autonomy": "suggest", "weekly_connects_budget": 60,
    "hourly_floor": None, "fixed_floor": None, "categories": [],
    "saved_searches": [], "upwork_connected": False,
}


def get_settings(uid: int) -> dict:
    with engine().begin() as c:
        row = c.execute(select(settings.c.data).where(settings.c.user_id == uid)).first()
    return DEFAULT_SETTINGS | (row[0] if row else {})


def put_settings(uid: int, data: dict) -> dict:
    merged = get_settings(uid) | data
    with engine().begin() as c:
        if c.execute(select(settings.c.user_id).where(settings.c.user_id == uid)).first():
            c.execute(update(settings).where(settings.c.user_id == uid).values(data=merged))
        else:
            c.execute(insert(settings).values(user_id=uid, data=merged))
    return merged


def upsert_run(thread_id: str, uid: int, kind: str, status: str, summary: dict, job_id: str | None = None,
               market_thread_id: str | None = None) -> None:
    with engine().begin() as c:
        row = c.execute(select(runs.c.summary).where(runs.c.thread_id == thread_id)).first()
        if row:
            c.execute(update(runs).where(runs.c.thread_id == thread_id).values(
                status=status, summary=(row[0] or {}) | summary, updated_at=now()))
        else:
            c.execute(insert(runs).values(thread_id=thread_id, user_id=uid, kind=kind, job_id=job_id,
                                          market_thread_id=market_thread_id, status=status, summary=summary,
                                          created_at=now(), updated_at=now()))


def dumps(x) -> str:
    return json.dumps(x, default=str)


__all__ = ["engine", "users", "settings", "secrets", "runs", "proposals", "approvals", "sync_state", "get_settings",
           "put_settings", "upsert_run", "select", "insert", "update", "delete", "now"]
