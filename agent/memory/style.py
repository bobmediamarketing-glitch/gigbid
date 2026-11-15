"""Style memory (Part C2): what the user's own edits teach about how they want to sound.

Raw edits never become memory directly. Each approved edit is diffed into *observations*
(cut the first sentence, removed a phrase, made it much shorter, ...), kept in a staging
namespace with a count. An observation is promoted to a *rule* only when it has been seen in
`memory.style.promote_after` separate edits. Rules are what the Writer reads; the user can list
and delete them (Settings -> memory viewer).

Namespaces (per user):
    ("style_obs", user)  -> staging: {kind, value, count, examples, first_seen, last_seen}
    ("style", user)      -> promoted rules: same fields + promoted_at
"""
from __future__ import annotations

import difflib
import re
from datetime import datetime, timezone

from agent.memory.promotion_rules import style_rule_qualifies

SENT = re.compile(r"(?<=[.!?])\s+")
WORD = re.compile(r"[a-z][a-z'-]+")
# Words too common to learn "never say X" from.
STOP = set("""a an and are as at be but by for from has have i i'm in is it its of on or our so that the this
to was we will with you your my me can would could should just very also then than""".split())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sentences(t: str) -> list[str]:
    return [s.strip() for s in SENT.split(t.strip()) if s.strip()]


def observe(before: str, after: str) -> list[dict]:
    """Diff one edit into observations. Pure function (unit-tested)."""
    obs: list[dict] = []
    b, a = _sentences(before), _sentences(after)
    if not b or not a:
        return obs
    if len(b) > 1 and b[0] not in after and b[1][:40] in after:
        obs.append({"kind": "cut_first_sentence", "value": "cut the first sentence",
                    "example": b[0][:160]})
    bw, aw = WORD.findall(before.lower()), WORD.findall(after.lower())
    removed = {w for w in set(bw) - set(aw) if w not in STOP and len(w) > 3}
    # A removed word only counts as a style signal when the sentence around it survived (the user
    # deleted the word, not a whole paragraph for content reasons).
    for w in sorted(removed):
        ctx = next((s for s in b if re.search(rf"\b{re.escape(w)}\b", s.lower())), "")
        if ctx and difflib.SequenceMatcher(None, ctx, after).find_longest_match().size > len(ctx) * 0.4:
            obs.append({"kind": "avoid_phrase", "value": w, "example": ctx[:160]})
    cut = any(o["kind"] == "cut_first_sentence" for o in obs)
    base_len = len(before) - (len(b[0]) if cut else 0)  # shortening explained by the cut is not counted twice
    if len(after) < 0.75 * base_len:
        obs.append({"kind": "prefer_shorter", "value": f"keep it under {max(80, len(aw) // 10 * 10 + 10)} words",
                    "example": f"{len(bw)} -> {len(aw)} words"})
    def is_new(s: str) -> bool:  # genuinely new text, not an edited version of an old sentence
        return s not in before and all(difflib.SequenceMatcher(None, s, x).ratio() < 0.6 for x in b)
    if is_new(a[-1]) and len(a[-1]) < 120:
        obs.append({"kind": "closing_line", "value": a[-1], "example": a[-1]})
    return obs


def _key(o: dict) -> str:
    return f"{o['kind']}:{re.sub(r'[^a-z0-9]+', '_', o['value'].lower())[:60]}"


async def record_edit(store, user: str, before: str, after: str) -> list[dict]:
    """Stage observations from one edit and promote the ones that crossed the threshold.
    Returns the rules promoted by this edit."""
    if store is None or before.strip() == after.strip():
        return []
    promoted = []
    for o in observe(before, after):
        k = _key(o)
        cur = await store.aget(("style_obs", user), k)
        v = dict(cur.value) if cur else {"kind": o["kind"], "value": o["value"], "count": 0, "examples": [],
                                         "first_seen": _now()}
        v["count"] += 1
        v["last_seen"] = _now()
        v["examples"] = (v["examples"] + [o["example"]])[-3:]
        await store.aput(("style_obs", user), k, v)
        if style_rule_qualifies(v["count"]) and not await store.aget(("style", user), k):
            rule = v | {"promoted_at": _now()}
            await store.aput(("style", user), k, rule)
            promoted.append(rule)
    return promoted


async def rules(store, user: str) -> list[dict]:
    if store is None:
        return []
    return [i.value | {"key": i.key} for i in await store.asearch(("style", user), limit=100)]


async def forget(store, user: str, key: str) -> None:
    """User deleted a rule in the memory viewer: drop the rule and its staging so it is not re-learned
    from the same old edits."""
    await store.adelete(("style", user), key)
    await store.adelete(("style_obs", user), key)


def as_instructions(rs: list[dict]) -> str:
    if not rs:
        return ""
    lines = []
    for r in rs:
        if r["kind"] == "avoid_phrase":
            lines.append(f"never use the word '{r['value']}'")
        elif r["kind"] == "closing_line":
            lines.append(f"end with a line like: {r['value']}")
        else:
            lines.append(r["value"])
    return "The freelancer's learned style rules: " + "; ".join(lines) + "."


def apply(text: str, rs: list[dict], keep_first_word: str | None = None) -> str:
    """Deterministic post-pass so learned rules hold even on the rule path (no LLM)."""
    for r in rs:
        if r["kind"] == "avoid_phrase":
            parts = _sentences(text)
            text = " ".join(s for s in parts if not re.search(rf"\b{re.escape(r['value'])}\b", s, re.I)) or text
    if any(r["kind"] == "cut_first_sentence" for r in rs):
        paras = text.split("\n\n")
        s = _sentences(paras[0])
        if len(s) > 1 or len(paras) > 1:
            lead = f"{keep_first_word.capitalize()}. " if keep_first_word and s and \
                s[0].lower().startswith(keep_first_word.lower()) else ""
            rest = s[1:] if len(s) > 1 else []
            paras[0] = (lead + " ".join(rest)).strip()
            text = "\n\n".join(p for p in paras if p)
    closing = next((r for r in rs if r["kind"] == "closing_line"), None)
    if closing and closing["value"] not in text:
        text = text.rstrip() + "\n\n" + closing["value"]
    return text
