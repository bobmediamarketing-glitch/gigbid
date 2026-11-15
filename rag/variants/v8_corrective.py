"""V8: the best pipeline inside a corrective LangGraph loop: grade evidence, re-query when weak, refuse when none."""
from rag.variants.best import CONFIG as BEST

CONFIG = BEST.without(name="v8_corrective", corrective=True, min_grade=-3.0)
