"""Create (or reset) the reviewer account on a deployment, preloaded with a persona (E6).

    REVIEWER_EMAIL=... REVIEWER_PASSWORD=... python -m apps.api.seed_reviewer [--persona ai_ml] [--analyse 6]

Credentials come only from the environment and are never printed or written to the repo; share them in
the private Google Classroom comment. `--analyse N` runs the bid graph on N fresh jobs so the inbox,
studio and pipeline have content the moment the reviewer signs in.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

from apps.api import db
from apps.api.auth import hash_password


def upsert_user(email: str, password: str, name: str) -> int:
    with db.engine().begin() as c:
        row = c.execute(db.select(db.users.c.id).where(db.users.c.email == email.lower())).first()
        if row:
            c.execute(db.update(db.users).where(db.users.c.id == row.id).values(password_hash=hash_password(password)))
            return row.id
        return c.execute(db.insert(db.users).values(email=email.lower(), name=name, password_hash=hash_password(password),
                                                    created_at=db.now())).inserted_primary_key[0]


async def analyse(uid: int, n: int) -> None:
    from apps.api.runtime import Runtime
    rt = Runtime()
    os.environ["GIGBID_SYNC"] = "0"
    await rt.start(role="api")
    try:
        threads = []
        for cat in db.get_settings(uid).get("categories") or [None]:
            res = await rt.call(uid, "scout", "marketplace.search_jobs", {"category": cat, "limit": 5})
            for j in res["items"][: max(1, n // 2)]:
                threads.append(await rt.start_bid(uid, j["id"], j["title"]))
            if len(threads) >= n:
                break
        if rt.queue is not None:
            print(f"queued {len(threads)} jobs; the worker analyses them in the next minute or two")
        else:
            for t in list(rt.tasks.values()):
                await t
            print(f"analysed {len(threads)} jobs for the reviewer")
    finally:
        await rt.stop()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--persona", default="ai_ml", choices=["ai_ml", "fullstack", "data_analyst"])
    ap.add_argument("--analyse", type=int, default=0)
    a = ap.parse_args()
    email, password = os.getenv("REVIEWER_EMAIL"), os.getenv("REVIEWER_PASSWORD")
    if not email or not password or len(password) < 12:
        print("set REVIEWER_EMAIL and REVIEWER_PASSWORD (12+ characters) in the environment", file=sys.stderr)
        return 2
    uid = upsert_user(email, password, "Reviewer")
    import json
    prof = json.loads((db.ROOT / "data" / "personas" / a.persona / "profile.json").read_text(encoding="utf-8"))
    db.put_settings(uid, {"onboarded": True, "profile_mode": "persona", "persona": a.persona,
                          "gigsim_account": a.persona, "marketplace": "gigsim", "categories": prof["categories"][:3],
                          "hourly_floor": prof["hourly_floor"], "fixed_floor": prof["fixed_floor"],
                          "weekly_connects_budget": 60, "autonomy": "suggest"})
    print(f"reviewer account ready (user id {uid}, persona {a.persona})")  # never print the credentials
    if a.analyse:
        asyncio.run(analyse(uid, a.analyse))
    return 0


if __name__ == "__main__":
    sys.exit(main())
