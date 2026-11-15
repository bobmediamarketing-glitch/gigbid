"""Ablation of the shipped retrieval pipeline: flip one component at a time (Part B, R&D question B).

    python -m evals.runners.ablation [--limit N]

Same code path as rag_eval --ablation; writes evals/results/ablation.json and ablation_table.md.
"""
from __future__ import annotations

import sys

from evals.runners import rag_eval

if __name__ == "__main__":
    sys.argv = [sys.argv[0], "--ablation", *sys.argv[1:]]
    rag_eval.main()
