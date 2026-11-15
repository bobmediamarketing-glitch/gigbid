"""Claim verification (R5): every factual sentence in a proposal must be backed by cited evidence.

A sentence is checked when it cites an evidence id or states a metric (percentages, money,
"N years", "Nx", "Nk"). It is supported only if every id it cites is in the evidence pack
and every metric it states appears in the text of a cited item (or, with no citation, in
any item). Unsupported sentences are removed from the draft and reported, so the human
reviewer and the Critic see exactly what was cut and why.
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
    removed: list[dict] = field(default_factory=list)  # {sentence, reason}

    @property
    def rate(self) -> float:
        return self.supported / self.checked if self.checked else 1.0


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s.lower())


def check_sentence(sent: str, evidence: dict[str, str]) -> tuple[bool | None, str]:
    ids = CITE.findall(sent)
    metrics = METRIC.findall(sent.replace(",", ""))
    if not ids and not metrics:
        return None, "no factual claim"
    unknown = [i for i in ids if i not in evidence]
    if unknown:
        return False, f"cites unknown evidence {unknown}"
    pool = " ".join(evidence[i] for i in ids) if ids else " ".join(evidence.values())
    pool_n = _norm(pool.replace(",", ""))
    missing = [m for m in metrics if _norm(m) not in pool_n]
    if missing:
        return False, f"metric {missing} not in {'cited evidence' if ids else 'any evidence'}"
    return True, "supported"


def verify_text(text: str, evidence: dict[str, str]) -> tuple[str, Verification]:
    v = Verification()
    out_paras = []
    for para in text.split("\n\n"):
        keep = []
        for s in SENT.split(para.strip()):
            ok, why = check_sentence(s, evidence)
            if ok is None:
                keep.append(s)
                continue
            v.checked += 1
            if ok:
                v.supported += 1
                keep.append(s)
            else:
                v.removed.append({"sentence": s, "reason": why})
        if keep:
            out_paras.append(" ".join(keep))
    return "\n\n".join(out_paras), v
