"""Retrieval comparison (Part B4/B5): every variant x persona on the dev set, plus the ablation.

    python -m evals.runners.rag_eval                      # all variants, all personas
    python -m evals.runners.rag_eval --variants v0_naive best --limit 50
    python -m evals.runners.rag_eval --ablation           # best pipeline minus one component at a time

The query is what the system really sees: the public job post (title + description) after
injection stripping. Gold = `gold_evidence` in evals/datasets/dev_<persona>.jsonl.
Writes evals/results/retrieval.json and evals/results/retrieval_table.md.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

from agent.guards import strip_injections
from evals.metrics import mean, mrr, ndcg_at_k, pct, recall_at_k
from rag.ingest.loaders import Corpus
from rag.pipeline import Pipeline, PipelineConfig
from rag.variants import all_configs

ROOT = Path(__file__).resolve().parents[2]
# GIGBID_RESULTS_DIR lets CI smoke runs write elsewhere, so committed results are never overwritten.
RESULTS = Path(os.getenv("GIGBID_RESULTS_DIR", ROOT / "evals" / "results"))
PERSONAS = ["ai_ml", "fullstack", "data_analyst"]
HYPOTHESIS = ("H-B: requirement decomposition plus hybrid retrieval raises evidence Recall@5 by at least "
              "15 points over V0 on jobs with four or more requirements.")


def load_dev(persona: str) -> list[dict]:
    return [json.loads(line) for line in (ROOT / "evals" / "datasets" / f"dev_{persona}.jsonl").read_text().splitlines()
            if line.strip()]


def job_texts() -> dict[str, str]:
    jobs = json.loads((ROOT / "gigsim" / "seed" / "jobs.json").read_text(encoding="utf-8"))
    return {j["id"]: strip_injections(f"{j['title']}\n\n{j['description']}")[0] for j in jobs}


def cold_caches() -> None:
    from rag.index.dense import Embedder
    from rag.index.rerank import Reranker
    for e in Embedder._instances.values():
        e.cache = {k: v for k, v in e.cache.items() if not k.startswith("q:")}
    for r in Reranker._instances.values():
        r.cache.clear()


def ablations(best: PipelineConfig) -> dict[str, PipelineConfig]:
    """Flip one component of the shipped pipeline at a time (removing what it has, adding what it lacks)."""
    out = {"best": best}
    out["best without decomposition (whole post only)" if best.query != "whole" else "best + decomposition"] =         best.without(name="abl_query", query="whole" if best.query != "whole" else "both")
    out["best without BM25 (dense only)" if best.retrieval == "hybrid" else "best + BM25"] =         best.without(name="abl_retrieval", retrieval="dense" if best.retrieval == "hybrid" else "hybrid")
    out["best + cross-encoder rerank (V3)" if not best.rerank else "best without rerank"] =         best.without(name="abl_rerank", rerank=not best.rerank)
    out["best without outcome boost" if best.outcome_boost else "best + outcome boost"] =         best.without(name="abl_outcome", outcome_boost=not best.outcome_boost)
    other = "multivector" if best.units != "multivector" else "item"
    out[f"best with {other} units"] = best.without(name="abl_units", units=other)
    # The hypothesis exactly as stated: V0 (fixed chunks, dense) + decomposition + hybrid.
    from rag.variants.v0_naive import CONFIG as V0
    out["H-B test: V0 + decomposition + hybrid"] = V0.without(name="abl_hb", query="decompose", retrieval="hybrid")
    return out


def evaluate(cfg: PipelineConfig, persona: str, texts: dict[str, str], limit: int | None) -> dict:
    corpus = Corpus(ROOT / "data" / "personas" / persona)
    pipe = Pipeline(corpus, cfg)
    cold_caches()  # latency is measured with query-side caches empty, as for a new job
    rows = []
    for item in load_dev(persona)[:limit]:
        gold = {g["id"]: g["relevance"] for g in item["gold_evidence"]}
        t0 = time.perf_counter()
        hits = pipe.search(texts[item["job_id"]], k=10)
        ms = (time.perf_counter() - t0) * 1000
        ranked = [h.doc.id for h in hits]
        rows.append({"job_id": item["job_id"], "bid": item["bid"], "n_req": item["n_requirements"],
                     "coverage": item["coverage"],
                     "has_gold": bool(gold), "ms": ms, "returned": len(ranked),
                     "r5": recall_at_k(ranked, set(gold), 5), "mrr": mrr(ranked, set(gold)),
                     "ndcg10": ndcg_at_k(ranked, gold, 10)})
    g = [r for r in rows if r["has_gold"]]

    def agg(rs):
        return {"n": len(rs), "recall@5": mean(r["r5"] for r in rs), "mrr": mean(r["mrr"] for r in rs),
                "ndcg@10": mean(r["ndcg10"] for r in rs)}
    out = agg(g)
    out.update({
        "p50_ms": pct([r["ms"] for r in rows], 0.5), "p95_ms": pct([r["ms"] for r in rows], 0.95),
        "by_n_requirements": {"4+": agg([r for r in g if r["n_req"] >= 4]), "1-3": agg([r for r in g if r["n_req"] < 4])},
        "by_decision": {"bid": agg([r for r in g if r["bid"]]), "skip": agg([r for r in g if not r["bid"]])},
        # Only V8 can refuse; for other variants this is 1.0 by construction. "cannot" = jobs where the
        # persona has under half the needed skills (evidence should be refused), "can" = 60%+.
        "evidence_returned_rate": {"can": mean(r["returned"] > 0 for r in rows if r["coverage"] >= 0.6),
                                   "cannot": mean(r["returned"] > 0 for r in rows if r["coverage"] < 0.5)},
    })
    return out


def overall(per_persona: dict[str, dict]) -> dict:
    keys = ["recall@5", "mrr", "ndcg@10", "p50_ms", "p95_ms"]
    o = {k: mean(v[k] for v in per_persona.values()) for k in keys}
    o["recall@5 (4+ req)"] = mean(v["by_n_requirements"]["4+"]["recall@5"] for v in per_persona.values())
    o["evidence when unqualified"] = mean(v["evidence_returned_rate"]["cannot"] for v in per_persona.values())
    o["evidence when qualified"] = mean(v["evidence_returned_rate"]["can"] for v in per_persona.values())
    return o


def table(results: dict, title: str) -> str:
    lines = [f"### {title}", "", "| Variant | Recall@5 | Recall@5 (4+ req) | MRR | nDCG@10 | p50 ms | p95 ms | "
             "Evidence when qualified | Evidence when unqualified |", "|---|---|---|---|---|---|---|---|---|"]
    for name, r in results.items():
        o = r["overall"]
        lines.append(f"| {name} | {o['recall@5']:.3f} | {o['recall@5 (4+ req)']:.3f} | {o['mrr']:.3f} | "
                     f"{o['ndcg@10']:.3f} | {o['p50_ms']:.0f} | {o['p95_ms']:.0f} | {o['evidence when qualified']:.2f} | "
                     f"{o['evidence when unqualified']:.2f} |")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variants", nargs="*", default=None)
    ap.add_argument("--personas", nargs="*", default=PERSONAS)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--ablation", action="store_true")
    a = ap.parse_args()
    texts = job_texts()
    configs = all_configs()
    if a.ablation:
        todo = ablations(configs["best"])
        out_name = "ablation"
    else:
        todo = {n: c for n, c in configs.items() if not a.variants or n in a.variants}
        out_name = "retrieval"
    results = {}
    for name, cfg in todo.items():
        per = {}
        for p in a.personas:
            t0 = time.time()
            per[p] = evaluate(cfg, p, texts, a.limit)
            print(f"{name:32s} {p:13s} R@5 {per[p]['recall@5']:.3f}  MRR {per[p]['mrr']:.3f}  "
                  f"nDCG@10 {per[p]['ndcg@10']:.3f}  ({time.time() - t0:.0f}s)", flush=True)
        results[name] = {"config": cfg.__dict__, "per_persona": per, "overall": overall(per)}
    RESULTS.mkdir(parents=True, exist_ok=True)
    meta = {"hypothesis": HYPOTHESIS, "limit": a.limit, "personas": a.personas,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    (RESULTS / f"{out_name}.json").write_text(json.dumps({"meta": meta, "results": results}, indent=1, default=str))
    md = table(results, "Retrieval ablation (one component of the shipped pipeline flipped at a time)" if a.ablation
               else "Retrieval variants (dev set, mean over personas)")
    (RESULTS / f"{out_name}_table.md").write_text(md + "\n")
    print("\n" + md)


if __name__ == "__main__":
    main()
