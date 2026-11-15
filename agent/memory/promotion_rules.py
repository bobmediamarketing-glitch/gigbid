"""The explicit rules that decide what becomes long-term memory (C2). Thresholds live in config.

Nothing a tool returns is written to memory directly. Each store goes through one of these gates:

- Style memory: an edit pattern becomes a rule only after it appears in `promote_after`
  separate edits (one edit is a preference for one job, not a style).
- Outcome memory: a category is remembered only after `min_outcomes` resolved proposals,
  and a feature becomes a lesson only with `min_support` proposals behind it and a reply
  rate at least `min_lift` above the category's.
"""
from __future__ import annotations

from agent.settings import section


def style_cfg() -> dict:
    return section("memory")["style"]


def outcome_cfg() -> dict:
    return section("memory")["outcome"]


def style_rule_qualifies(times_seen: int) -> bool:
    return times_seen >= style_cfg()["promote_after"]


def category_qualifies(resolved: int) -> bool:
    return resolved >= outcome_cfg()["min_outcomes"]


def lesson_qualifies(support: int, rate: float, base_rate: float) -> bool:
    c = outcome_cfg()
    return support >= c["min_support"] and rate - base_rate >= c["min_lift"]
