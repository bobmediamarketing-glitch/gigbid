"""V5: V0 with multi-vector items: summary, README and code chunks indexed separately, returned as one item."""
from rag.variants.v0_naive import CONFIG as V0

CONFIG = V0.without(name="v5_multivector", units="multivector")
