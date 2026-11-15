### Retrieval variants (dev set, mean over personas)

| Variant | Recall@5 | Recall@5 (4+ req) | MRR | nDCG@10 | p50 ms | p95 ms | Evidence when qualified | Evidence when unqualified |
|---|---|---|---|---|---|---|---|---|
| best | 0.938 | 0.943 | 0.960 | 0.716 | 17 | 43 | 1.00 | 1.00 |
| v0_naive | 0.719 | 0.720 | 0.817 | 0.493 | 14 | 43 | 1.00 | 1.00 |
| v1_decompose | 0.633 | 0.631 | 0.777 | 0.426 | 1 | 22 | 1.00 | 1.00 |
| v2_hybrid | 0.715 | 0.714 | 0.816 | 0.485 | 14 | 26 | 1.00 | 1.00 |
| v3_rerank | 0.815 | 0.827 | 0.874 | 0.529 | 577 | 1004 | 1.00 | 1.00 |
| v4_outcome | 0.695 | 0.694 | 0.793 | 0.468 | 12 | 16 | 1.00 | 1.00 |
| v5_multivector | 0.922 | 0.932 | 0.939 | 0.715 | 12 | 22 | 1.00 | 1.00 |
| v8_corrective | 0.931 | 0.939 | 0.961 | 0.707 | 212 | 627 | 1.00 | 0.25 |
