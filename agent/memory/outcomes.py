"""Outcome memory (Part C2): what got replies or wins, per job category.

Pipeline, with an explicit rule at each step (raw tool output never goes straight into memory):

1. At submit, the bid graph stages the *features* of what was sent (category, price position vs the
   market, length bucket, opening style, evidence types cited). Namespace ("proposal_features", user).
2. `ingest_events` reads marketplace events (viewed / reply / hired / lost) and attaches the outcome to
   the staged features. Event payloads are not stored, only the outcome label.
3. `promote` aggregates per category. A category gets a memory entry once it has
   `memory.outcome.min_outcomes` resolved proposals; a feature value becomes a *lesson* only when its reply
   rate beats the category's by `memory.outcome.min_lift` with at least `min_support` proposals behind it.

Read side: `lessons(store, user, category)` -> used by Pricing (price position) and the Writer (notes).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from agent.settings import section

REPLIED = {"reply", "replied", "interview", "hired"}
# Marketplace event type -> outcome label (GigSim names; the Upwork adapter maps onto the same events).
EVENT_OUTCOME = {"proposal_viewed": "viewed", "client_replied": "reply", "interview_requested": "interview",
                 "hired": "hired", "proposal_lost": "lost"}
RESOLVED = REPLIED | {"lost"}


def features(state: dict) -> dict:
    q, d, job = state["quote"], state["draft"], state["job"]
    m = q.market or {}
    if m:
        pos = "below_p25" if q.amount < m["p25"] else "p25_p50" if q.amount <= m["p50"] else \
            "p50_p75" if q.amount <= m["p75"] else "above_p75"
    else:
        pos = "unknown"
    words = len(d.client_text().split())
    cited = sorted({i.split("-")[-2] for c in d.claims for i in c.evidence_ids})
    return {"category": job.get("category"), "price_position": pos,
            "length": "short" if words < 150 else "medium" if words <= 250 else "long",
            "opens_with_read_check": bool(state["spec"].read_check_word),
            "evidence_types": ",".join(cited) or "none", "job_id": job["id"]}


async def stage_submission(store, user: str, proposal_id: str, feats: dict) -> None:
    if store is not None:
        await store.aput(("proposal_features", user), proposal_id,
                         feats | {"outcome": None, "staged_at": datetime.now(timezone.utc).isoformat()})


async def ingest_events(store, user: str, events: list[dict]) -> int:
    """Attach outcomes from marketplace events to staged proposals. Returns how many changed."""
    changed = 0
    rank = {"viewed": 0, "lost": 1, "reply": 2, "interview": 3, "hired": 4}
    for e in events:
        pid, kind = e.get("proposal_id"), EVENT_OUTCOME.get(e.get("type"), e.get("type"))
        if not pid or kind not in rank:
            continue
        cur = await store.aget(("proposal_features", user), pid)
        if not cur:
            continue  # not a proposal GigBid sent: ignore, never store foreign data
        v = dict(cur.value)
        if v["outcome"] is None or rank[kind] > rank.get(v["outcome"], -1):
            v["outcome"] = kind
            await store.aput(("proposal_features", user), pid, v)
            changed += 1
    return changed


async def promote(store, user: str) -> dict[str, dict]:
    cfg = section("memory")["outcome"]
    rows = [i.value for i in await store.asearch(("proposal_features", user), limit=10_000)]
    by_cat: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if r.get("outcome") in RESOLVED and r.get("category"):
            by_cat[r["category"]].append(r)
    out = {}
    for cat, rs in by_cat.items():
        if len(rs) < cfg["min_outcomes"]:
            continue
        base = sum(r["outcome"] in REPLIED for r in rs) / len(rs)
        lessons = []
        for feat in ("price_position", "length", "evidence_types", "opens_with_read_check"):
            groups = defaultdict(list)
            for r in rs:
                groups[str(r[feat])].append(r["outcome"] in REPLIED)
            for val, hits in groups.items():
                if len(hits) >= cfg["min_support"]:
                    rate = sum(hits) / len(hits)
                    if rate - base >= cfg["min_lift"]:
                        lessons.append({"feature": feat, "value": val, "reply_rate": round(rate, 3), "n": len(hits)})
        entry = {"category": cat, "n": len(rs), "reply_rate": round(base, 3),
                 "won": sum(r["outcome"] == "hired" for r in rs),
                 "lessons": sorted(lessons, key=lambda x: -x["reply_rate"]),
                 "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        await store.aput(("outcome", user), cat, entry)
        out[cat] = entry
    return out


async def lessons(store, user: str, category: str | None) -> dict | None:
    if store is None or not category:
        return None
    item = await store.aget(("outcome", user), category)
    return item.value if item else None


def price_hint(entry: dict | None) -> str | None:
    """The price position that worked best in this category, if memory has learned one."""
    if not entry:
        return None
    best = next((l for l in entry["lessons"] if l["feature"] == "price_position"), None)
    return best["value"] if best else None


def notes(entry: dict | None) -> str:
    if not entry or not entry["lessons"]:
        return ""
    parts = [f"{l['feature'].replace('_', ' ')} = {l['value']} (reply rate {l['reply_rate']:.0%}, n={l['n']})"
             for l in entry["lessons"][:3]]
    return f"In {entry['category']}, what got replies before: " + "; ".join(parts) + "."
