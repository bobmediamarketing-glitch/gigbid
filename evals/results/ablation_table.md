### Retrieval ablation (one component of the shipped pipeline flipped at a time)

| Variant | Recall@5 | Recall@5 (4+ req) | MRR | nDCG@10 | p50 ms | p95 ms | Evidence when qualified | Evidence when unqualified |
|---|---|---|---|---|---|---|---|---|
| best | 0.938 | 0.943 | 0.960 | 0.716 | 16 | 39 | 1.00 | 1.00 |
| best without decomposition (whole post only) | 0.916 | 0.921 | 0.932 | 0.699 | 13 | 20 | 1.00 | 1.00 |
| best without BM25 (dense only) | 0.918 | 0.918 | 0.954 | 0.698 | 14 | 34 | 1.00 | 1.00 |
| best + cross-encoder rerank (V3) | 0.939 | 0.943 | 0.964 | 0.717 | 620 | 1900 | 1.00 | 1.00 |
| best + outcome boost | 0.930 | 0.931 | 0.959 | 0.689 | 17 | 39 | 1.00 | 1.00 |
| best with multivector units | 0.912 | 0.913 | 0.956 | 0.678 | 18 | 38 | 1.00 | 1.00 |
| H-B test: V0 + decomposition + hybrid | 0.697 | 0.700 | 0.806 | 0.467 | 2 | 23 | 1.00 | 1.00 |
