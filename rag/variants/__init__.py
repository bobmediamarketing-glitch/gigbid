"""Retrieval variants. Each module exports CONFIG (a PipelineConfig); `rag.variant` in config picks one."""
from __future__ import annotations

import importlib
import pkgutil

from rag.pipeline import PipelineConfig


def all_configs() -> dict[str, PipelineConfig]:
    out = {}
    for m in pkgutil.iter_modules(__path__):
        mod = importlib.import_module(f"{__name__}.{m.name}")
        if hasattr(mod, "CONFIG"):
            out[mod.CONFIG.name] = mod.CONFIG
    return dict(sorted(out.items()))
