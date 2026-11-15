"""V3: V0 + cross-encoder reranking of the top candidates (precision at small k)."""
from rag.variants.v0_naive import CONFIG as V0

CONFIG = V0.without(name="v3_rerank", rerank=True)
