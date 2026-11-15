"""V4: V0 + outcome-aware ranking (past proposals that won or got replies rank higher, ignored ones lower)."""
from rag.variants.v0_naive import CONFIG as V0

CONFIG = V0.without(name="v4_outcome", outcome_boost=True)
