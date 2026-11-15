"""Metric definitions used by every eval runner (one place, so the report and CI agree)."""
from __future__ import annotations

import math
from collections import Counter


def recall_at_k(ranked: list[str], gold: set[str], k: int) -> float:
    """Capped recall: gold items in the top k / min(k, |gold|), so a perfect ranker scores 1.0 even when
    more than k items are relevant (gold sets here have a median of ~30 items)."""
    return len(set(ranked[:k]) & gold) / min(k, len(gold)) if gold else 0.0


def mrr(ranked: list[str], gold: set[str]) -> float:
    for i, d in enumerate(ranked, 1):
        if d in gold:
            return 1.0 / i
    return 0.0


def ndcg_at_k(ranked: list[str], rel: dict[str, float], k: int) -> float:
    dcg = sum((2 ** rel.get(d, 0) - 1) / math.log2(i + 2) for i, d in enumerate(ranked[:k]))
    ideal = sorted(rel.values(), reverse=True)[:k]
    idcg = sum((2 ** r - 1) / math.log2(i + 2) for i, r in enumerate(ideal))
    return dcg / idcg if idcg else 0.0


def prf(pred: list[bool], gold: list[bool]) -> dict[str, float]:
    tp = sum(p and g for p, g in zip(pred, gold))
    fp = sum(p and not g for p, g in zip(pred, gold))
    fn = sum(g and not p for p, g in zip(pred, gold))
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    return {"precision": round(p, 4), "recall": round(r, 4), "f1": round(2 * p * r / (p + r) if p + r else 0.0, 4),
            "tp": tp, "fp": fp, "fn": fn, "n": len(gold)}


def cohen_kappa(a: list, b: list, weights: str | None = None, labels: list | None = None) -> float:
    """Cohen's kappa; weights='quadratic' for ordinal rubric scores (1-5)."""
    assert len(a) == len(b) and a
    labels = labels or sorted(set(a) | set(b))
    idx = {l: i for i, l in enumerate(labels)}
    n, m = len(a), len(labels)
    ca, cb = Counter(a), Counter(b)

    def w(i, j):
        if weights == "quadratic":
            return ((i - j) ** 2) / ((m - 1) ** 2) if m > 1 else 0.0
        return 0.0 if i == j else 1.0
    obs = sum(w(idx[x], idx[y]) for x, y in zip(a, b)) / n
    exp = sum(ca[li] * cb[lj] * w(idx[li], idx[lj]) for li in labels for lj in labels) / (n * n)
    return round(1 - obs / exp, 4) if exp else 1.0


def pct(xs: list[float], q: float) -> float:
    if not xs:
        return 0.0
    xs = sorted(xs)
    k = (len(xs) - 1) * q
    f = int(k)
    c = min(f + 1, len(xs) - 1)
    return round(xs[f] + (xs[c] - xs[f]) * (k - f), 2)


def mean(xs) -> float:
    xs = list(xs)
    return round(sum(xs) / len(xs), 4) if xs else 0.0
