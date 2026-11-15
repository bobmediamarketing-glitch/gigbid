"""V2: V0 + hybrid BM25 + dense with reciprocal rank fusion (exact tool names survive)."""
from rag.variants.v0_naive import CONFIG as V0

CONFIG = V0.without(name="v2_hybrid", retrieval="hybrid")
