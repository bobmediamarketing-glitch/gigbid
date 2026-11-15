"""Proposal quality and outcomes (Part B4): unsupported claims, rubric score, GigSim reply rate, cost.

For a fixed job set (the first N dev jobs per persona whose gold label is "bid"), run the full bid
graph, auto-approve at the interrupt (an eval harness stands in for the human), then advance
GigSim's clock 80 simulated hours and read what the simulated clients did.

    python -m evals.runners.gigsim_outcomes --variants best v0_naive --n 25

Writes evals/results/outcomes.json, outcomes_table.md and the proposals to evals/results/runs/
(those files feed the judge calibration in evals/runners/judge.py).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
import uuid

os.environ.setdefault("GIGBID_OFFLINE", "1")

from langgraph.types import Command  # noqa: E402

from agent.checkpoint import memory_saver  # noqa: E402
from agent.graphs.bid_graph import compile  # noqa: E402
from agent.llm import LLM, profile_name  # noqa: E402
from agent.nodes.base import Ctx  # noqa: E402
from evals.metrics import mean, pct  # noqa: E402
from evals.runners.decision_eval import set_variant  # noqa: E402
from evals.runners.rag_eval import PERSONAS, RESULTS, load_dev  # noqa: E402

REPLIED = {"replied", "interview", "hired"}


async def run_persona(persona: str, n: int, llm: LLM) -> list[dict]:
    from gigsim.app import SIM, score_proposal
    from tests.integration.harness import lift_rate_limits, toolbox
    SIM.reset()
    lift_rate_limits()
    SIM.policy["connects"]["weekly_allowance"] = 100_000  # eval: never run out mid-set
    g = compile(memory_saver())
    jobs = [x for x in load_dev(persona) if x["bid"]][:n]
    rows = []
    async with toolbox(persona) as tb:
        ctx = Ctx(tools=tb, llm=llm)
        for item in jobs:
            rid = uuid.uuid4().hex[:12]
            cfg = {"configurable": {"thread_id": rid}}
            t0 = time.perf_counter()
            out = await g.ainvoke({"run_id": rid, "job_id": item["job_id"], "persona": persona}, cfg, context=ctx)
            ms = (time.perf_counter() - t0) * 1000
            req = out["__interrupt__"][0].value if "__interrupt__" in out else None
            if req:
                out = await g.ainvoke(Command(resume={"action": "approve"}), cfg, context=ctx)
            ver = out.get("verification") or {}
            crit = out["critiques"][-1] if out.get("critiques") else None
            prop = out.get("submission") or {}
            rows.append({
                "job_id": item["job_id"], "persona": persona, "status": out.get("status"),
                "proposal_id": prop.get("id"), "cover_letter": req["cover_letter"] if req else None,
                "screening_answers": req["screening_answers"] if req else [],
                "bid_amount": req["bid_amount"] if req else None,
                "claims_checked": ver.get("checked", 0), "claims_removed": ver.get("unsupported", 0),
                "claims_partly": ver.get("partly", 0), "claims_unsupported_after": ver.get("unsupported_after", 0),
                "rubric_score": crit.score if crit else None, "revisions": out.get("revisions", 0),
                "ms_to_approval": ms, "tokens": out.get("tokens", 0), "usd": out.get("usd", 0.0),
                "client_score": score_proposal(SIM.jobs[item["job_id"]], req["cover_letter"], req["bid_amount"])["score"]
                if req else None})
        SIM.offset_sim_s += 80 * 3600
        SIM.process_due()
        for r in rows:
            p = SIM.proposals.get(r["proposal_id"]) if r["proposal_id"] else None
            r["outcome"] = p["status"] if p else None
            r["replied"] = bool(p and p["status"] in REPLIED)
    return rows


def summarize(rows: list[dict]) -> dict:
    sent = [r for r in rows if r["proposal_id"]]
    checked = sum(r["claims_checked"] for r in sent)
    removed = sum(r["claims_removed"] for r in sent)
    return {"jobs": len(rows), "proposals": len(sent),
            "reply_rate": mean(r["replied"] for r in sent),
            "unsupported_claims_per_proposal_before": round(removed / len(sent), 3) if sent else 0.0,
            "unsupported_claims_per_proposal_after": round(sum(r["claims_unsupported_after"] for r in sent) / len(sent), 3)
            if sent else 0.0,
            "partly_supported_per_proposal": round(sum(r["claims_partly"] for r in sent) / len(sent), 3) if sent else 0.0,
            "unsupported_claim_rate_before": round(removed / checked, 4) if checked else 0.0,
            "rubric_score": mean(r["rubric_score"] for r in sent if r["rubric_score"] is not None),
            "hidden_client_score": mean(r["client_score"] for r in sent if r["client_score"] is not None),
            "p50_s": round(pct([r["ms_to_approval"] for r in sent], 0.5) / 1000, 3),
            "p95_s": round(pct([r["ms_to_approval"] for r in sent], 0.95) / 1000, 3),
            "tokens_per_proposal": mean(r["tokens"] for r in sent),
            "usd_per_proposal": round(mean(r["usd"] for r in sent), 6)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variants", nargs="*", default=["best"])
    ap.add_argument("--personas", nargs="*", default=PERSONAS)
    ap.add_argument("--n", type=int, default=25)
    a = ap.parse_args()
    llm = LLM()
    results = {}
    for v in a.variants:
        set_variant(v)
        per, all_rows = {}, []
        for p in a.personas:
            t0 = time.time()
            rows = asyncio.run(run_persona(p, a.n, llm))
            per[p] = summarize(rows)
            all_rows += rows
            (RESULTS / "runs").mkdir(parents=True, exist_ok=True)
            (RESULTS / "runs" / f"proposals_{v}_{p}.jsonl").write_text(
                "\n".join(json.dumps(r, default=str) for r in rows) + "\n")
            s = per[p]
            print(f"{v:16s} {p:13s} reply {s['reply_rate']:.3f}  rubric {s['rubric_score']:.3f}  "
                  f"unsupported/prop {s['unsupported_claims_per_proposal_before']:.2f}  ({time.time() - t0:.0f}s)",
                  flush=True)
        results[v] = {"per_persona": per, "overall": summarize(all_rows)}
    meta = {"model_profile": profile_name() if llm.available else "rules (no API key)", "n_per_persona": a.n,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "note": "rubric_score is the Critic's rule rubric until the LLM judge is calibrated (judge.py)"}
    (RESULTS / "outcomes.json").write_text(json.dumps({"meta": meta, "results": results}, indent=1, default=str))
    lines = ["### Proposal quality and outcomes (fixed job set)", "", f"Model: {meta['model_profile']}", "",
             "| RAG variant | Proposals | Unsupported claims / proposal (before verification) | Rubric score | "
             "GigSim reply rate | p95 latency (s) | Cost per proposal (USD) |", "|---|---|---|---|---|---|---|"]
    for n, r in results.items():
        o = r["overall"]
        lines.append(f"| {n} | {o['proposals']} | {o['unsupported_claims_per_proposal_before']:.2f} | "
                     f"{o['rubric_score']:.3f} | {o['reply_rate']:.3f} | {o['p95_s']:.2f} | {o['usd_per_proposal']:.4f} |")
    (RESULTS / "outcomes_table.md").write_text("\n".join(lines) + "\n")
    print("\n" + "\n".join(lines))


if __name__ == "__main__":
    main()
