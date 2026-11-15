"""Claim verification (Part B3, R5): every factual sentence in a proposal must be backed by cited evidence.

A sentence is a claim when it cites an evidence id or states a metric (percentages, money,
"N years", "Nx", "Nk"). Each claim gets one label:

- supported        every cited id is in the evidence pack and every metric appears in a cited item
                   (or, with no citation, in some item);
- partly supported at least one cited id is real and backs every metric, but other cited ids are
                   unknown -> rewritten by dropping the unknown citations;
- unsupported      anything else (unknown source only, or a metric the evidence does not contain)
                   -> removed.

The rates before and after are reported, and after must be zero: the verifier re-checks its own output.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

CITE = re.compile(r"\[([a-z_]+-(?:cs|repo|rev|prop)-\d+)\]")
METRIC = re.compile(r"\d+(?:\.\d+)?\s?%|\$\s?\d[\d,]*(?:\.\d+)?k?|\b\d+\+?\s+years?\b|\b\d+(?:\.\d+)?x\b|\b\d+k\b",
                    re.I)
SENT = re.compile(r"(?<=[.!?\"])\s+(?=[A-Z\"])")


@dataclass
class Verification:
    checked: int = 0
    supported: int = 0
    partly: int = 0
    unsupported: int = 0
    removed: list[dict] = field(default_factory=list)    # {sentence, reason}
    rewritten: list[dict] = field(default_factory=list)  # {before, after, reason}
    unsupported_after: int = 0

    @property
    def rate(self) -> float:
        return self.supported / self.checked if self.checked else 1.0

    def merge(self, o: "Verification") -> None:
        for k in ("checked", "supported", "partly", "unsupported", "unsupported_after"):
            setattr(self, k, getattr(self, k) + getattr(o, k))
        self.removed += o.removed
        self.rewritten += o.rewritten

    def summary(self) -> dict:
        return {"checked": self.checked, "supported": self.supported, "partly": self.partly,
                "unsupported": self.unsupported, "unsupported_after": self.unsupported_after,
                "removed": self.removed, "rewritten": self.rewritten}


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s.lower().replace(",", ""))


def _metrics_in(metrics: list[str], text: str) -> list[str]:
    pool = _norm(text)
    return [m for m in metrics if _norm(m) not in pool]


def check_sentence(sent: str, evidence: dict[str, str]) -> tuple[bool | None, str]:
    """Back-compatible binary check: True supported, False not fully supported, None not a claim."""
    label, why, _ = classify(sent, evidence)
    return (None if label is None else label == "supported"), why


def classify(sent: str, evidence: dict[str, str]) -> tuple[str | None, str, str]:
    """Returns (label, reason, rewritten_sentence)."""
    ids = CITE.findall(sent)
    metrics = METRIC.findall(sent.replace(",", ""))
    if not ids and not metrics:
        return None, "no factual claim", sent
    known = [i for i in ids if i in evidence]
    unknown = [i for i in ids if i not in evidence]
    if ids and not known:
        return "unsupported", f"cites unknown evidence {unknown}", sent
    pool = " ".join(evidence[i] for i in known) if known else " ".join(evidence.values())
    missing = _metrics_in(metrics, pool)
    if missing:
        return "unsupported", f"metric {missing} not in {'cited evidence' if known else 'any evidence'}", sent
    if unknown:
        fixed = re.sub(r"\s?\[(" + "|".join(map(re.escape, unknown)) + r")\]", "", sent)
        return "partly", f"dropped unknown citations {unknown}", fixed
    return "supported", "supported", sent


def verify_text(text: str, evidence: dict[str, str]) -> tuple[str, Verification]:
    v = Verification()
    out_paras = []
    for para in text.split("\n\n"):
        keep = []
        for s in SENT.split(para.strip()):
            label, why, fixed = classify(s, evidence)
            if label is None:
                keep.append(s)
                continue
            v.checked += 1
            if label == "supported":
                v.supported += 1
                keep.append(s)
            elif label == "partly":
                v.partly += 1
                v.rewritten.append({"before": s, "after": fixed, "reason": why})
                keep.append(fixed)
            else:
                v.unsupported += 1
                v.removed.append({"sentence": s, "reason": why})
        if keep:
            out_paras.append(" ".join(keep))
    out = "\n\n".join(out_paras)
    # Re-check the output: anything still unsupported is a verifier bug and is counted, not hidden.
    v.unsupported_after = sum(1 for p in out.split("\n\n") for s in SENT.split(p.strip())
                              if classify(s, evidence)[0] == "unsupported")
    return out, v
