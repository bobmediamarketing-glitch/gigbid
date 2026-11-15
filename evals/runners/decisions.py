"""Decision quality (Part B4): bid/skip F1, scam precision/recall, price inside the fair band.

Runs the real bid graph (intake -> analyst | risk | matcher -> decide -> pricing) over the dev set
through the in-memory MCP servers and in-process GigSim, stopping before the writer.

    python -m evals.runners.decisions                       # configured RAG variant, all personas
    python -m evals.runners.decisions --variants best v8_corrective --limit 100

Writes evals/results/decisions.json and decisions_table.md.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
import uuid

os.environ.setdefault("GIGBID_OFFLINE", os.getenv("GIGBID_OFFLINE", "1"))

from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402

from agent.graphs.bid_graph import build  # noqa: E402
from agent.llm import LLM, profile_name  # noqa: E402
from agent.nodes.base import Ctx  # noqa: E402
from agent.settings import section  # noqa: E402
from evals.metrics import mean, pct, prf  # noqa: E402
from evals.runners.retrieval import PERSONAS, RESULTS, load_dev  # noqa: E402


def set_variant(name: str) -> None:
    from mcp_servers.portfolio import server as pf
    os.environ["RAG_VARIANT"] = name
    pf.store._cache.clear()


async def run_persona(persona: str, limit: int | None, llm: LLM) -> list[dict]:
    from tests.integration.harness import SIM, lift_rate_limits, toolbox
    SIM.reset()
    lift_rate_limits()
    g = build().compile(checkpointer=InMemorySaver(), interrupt_before=["writer"])
    max_scam = section("bid_graph")["decision"]["max_scam_score"]
    rows = []
    async with toolbox(persona) as tb:
        ctx = Ctx(tools=tb, llm=llm)
        for item in load_dev(persona)[:limit]:
            rid = uuid.uuid4().hex[:12]
            t0 = time.perf_counter()
            out = await g.ainvoke({"run_id": rid, "job_id": item["job_id"], "persona": persona},
                                  {"configurable": {"thread_id": rid}}, context=ctx)
            ms = (time.perf_counter() - t0) * 1000
            risk, dec, q = out.get("risk"), out.get("decision"), out.get("quote")
            band = item["fair_price_band"]
            rows.append({
                "job_id": item["job_id"], "gold_bid": item["bid"], "gold_scam": item["is_scam"],
                "pred_bid": bool(dec and dec.bid), "pred_scam": bool(risk and risk.scam_score > max_scam),
                "scam_type": item["scam_type"], "status": out.get("status"), "errors": out.get("errors", []),
                "price": q.amount if q else None,
                "in_band": (band["low"] <= q.amount <= band["high"]) if q and band["type"] == q.bid_type else None,
                "coverage": out["fit"].coverage if out.get("fit") else None,
                "ms": ms, "tokens": out.get("tokens", 0), "usd": out.get("usd", 0.0),
                "reasons": dec.reasons if dec else []})
    return rows


def summarize(rows: list[dict]) -> dict:
    bids = prf([r["pred_bid"] for r in rows], [r["gold_bid"] for r in rows])
    scams = prf([r["pred_scam"] for r in rows], [r["gold_scam"] for r in rows])
    priced = [r for r in rows if r["in_band"] is not None and r["gold_bid"]]
    by_type = {}
    for t in sorted({r["scam_type"] for r in rows if r["scam_type"]}):
        rs = [r for r in rows if r["scam_type"] == t]
        by_type[t] = {"n": len(rs), "caught": mean(r["pred_scam"] for r in rs)}
    return {"n": len(rows), "bid": bids, "scam": scams, "scam_recall_by_type": by_type,
            "price_in_band": mean(r["in_band"] for r in priced), "priced_n": len(priced),
            "p50_ms": pct([r["ms"] for r in rows], 0.5), "p95_ms": pct([r["ms"] for r in rows], 0.95),
            "tokens_per_job": mean(r["tokens"] for r in rows), "usd_per_job": round(mean(r["usd"] for r in rows), 6),
            "errors": sum(bool(r["errors"]) for r in rows)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variants", nargs="*", default=[None])
    ap.add_argument("--personas", nargs="*", default=PERSONAS)
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    llm = LLM()
    results = {}
    for v in a.variants:
        name = v or os.getenv("RAG_VARIANT") or (section("rag") or {}).get("variant", "keyword")
        set_variant(name)
        per, all_rows = {}, []
        for p in a.personas:
            t0 = time.time()
            rows = asyncio.run(run_persona(p, a.limit, llm))
            per[p] = summarize(rows)
            all_rows += rows
            s = per[p]
            print(f"{name:16s} {p:13s} bid F1 {s['bid']['f1']:.3f}  scam P {s['scam']['precision']:.3f} "
                  f"R {s['scam']['recall']:.3f}  price-in-band {s['price_in_band']:.3f}  ({time.time() - t0:.0f}s)",
                  flush=True)
            (RESULTS / "runs").mkdir(parents=True, exist_ok=True)
            (RESULTS / "runs" / f"decisions_{name}_{p}.jsonl").write_text(
                "\n".join(json.dumps(r, default=str) for r in rows) + "\n")
        results[name] = {"per_persona": per, "overall": summarize(all_rows)}
    meta = {"model_profile": profile_name() if llm.available else "rules (no API key)", "limit": a.limit,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    (RESULTS / "decisions.json").write_text(json.dumps({"meta": meta, "results": results}, indent=1, default=str))
    lines = ["### Decisions (dev set, all personas)", "", f"Model: {meta['model_profile']}", "",
             "| RAG variant | Bid/skip F1 | Scam precision | Scam recall | Price in fair band | p50 ms | p95 ms | "
             "USD per job |", "|---|---|---|---|---|---|---|---|"]
    for n, r in results.items():
        o = r["overall"]
        lines.append(f"| {n} | {o['bid']['f1']:.3f} | {o['scam']['precision']:.3f} | {o['scam']['recall']:.3f} | "
                     f"{o['price_in_band']:.3f} | {o['p50_ms']:.0f} | {o['p95_ms']:.0f} | {o['usd_per_job']:.4f} |")
    (RESULTS / "decisions_table.md").write_text("\n".join(lines) + "\n")
    print("\n" + "\n".join(lines))


if __name__ == "__main__":
    main()
