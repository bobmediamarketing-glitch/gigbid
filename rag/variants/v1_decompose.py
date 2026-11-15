"""V1: V0 + requirement decomposition (one retrieval per requirement, merged with RRF)."""
from rag.variants.v0_naive import CONFIG as V0

CONFIG = V0.without(name="v1_decompose", query="decompose")
