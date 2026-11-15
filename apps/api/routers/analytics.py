"""Analytics and health."""
from __future__ import annotations

from fastapi import APIRouter

from apps.api import db
from apps.api.auth import User
from apps.api.runtime import runtime
from collections import Counter, defaultdict

from agent.llm import profile_name
from agent.mcp_client import ToolFailed
from apps.api.schemas import Analytics, CategoryStat, Health

router = APIRouter(prefix="/api", tags=["analytics"])
REPLIED = {"replied", "interview", "hired"}


@router.get("/analytics", response_model=Analytics)
def analytics(u: dict = User) -> Analytics:
    with db.engine().begin() as c:
        props = c.execute(db.select(db.proposals).where(db.proposals.c.user_id == u["id"])).fetchall()
        rejects = c.execute(db.select(db.approvals.c.note).where(db.approvals.c.user_id == u["id"],
                                                                 db.approvals.c.action == "reject")).fetchall()
        skips = c.execute(db.select(db.runs.c.summary).where(db.runs.c.user_id == u["id"], db.runs.c.kind == "bid",
                                                             db.runs.c.status.in_(["skipped", "skip_suggested"]))).fetchall()
    by = defaultdict(list)
    for p in props:
        by[p.category or "other"].append(p)
    cats = []
    for cat, ps in sorted(by.items()):
        rep = sum(p.stage in REPLIED for p in ps)
        hires = sum(p.stage == "hired" for p in ps)
        cats.append(CategoryStat(category=cat, proposals=len(ps), replies=rep, hires=hires,
                                 reply_rate=round(rep / len(ps), 3), hire_rate=round(hires / len(ps), 3),
                                 connects=sum(p.connects or 0 for p in ps)))
    n = len(props)
    reasons = Counter()
    for (s,) in skips:
        for r in (s or {}).get("reasons", [])[:1]:
            reasons[r.split("(")[0].strip()] += 1
    rej = Counter((note or "").strip().lower()[:80] for (note,) in rejects if note)
    return Analytics(
        proposals=n, reply_rate=round(sum(p.stage in REPLIED for p in props) / n, 3) if n else 0.0,
        hire_rate=round(sum(p.stage == "hired" for p in props) / n, 3) if n else 0.0,
        connects_spent=sum(p.connects or 0 for p in props),
        connects_on_replied=sum(p.connects or 0 for p in props if p.stage in REPLIED),
        avg_usd_per_proposal=round(sum(p.usd or 0 for p in props) / n, 5) if n else 0.0,
        avg_latency_s=round(sum(p.latency_ms or 0 for p in props) / n / 1000, 2) if n else 0.0,
        by_category=cats, rejection_reasons=[{"reason": k, "count": v} for k, v in rej.most_common(8)],
        skip_reasons=[{"reason": k, "count": v} for k, v in reasons.most_common(8)])


@router.get("/health", response_model=Health)
async def health(u: dict = User) -> Health:
    s = db.get_settings(u["id"])
    ok, detail = True, None
    try:
        h = await runtime.call(u["id"], "scout", "marketplace.list_events", {"after_id": 10 ** 9})
        ok = h is not None
    except ToolFailed as e:
        ok, detail = False, str(e)[:200]
    except Exception as e:  # any transport problem counts as unavailable for the banner
        ok, detail = False, f"{type(e).__name__}: {e}"[:200]
    with db.engine().begin() as c:
        row = c.execute(db.select(db.sync_state.c.last_run_at).where(db.sync_state.c.user_id == u["id"])).first()
    return Health(marketplace_ok=ok, marketplace_mode=s.get("marketplace", "gigsim"), marketplace_detail=detail,
                  llm_available=runtime.llm.available,
                  model_profile=profile_name() if runtime.llm.available else "rules (no API key)",
                  sync_last_run=row.last_run_at if row else None)
