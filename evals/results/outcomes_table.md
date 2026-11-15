### Proposal quality and outcomes (fixed job set)

Model: rules (no API key)

| RAG variant | Proposals | Unsupported claims / proposal (before verification) | Rubric score | GigSim reply rate | p95 latency (s) | Cost per proposal (USD) |
|---|---|---|---|---|---|---|
| v0_naive | 74 | 0.00 | 0.970 | 0.730 | 0.35 | 0.0000 |
| v1_decompose | 74 | 0.00 | 0.970 | 0.716 | 0.36 | 0.0000 |
| v2_hybrid | 74 | 0.00 | 0.971 | 0.730 | 0.36 | 0.0000 |
| v3_rerank | 74 | 0.00 | 0.962 | 0.770 | 1.54 | 0.0000 |
| v4_outcome | 74 | 0.00 | 0.970 | 0.676 | 0.35 | 0.0000 |
| v5_multivector | 74 | 0.00 | 0.970 | 0.824 | 0.34 | 0.0000 |
| v8_corrective | 68 | 0.00 | 0.978 | 0.824 | 0.40 | 0.0000 |
| best | 74 | 0.00 | 0.967 | 0.676 | 0.38 | 0.0000 |
| keyword | 72 | 0.00 | 0.968 | 0.694 | 0.33 | 0.0000 |
