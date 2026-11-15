"""Signature extension X2: proposal strategies as an A/B test in GigSim, with a significance test on reply rate.

Arm A = goal_first (open with the client's goal), arm B = proof_first (open with the strongest proven result).
Both arms draft and submit proposals for the SAME jobs (paired design), each arm in a fresh GigSim, then GigSim
advances 80 simulated hours and we read who replied. Tests:
- McNemar's exact test on the discordant pairs (the right test for paired binary outcomes),
- a two-proportion z-test (reported for familiarity; it ignores the pairing).

    python -m evals.runners.ab_test --n 40      # 40 bid jobs per persona -> 120 pairs

Writes evals/results/ab_test.json and ab_test_table.md.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import time
import uuid

os.environ.setdefault("GIGBID_OFFLINE", "1")

from langgraph.types import Command  # noqa: E402

from agent.checkpoint import memory_saver  # noqa: E402
from agent.graphs.bid_graph import compile  # noqa: E402
from agent.llm import LLM, profile_name  # noqa: E402
from agent.nodes.base import Ctx  # noqa: E402
from evals.runners.rag_eval import PERSONAS, RESULTS, load_dev  # noqa: E402

REPLIED = {"replied", "interview", "hired"}
ARMS = {"A": "goal_first", "B": "proof_first"}


async def run_arm(persona: str, jobs: list[str], strat: str, llm: LLM) -> dict[str, dict]:
    from gigsim.app import SIM, score_proposal
    from tests.integration.harness import lift_rate_limits, toolbox
    SIM.reset()
    lift_rate_limits()
    SIM.policy["connects"]["weekly_allowance"] = 100_000
    g = compile(memory_saver())
    out: dict[str, dict] = {}
    async with toolbox(persona) as tb:
        ctx = Ctx(tools=tb, llm=llm)
        for jid in jobs:
            rid = uuid.uuid4().hex[:12]
            cfg = {"configurable": {"thread_id": rid}}
            r = await g.ainvoke({"run_id": rid, "job_id": jid, "persona": persona, "strategy": strat}, cfg, context=ctx)
            if "__interrupt__" not in r:
                continue
            text = r["__interrupt__"][0].value["cover_letter"]
            bid = r["__interrupt__"][0].value["bid_amount"]
            r = await g.ainvoke(Command(resume={"action": "approve"}), cfg, context=ctx)
            pid = (r.get("submission") or {}).get("id")
            if pid:
                out[jid] = {"pid": pid, "opening": text.split(". ")[0][:120],
                            "client_score": score_proposal(SIM.jobs[jid], text, bid)["score"]}
        SIM.offset_sim_s += 80 * 3600
        SIM.process_due()
        for jid, row in out.items():
            row["replied"] = SIM.proposals[row["pid"]]["status"] in REPLIED
    return out


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar p-value from the discordant counts b (A only) and c (B only)."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    p = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return min(1.0, 2 * p)


def two_prop_z(x1: int, n1: int, x2: int, n2: int) -> tuple[float, float]:
    p = (x1 + x2) / (n1 + n2)
    se = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2)) if 0 < p < 1 else 0.0
    if se == 0:
        return 0.0, 1.0
    z = (x2 / n2 - x1 / n1) / se
    return z, math.erfc(abs(z) / math.sqrt(2))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--personas", nargs="*", default=PERSONAS)
    a = ap.parse_args()
    llm = LLM()
    pairs = []
    for p in a.personas:
        jobs = [x["job_id"] for x in load_dev(p) if x["bid"]][:a.n]
        arm = {k: asyncio.run(run_arm(p, jobs, s, llm)) for k, s in ARMS.items()}
        for jid in jobs:
            if jid in arm["A"] and jid in arm["B"]:
                pairs.append({"persona": p, "job_id": jid, "A": arm["A"][jid], "B": arm["B"][jid]})
        print(f"{p:13s} pairs so far {len(pairs)}", flush=True)
    n = len(pairs)
    ra = sum(x["A"]["replied"] for x in pairs)
    rb = sum(x["B"]["replied"] for x in pairs)
    b = sum(x["A"]["replied"] and not x["B"]["replied"] for x in pairs)
    c = sum(x["B"]["replied"] and not x["A"]["replied"] for x in pairs)
    z, pz = two_prop_z(ra, n, rb, n)
    res = {"pairs": n, "A_goal_first": {"replies": ra, "reply_rate": round(ra / n, 4) if n else 0.0,
                                        "client_score": round(sum(x["A"]["client_score"] for x in pairs) / n, 4) if n else 0},
           "B_proof_first": {"replies": rb, "reply_rate": round(rb / n, 4) if n else 0.0,
                             "client_score": round(sum(x["B"]["client_score"] for x in pairs) / n, 4) if n else 0},
           "difference_B_minus_A": round((rb - ra) / n, 4) if n else 0.0,
           "mcnemar": {"A_only": b, "B_only": c, "p_value": round(mcnemar_exact(b, c), 4)},
           "two_proportion_z": {"z": round(z, 3), "p_value": round(pz, 4)},
           "significant_at_0.05": mcnemar_exact(b, c) < 0.05}
    meta = {"model_profile": profile_name() if llm.available else "rules (no API key)", "n_per_persona": a.n,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "ab_test.json").write_text(json.dumps({"meta": meta, "result": res, "pairs": pairs}, indent=1))
    lines = ["### X2: proposal strategy A/B test in GigSim (paired, same jobs)", "", f"Model: {meta['model_profile']}", "",
             "| Arm | Proposals | Replies | Reply rate | Hidden client score |", "|---|---|---|---|---|",
             f"| A goal_first | {n} | {ra} | {res['A_goal_first']['reply_rate']:.3f} | {res['A_goal_first']['client_score']:.3f} |",
             f"| B proof_first | {n} | {rb} | {res['B_proof_first']['reply_rate']:.3f} | {res['B_proof_first']['client_score']:.3f} |",
             "", f"Difference (B - A): {res['difference_B_minus_A']:+.3f}. McNemar exact p = {res['mcnemar']['p_value']:.4f} "
                 f"(A-only {b}, B-only {c}); two-proportion z = {res['two_proportion_z']['z']:.3f}, "
                 f"p = {res['two_proportion_z']['p_value']:.4f}. "
                 f"{'Significant' if res['significant_at_0.05'] else 'Not significant'} at 0.05."]
    (RESULTS / "ab_test_table.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
