# ADR 0001: Build a stand-in starter kit until the official one is released

**Date:** 2026-11-07 · **Status:** accepted (temporary)

## Context
The brief says the starter kit (GigSim, three personas, policy pack, job stream, dev set and
skeleton) is "shared on Google Classroom with this assignment". As of 7 Nov it has not been
posted; two classmates asked for it in the class comments. The deadline is 12 Nov.

## Decision
Generate a stand-in kit with the same shape the brief describes (`scripts/make_standin_kit.py`,
seed 4016) and a stand-in simulator (`gigsim/app.py`). All GigBid code talks to the marketplace
only through `agent/marketplace_port.py` and the Marketplace MCP server, so the official GigSim
replaces the stand-in by changing `GIGSIM_BASE_URL`; adapters absorb any API differences.

## Consequences
- Every number produced before the swap is labelled "stand-in kit" in `evals/results/`.
- Simulated clients score proposals with a transparent heuristic (must-have coverage,
  generic openings, evidence specificity, price vs ceiling, policy violations) rather than an LLM.
  This is easier to audit but easier to overfit; we never read `gigsim/seed/hidden.json` from GigBid.
- When the official kit arrives: drop it into `gigsim/` and `data/`, rerun `make eval`, and
  record the diff in this ADR.
