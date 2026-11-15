"""V0 (baseline): fixed word chunks, top-k cosine on the whole job post."""
from rag.pipeline import PipelineConfig

CONFIG = PipelineConfig(name="v0_naive", query="whole", units="fixed", retrieval="dense")
