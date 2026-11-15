"""The shipped pipeline (see evals/results/RESULTS.md and docs/adr/0003-retrieval-choice.md):
item units with metadata headers + hybrid BM25/dense + the whole post AND each requirement as queries.
Left out after measuring: the cross-encoder (V3: ~1.8 s p95, no Recall@5 gain on top of this pipeline),
multi-vector units (V5: strong alone, but item units win once hybrid and decomposition are on) and the
outcome boost (V4: lowers Recall@5, and the writer only cites proof items, never past proposals)."""
from rag.pipeline import PipelineConfig

CONFIG = PipelineConfig(name="best", query="both", units="item", retrieval="hybrid", rerank=False,
                        outcome_boost=False)
