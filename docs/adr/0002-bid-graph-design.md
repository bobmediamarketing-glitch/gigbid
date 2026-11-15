# ADR 0002: Bid graph design

**Status:** accepted · **Date:** 2026-11-15

## Context
Part C asks for a hand-written LangGraph StateGraph: typed hand-offs, Analyst, Risk and
Matcher in parallel, a bounded Critic loop, human approval through `interrupt()`, step and
token budgets, and crash-resume that submits exactly once.

## Decisions
1. **One state key per agent, Pydantic hand-offs on every edge** (`agent/handoffs.py`,
   `agent/state.py`). The parallel branches never write the same key, so no reducer is
   needed for them. Counters (`steps`, `tokens`, `usd`, `revisions`) and logs (`trace`,
   `errors`, `critiques`) use `operator.add`.
2. **Injection stripping happens once, at intake, before the fan-out.** All three
   parallel agents read `job_text_clean`, so no branch ever sees the raw post. The
   removed spans flow on to Risk (reporting) and Compliance (an echo check on the
   outgoing text).
3. **The bid decision is deterministic.** Each skip names the rule that caused it, and
   every threshold lives in `agent/config.yaml`. LLMs inform the reports, while the
   go/no-go stays explainable and testable.
4. **Every LLM node has a rule path.** `LLM.structured` returns `None` when no key is
   set or a call fails, and the node then uses its rules. CI runs the full graph with
   no keys, and a provider outage degrades quality without stopping the run.
5. **Claim verification sits between Writer and Critic** (`rag/verify.py`). Sentences
   that cite unknown ids, or state metrics missing from the cited evidence, are removed
   before the Critic or the human sees them.
6. **Approval and submit are separate nodes.** `approval` calls `interrupt()` with
   exactly what will be sent; `interrupt` re-runs the node on resume, and that node only
   does a dry-run. `submit` performs the two writes with idempotency keys derived from
   `run_id`, so re-running it after a crash replays and does not charge again. This is
   tested by killing the run right after the platform accepted the submit.
7. **Per-agent tool allowlists** (`mcp.allowlists` in config) are enforced in
   `agent/tools.py` before a request leaves the process. The Risk agent cannot submit,
   and the Writer cannot touch the marketplace.
8. **Degraded mode:** a `[marketplace_unavailable]` tool error sets status `queued`,
   with no retry storm inside the graph; the worker re-queues it (Part E).

## Consequences
The rule paths double as the "rules baseline" in the evals. The quality numbers that
matter, the LLM ones, need `GROQ_API_KEY` and come from `evals/results/`.
