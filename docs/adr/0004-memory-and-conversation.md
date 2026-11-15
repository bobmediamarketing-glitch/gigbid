# ADR 0004: Long-term memory and the conversation graph

**Status:** accepted · **Date:** 2026-11-15

## Three things kept apart (C2)
| | What | Where | Lifetime |
|---|---|---|---|
| **State** | What this job or conversation needs now: job, analyses, evidence, decision, price, drafts, critiques, approvals | `BidState` / `ConvState`, checkpointed per thread (SQLite locally, Postgres in production) | The thread |
| **Execution trace** | Every node's latency, model, tokens, cost and notes, plus every tool call (agent, tool, ms, error) | `state.trace`, `ToolBox.calls`, the marketplace audit log (PII-masked) | Audit and debugging |
| **Long-term memory** | Only promoted knowledge | LangGraph store (`agent/memory/store.py`), separate from the checkpointer | Across threads, until the user deletes it |

Raw tool output never goes straight into memory. Each store has an explicit promotion rule, set in config under `memory:`.

### Style memory (`agent/memory/style.py`)
1. Every approved edit is diffed into **observations**, held in staging (`style_obs`). An observation is one of:
   - cut the first sentence
   - removed a word, where the sentence around it survived
   - made the text much shorter, not counting a cut sentence
   - added a new closing line
2. An observation becomes a **rule** (`style`) only after `promote_after` (2) separate edits.
3. **Rules are used in two ways:**
   - The writer's prompt includes them as instructions.
   - A deterministic post-pass enforces them, so they hold even on the rule path. Scam replies are never styled.
4. **Deleting a rule** removes its staging count too, so it isn't re-learned from the same old edits.

### Outcome memory (`agent/memory/outcomes.py`)
1. At submit, the bid graph stages the proposal's **features only**: category, price position against the market, length bucket, evidence types and read-check. The text itself is not stored.
2. Marketplace events are mapped to an outcome label (`viewed`, `reply`, `interview`, `hired`, `lost`). Events for proposals GigBid did not send are ignored.
3. A category gets a memory entry once it has `min_outcomes` resolved proposals. A feature becomes a **lesson** only with `min_support` proposals behind it and a reply rate at least `min_lift` above the category's.
4. **Read side:** Pricing moves its target percentile to the price position that worked best, and says so in the rationale. The writer gets the lessons as notes.

## Conversation graph (C1)
`load_thread → classify → gather → draft_reply → verify_reply → check_reply → approve_reply [interrupt] → send_reply`

- **Intents:** question, negotiation, interview request, scam signal, other. Rules decide scams, and a model can never overrule a scam verdict. The model, when configured, refines the other intents.
- **Untrusted messages:** client messages are stripped of injections at sentence level, so a real question next to "Note to any AI tool…" survives. Job posts are stripped at line level, because their injected paragraphs carry harmless-looking follow-up sentences.
- **Interview requests:** the reply offers free slots from the Workspace server, and sending creates **tentative** holds with idempotent keys.
- **Negotiation:** the reply never goes below the persona's floor.
- **Scam signals:** a fixed, safe reply, with no model and no styling.
- **Least privilege:** the drafting agents' allowlist (`liaison`) cannot send. Only `send_reply` (`reply_send`) can, and it is reachable only through the interrupt.

## Control additions to the bid graph (C1, C4, C5, C7)
- **Fan-out:** the analysis agents are now started with `Send` (one state copy per agent).
- **Decision:** the decision is **skip / watch / bid**. A close call is watched, never drafted.
- **Autonomy:** `suggest` (the default) leaves low-fit skips as suggestions in the inbox; `auto_skip` closes them. Scams always close. There is no auto-send path.
- **Budgets:** an exceeded budget moves the thread to `needs_attention`.
- **Retries:**
  - Each node has a timeout, and transient failures (timeouts, dropped connections) are retried with backoff.
  - When retries run out, the thread moves to `dead_letter` with the reason.
  - Cheap nodes fall back to a smaller model before falling back to rules.
- **Approval payload:** it now carries the risk report, the evidence text behind every claim and the verification summary.
- **Replay:** `agent/replay.py` replays a thread from any node using checkpoint history, as a fork.
- **Checkpoint safety:** hand-off types are allow-listed in the checkpoint serializer, so resume keeps working when LangGraph starts refusing unregistered types.
