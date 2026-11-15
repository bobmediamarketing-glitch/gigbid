"""CI eval gate (E2): a 30-job smoke eval that fails the build if quality drops past evals/thresholds.json.

    python scripts/ci/eval_gate.py               # runs the smoke evals into a temp dir, then checks
    python scripts/ci/eval_gate.py --check DIR   # only check results already in DIR

Fails if retrieval Recall@5 / nDCG@10, bid-or-skip F1, scam recall or price-in-band drop below their floors,
or if unsupported claims per proposal rise above their ceilings.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def run_smoke(out: Path) -> None:
    env = {**os.environ, "GIGBID_RESULTS_DIR": str(out), "PYTHONPATH": str(ROOT)}
    v = json.loads((ROOT / "evals" / "thresholds.json").read_text())["retrieval"]["variant"]
    for args in (["evals.runners.rag_eval", "--variants", v, "--limit", "10"],
                 ["evals.runners.decision_eval", "--variants", v, "--limit", "10"],
                 ["evals.runners.gigsim_outcomes", "--variants", v, "--n", "4"]):
        print("$ python -m", " ".join(args), flush=True)
        subprocess.run([sys.executable, "-m", *args], cwd=ROOT, env=env, check=True,
                       stdout=subprocess.DEVNULL if os.getenv("CI_QUIET") else None)


def check(out: Path) -> int:
    t = json.loads((ROOT / "evals" / "thresholds.json").read_text())
    v = t["retrieval"]["variant"]
    ret = json.loads((out / "retrieval.json").read_text())["results"][v]["overall"]
    dec = json.loads((out / "decisions.json").read_text())["results"][v]["overall"]
    outc = json.loads((out / "outcomes.json").read_text())["results"][v]["overall"]
    checks = [
        ("retrieval Recall@5", ret["recall@5"], ">=", t["retrieval"]["min_recall@5"]),
        ("retrieval nDCG@10", ret["ndcg@10"], ">=", t["retrieval"]["min_ndcg@10"]),
        ("bid-or-skip F1", dec["bid"]["f1"], ">=", t["decisions"]["min_bid_f1"]),
        ("scam recall", dec["scam"]["recall"], ">=", t["decisions"]["min_scam_recall"]),
        ("price in fair band", dec["price_in_band"], ">=", t["decisions"]["min_price_in_band"]),
        ("unsupported claims / proposal (before)", outc["unsupported_claims_per_proposal_before"], "<=",
         t["outcomes"]["max_unsupported_claims_per_proposal_before"]),
        ("unsupported claims / proposal (after)", outc["unsupported_claims_per_proposal_after"], "<=",
         t["outcomes"]["max_unsupported_claims_per_proposal_after"]),
    ]
    failed = 0
    for name, val, op, lim in checks:
        ok = val >= lim if op == ">=" else val <= lim
        failed += not ok
        print(f"{'PASS' if ok else 'FAIL'}  {name:42s} {val:.3f} {op} {lim}")
    summary = {"variant": v, "checks": [{"name": n, "value": val, "op": op, "limit": lim} for n, val, op, lim in checks],
               "failed": failed}
    (out / "eval_gate.json").write_text(json.dumps(summary, indent=1))
    print(f"eval gate: {'FAILED' if failed else 'passed'} ({failed} of {len(checks)} checks failed)")
    return 1 if failed else 0


def main() -> int:
    if "--check" in sys.argv:
        return check(Path(sys.argv[sys.argv.index("--check") + 1]))
    out = Path(os.getenv("EVAL_GATE_DIR") or tempfile.mkdtemp(prefix="gigbid-eval-"))
    out.mkdir(parents=True, exist_ok=True)
    run_smoke(out)
    return check(out)


if __name__ == "__main__":
    sys.exit(main())
