# ADR 0003: What retrieval ships

**Status:** accepted · **Date:** 2026-11-15 · **Evidence:** `evals/results/RESULTS.md`
(regenerate with `python -m evals.run_all`)

## Hypothesis (stated before running)
> H-B: requirement decomposition plus hybrid retrieval raises evidence Recall@5 by at least
> 15 points over V0 on jobs with four or more requirements.

## What we measured
- Seven variants (V0–V5, V8) plus the combined pipeline, on 600 dev jobs (200 per persona).
- Metrics: Recall@5, MRR, nDCG@10 and latency.
- The combined pipeline was then ablated one component at a time, and decisions and GigSim outcomes were measured end to end.

## Result in one line
**H-B is rejected as stated.** On jobs with 4+ requirements, V0 + decomposition + hybrid scores
Recall@5 0.700 against V0's 0.720. The shipped pipeline scores 0.943 (+22 points), and most of the
gain comes from how items are indexed, not from the query side. All figures are from
`evals/results/retrieval_table.md` and `ablation_table.md`.

## Findings
1. **Indexing beat query tricks.** Giving each portfolio item one unit, with a metadata header
   (title, type, client industry, outcome, skills), was the largest single gain. V5 shows it
   alone. Fixed word chunks (V0) cut skills and project names away from the text that proves them.
2. **Decomposition alone hurts.** V1 is below V0. Fusing one ranking per requirement rewards items
   that match a single requirement strongly, while relevance here means covering many requirements
   at once. Querying with the whole post *and* each requirement, with the whole post weighted ×2,
   keeps the multi-skill signal and still surfaces items for the rarer requirements. That combination
   is the best query strategy.
3. **Every kept component earns its place in the ablation.** Removing decomposition costs 2.2 points
   of Recall@5, removing BM25 costs 2.0, and swapping item units for multi-vector units costs 2.6. BM25 on its own (V2)
   does nothing for fixed chunks; it pays off once items carry their tool names in a header.
4. **The cross-encoder (V3) helps a weak pipeline and does nothing for a strong one.** It lifts V0
   from 0.719 to 0.815, but on top of the shipped pipeline it adds 0.1 points while p95 latency goes from about
   40 ms to 1.9 s.
5. **The outcome boost (V4) lowers recall.** It can only matter for phrasing: the writer cites proof
   items (case studies, repos, reviews), never past proposals. It is kept as a variant for the LLM
   writer's style examples and left out of proof retrieval.
6. **The corrective loop (V8) does what it promises at retrieval level and still loses end to end.** It
   refuses evidence on most jobs the persona is not qualified for and keeps it on qualified ones. But
   refusing evidence per requirement lowers the Matcher's coverage, and bid/skip F1 drops. Off-domain
   jobs are already skipped by the category and coverage rules, so the refusal adds risk without benefit.
7. **Better retrieval did not mean more replies.** Across variants, GigSim reply rate ranges from 0.676
   to 0.824 (about 74 proposals each, standard error about ±5 points) and does not follow Recall@5. The
   shipped pipeline sits at the bottom of that range and V5 at the top. Yet the simulator's own hidden
   client score for those same proposals barely moves (0.775–0.791, `evals/results/outcomes.json`), so the
   reply differences are the simulator's randomness, not proposal quality. The simulated clients reward naming every required skill, a specific opening and a metric.
   In rule mode the writer names the skills from the requirements whatever evidence it gets, and any
   retrieved case study supplies a metric. So retrieval quality decides *which* proof is cited, not
   *whether* the proposal reads as relevant. We expect the gap to show with the LLM writer, whose
   claims depend on the evidence it is given, and to show as fewer unsupported claims before verification.

## Decision
Ship `rag/variants/best.py`: item units with metadata headers, hybrid BM25 + dense, the whole post
plus each requirement as queries, no reranker, no outcome boost, no corrective loop. It gave the highest
Recall@5 among the configurations we tried, with p95 retrieval latency in the tens of milliseconds on CPU and no
API cost. Reconsider the reranker if the corpus grows by an order of magnitude, and V8 once the decision
step can use "refused" as a separate signal instead of a lower coverage number.

## Caveats
All on the stand-in kit (see `docs/DATA_CARD.md`, threats to validity). The pipeline choices were made
on the same dev set they are reported on, and gold is defined by skill-tag overlap. Rerun when the
official kit arrives.
