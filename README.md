# GigBid: a multi-agent freelancer copilot

AI-4016 R&D assignment. A team of LangGraph agents finds freelance jobs, judges whether they are worth a bid,
writes proposals grounded in real portfolio evidence and handles client conversations. A human approves every
proposal and message before it leaves the system.

> Status: work in progress. The official starter kit is not released yet, so development runs on a stand-in
> kit ([ADR 0001](docs/adr/0001-standin-starter-kit.md)).

## Quick start (dev)
```bash
python -m venv .venv && .venv/Scripts/pip install -e .[dev]
make seed      # generate personas, GigSim seed, dev set
make gigsim    # simulator on :8100
make test
```
