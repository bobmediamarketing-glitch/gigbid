"""CI rule: every number in README.md and the report traces to a file in evals/results/.

Numbers to check live between `<!-- results:start -->` and `<!-- results:end -->` markers (the README's
results section, the report's results chapter). Each decimal or percentage there must appear in some file
under evals/results/ (as written, or as the matching fraction: "93.8%" matches 0.938).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCS = ["README.md", "docs/REPORT.md"]
NUM = re.compile(r"(?<![\w.])(\d+\.\d+|\d+(?:\.\d+)?%)(?![\w.])")


def corpus() -> str:
    return "\n".join(f.read_text(encoding="utf-8", errors="ignore")
                     for f in (ROOT / "evals" / "results").rglob("*") if f.is_file() and f.suffix in (".json", ".md", ".csv"))


def variants(n: str) -> list[str]:
    if n.endswith("%"):
        v = float(n[:-1]) / 100
        return [n, f"{v:.3f}", f"{v:.4f}".rstrip("0"), f"{v:.2f}", str(round(v, 4))]
    v = float(n)
    return [n, f"{v:.3f}", f"{v:.2f}", str(round(v, 4))]


def main() -> int:
    blob, bad, seen = corpus(), [], 0
    for doc in DOCS:
        p = ROOT / doc
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8")
        for block in re.findall(r"<!-- results:start -->(.*?)<!-- results:end -->", text, re.S):
            for n in NUM.findall(block):
                seen += 1
                if not any(v in blob for v in variants(n)):
                    bad.append(f"{doc}: {n} not found in evals/results/")
    for line in bad:
        print("FAIL", line)
    print(f"numbers check: {seen} number(s) checked, {len(bad)} untraceable")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
