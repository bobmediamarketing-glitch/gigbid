# GigBid: a Multi-Agent Freelancer Copilot

AI-4016 R&D Assignment - report

> **Read this first.** (1) The official starter kit had not been released, so all data comes from a **stand-in kit** built to the brief's description (`scripts/make_standin_kit.py`, seed 4016; ADR 0001). (2) No model API key was configured, so every number was produced in **rule mode** ("rules (no API key)"): writer, critic and analyst ran their deterministic rule paths, and model-dependent columns are not yet meaningful. All numbers come from `evals/results/` and are checked by `scripts/ci/check_numbers.py`.

## 1. Summary

GigBid is a freelancing copilot. It finds jobs that fit, proves the fit with the freelancer's own portfolio, prices the job, drafts a grounded proposal, and then waits for a human: nothing is submitted, sent or spent without approval. It consists of two hand-written LangGraph graphs (bid and conversation), three MCP servers we wrote, a FastAPI + React app, an Arq worker, and a Docker Compose stack with CI and an eval gate.

<!-- results:start -->
Result in one paragraph: on the stand-in dev set (600 jobs, 200 per persona), the shipped retrieval pipeline raises evidence Recall@5 from 0.719 (naive baseline V0) to 0.938, and nDCG@10 from 0.493 to 0.716, at a p95 retrieval latency of 43 ms on CPU with no API cost. The pre-registered hypothesis H-B (decomposition plus hybrid retrieval gives at least 15 points over V0 on jobs with four or more requirements) is **rejected as stated**: that exact configuration scores 0.700 against V0's 0.720. The gain comes from how portfolio items are indexed, not from query decomposition. End to end, the rule-mode decisions reach bid/skip F1 0.989 with scam precision and recall of 1.000 and 0.870 of quotes inside the fair price band. Better retrieval did **not** translate into a higher simulated reply rate: reply rates range from 0.676 to 0.824 across variants and do not follow Recall@5, while the simulator's hidden client score stays flat (0.775 to 0.7912). All of this is on synthetic data whose generator and decision rules were written by the same person, so it says little about real jobs.
<!-- results:end -->

## 2. System architecture

### 2.1 Components

The browser talks to FastAPI over REST and Server-Sent Events (SSE). The API enqueues graph runs on Redis; an Arq worker runs the graphs and publishes events back through Redis pub/sub. Postgres holds app tables, checkpoints and the memory store. The worker reaches the outside world only through three MCP servers: Portfolio (backed by Qdrant), Marketplace (GigSim or the official Upwork MCP server) and Workspace. Traces go to Langfuse.

### 2.2 Agents and why each exists

Each agent is a graph node with its own typed output and its own MCP tool allowlist.

| Agent | Job | Why it is separate |
|---|---|---|
| Scout | Saved searches to new jobs, on a schedule | Read-only; owns pacing; never re-hands a seen job |
| Job Analyst | Post to `JobSpec` (requirements, implied skills) | Implied skills are the corpus's main trap; one place resolves them |
| Risk Assessor | Scams, client history, removed injections to `RiskReport` | Cheap, runs on every job; a model can never clear a rule hit |
| Fit Matcher | Proof per requirement to `FitReport` | Decides what the writer may claim; coverage drives bid/skip |
| Decision | Bid, watch or skip, with named reasons | Deterministic; thresholds in config |
| Pricing Strategist | Percentiles, floor, client range, outcome memory to `PriceQuote` | Price is numeric and auditable, not left to a model |
| Proposal Writer | Cover letter with `[evidence-id]` markers | The only creative step; sees only proven evidence |
| Claim verifier | Labels claims supported, partly, unsupported | Hallucinated experience is the worst failure |
| Critic | Client-eyed rubric; sends back at most twice | A different model family judges the writer |
| Compliance Guard | Policy pack, platform limits, injection echo | Policy changes are config edits; re-checks human edits |
| Client Liaison | The conversation graph | Different risks: negotiation floors, off-platform pushes, holds |

Model routing is per node in `agent/config.yaml`: the required `open` profile uses open-weight models on Groq (8B for analyst and compliance, 70B for writer and risk, a different family for the critic); `paid` and `open_local` (Ollama) profiles also exist. With no key, each node runs its rule path, which is how all reported numbers were produced.

### 2.3 MCP servers and least privilege

Agents only see MCP tools. Each node has an allowlist (`mcp.allowlists`), enforced in `agent/tools.py` before a request leaves the process. For example, the Risk agent cannot submit, the writer cannot touch the marketplace, and in the conversation graph only the post-approval `send_reply` node may call `send_message` or create a calendar hold.

### 2.4 One marketplace port

`agent/marketplace_port.py` defines one interface with two adapters, GigSim and live Upwork (via the official Upwork MCP server). Only the Marketplace server knows which is active. Upwork tool names are mapped in config and checked on connect. Live mode is drafts-only, reads at most once per 15 minutes per search, and uses no scraping or session cookies.

### 2.5 The two graphs

Both graphs are rendered from the compiled code in `docs/GRAPHS.md`.

- **Bid graph** (one thread per job): `intake` fans out to `analyst`, `risk` and `matcher` in parallel; all three join at `decide`; then `pricing`, `writer`, `verify`, `critic` (which may loop back to the writer), `compliance`, `approval` (interrupt) and `submit`. Any node can route a halted run to the end.
- **Conversation graph** (one thread per client conversation): `load_thread`, `classify`, `gather`, `draft_reply`, `verify_reply`, `check_reply`, `approve_reply` (interrupt), `send_reply`.

### 2.6 Durability

Every super-step is checkpointed, approvals are interrupts read back from the checkpoint (they survive refreshes, restarts and crashes), and submits are idempotent (Section 5.3).

## 3. Part A: MCP servers

### 3.1 The three servers

| Server | Tools | Notes |
|---|---|---|
| Marketplace | 9 read tools (health, policy, search, job, client history, price stats, Connects balance, messages, events); writes `create_proposal_draft`, `submit_proposal`, `send_message` | GigSim or Upwork behind one port; rate limited |
| Portfolio | `search_evidence`, `get_case_study`, `list_skills`; `portfolio://` resources for cases, proposals, repos, reviews and the CV; three prompts | Retriever variant set in config; incremental reindex |
| Workspace | `free_slots`, `list_holds`, `create_interview_hold`, `create_email_draft` | Mock calendar; tentative holds; drafts only |

Third-party servers used, not written by us: the official Upwork MCP server (live marketplace, OAuth 2.1, every write a draft the user confirms on Upwork) and the official GitHub MCP server (read-only ingestion of the freelancer's repos).

### 3.2 Tool design

- **Annotations.** Read tools are read-only and idempotent; marketplace tools are open-world, the others closed-world; `submit_proposal` and `send_message` are destructive.
- **Safe writes.** Every write takes an idempotency key and marketplace writes support `dry_run`. Approval only dry-runs; the real write happens in `submit`.
- **Untrusted output.** `get_job` and `list_messages` text is treated as untrusted (Section 7.3).
- **Degraded mode.** An outage returns `[marketplace_unavailable]`; the run is `queued` (no retry storm), the worker re-queues it, and `marketplace_health` drives the UI banner.
- **Frozen schemas.** Signatures are snapshotted in `tests/contract/snapshots/`; CI fails on unregenerated changes.

### 3.3 Auth and audit

The servers run over stdio (MCP Inspector, Claude Desktop, Cursor) or Streamable HTTP (Compose). Over HTTP, each call carries a short-lived JWT signed with `MCP_CALLER_SECRET` naming the user and their marketplace credentials, so the servers stay multi-tenant; DNS-rebinding protection stays on. OAuth tokens are encrypted at rest with Fernet and never logged. Every marketplace and workspace call goes to an append-only audit log (`data/audit/*.jsonl`: user, tenant, tool, arguments, result summary, trace id) with emails, phones, card numbers and tokens masked.

### 3.4 Tests

- Per-server tests: annotations, submit exactly once with dry run, input constraints, outage code, PII masking in the audit log, exact tool-name search, filters, resources and prompts, incremental reindex, slots and holds.
- Contract snapshots per server, and HTTP integration with real subprocesses: unsigned and forged tokens are rejected, and the full bid graph runs with a signed user token.
- A CI workflow publishes the Portfolio server as a public Docker image.

### 3.5 What was not done in Part A

- **R&D question A (tool granularity) was NOT run.** Comparing coarse and fine tool surfaces needs a model to call the tools, and no model key was available. There are no results for it in `evals/results/`.
- **MCP Inspector screenshots are pending.** The servers support stdio for the Inspector, but the screenshots have not been captured yet.

## 4. Part B: Advanced RAG

### 4.1 Setup

Three personas, each with a CV, 15-25 case studies, 20-30 repos (README and code), reviews and 150 past proposals with outcomes. Planted hard cases: implied skills (about 30% of requirements), vague READMEs, duplicated projects, scams, injections and vague posts.

Gold evidence is every portfolio item (CV excluded) covering at least half of the job's real skills, graded by skills covered (an earlier top-8 gold with id tie-breaking made recall arbitrary and was fixed before any comparison). Recall@5 is capped recall (gold in top 5 over the smaller of 5 and the gold size); nDCG@10 uses gain 2^rel - 1; latency is measured with empty query caches. Embeddings: `BAAI/bge-small-en-v1.5`; reranker: `ms-marco-MiniLM-L-6-v2`.

### 4.2 Variants

| Variant | What it changes |
|---|---|
| V0 naive | Fixed word chunks, top-k cosine on the whole post (baseline) |
| V1 decompose | V0 + one retrieval per requirement, merged with RRF |
| V2 hybrid | V0 + BM25 and dense fused with RRF |
| V3 rerank | V0 + cross-encoder reranking |
| V4 outcome | V0 + outcome-aware ranking (won or replied proposals up, ignored down) |
| V5 multivector | V0 with summary, README and code chunks indexed separately, returned as one item |
| V8 corrective | The shipped pipeline inside a corrective LangGraph loop: grade evidence, re-query when weak, refuse when none |
| best (shipped) | One unit per item with a metadata header (title, type, client industry, outcome, skills); hybrid BM25 + dense; the whole post (weighted x2) plus each requirement as queries; RRF fusion |

V6 and V7 were not built.

### 4.3 Retrieval results

<!-- results:start -->
Dev set, mean over personas.

| Variant | Recall@5 | Recall@5 (4+ req) | MRR | nDCG@10 | p50 ms | p95 ms |
|---|---|---|---|---|---|---|
| best | 0.938 | 0.943 | 0.960 | 0.716 | 17 | 43 |
| v0_naive | 0.719 | 0.720 | 0.817 | 0.493 | 14 | 43 |
| v1_decompose | 0.633 | 0.631 | 0.777 | 0.426 | 1 | 22 |
| v2_hybrid | 0.715 | 0.714 | 0.816 | 0.485 | 14 | 26 |
| v3_rerank | 0.815 | 0.827 | 0.874 | 0.529 | 577 | 1004 |
| v4_outcome | 0.695 | 0.694 | 0.793 | 0.468 | 12 | 16 |
| v5_multivector | 0.922 | 0.932 | 0.939 | 0.715 | 12 | 22 |
| v8_corrective | 0.931 | 0.939 | 0.961 | 0.707 | 212 | 627 |

V8 refuses evidence on most jobs the persona is not qualified for (evidence returned on 0.25 of unqualified jobs against 1.00 for every other variant) while keeping it on qualified jobs (1.00).
<!-- results:end -->

### 4.4 Hypothesis H-B

H-B, stated before running: *requirement decomposition plus hybrid retrieval raises evidence Recall@5 by at least 15 points over V0 on jobs with four or more requirements.*

<!-- results:start -->
On jobs with 4+ requirements: V0 0.720, V1 (decomposition) 0.631, V2 (hybrid) 0.714. The exact hypothesis configuration (V0 + decomposition + hybrid) scores 0.700 (-2.0 points). **H-B is rejected as stated.** The shipped pipeline does reach 0.943 on these jobs (+22.3 points vs V0), but that gain comes mainly from indexing items as whole units with a metadata header, not from the two query-side techniques the hypothesis named.
<!-- results:end -->

Decomposition alone hurts because fusing one ranking per requirement rewards items that match one requirement strongly, while relevance here means covering many. Querying with the whole post plus each requirement keeps that signal. BM25 only pays off once items carry their tool names in a header.

### 4.5 Ablation of the shipped pipeline

<!-- results:start -->
One component flipped at a time.

| Configuration | Recall@5 | Recall@5 (4+ req) | MRR | nDCG@10 | p95 ms |
|---|---|---|---|---|---|
| best | 0.938 | 0.943 | 0.960 | 0.716 | 39 |
| without decomposition (whole post only) | 0.916 | 0.921 | 0.932 | 0.699 | 20 |
| without BM25 (dense only) | 0.918 | 0.918 | 0.954 | 0.698 | 34 |
| + cross-encoder rerank (V3) | 0.939 | 0.943 | 0.964 | 0.717 | 1900 |
| + outcome boost | 0.930 | 0.931 | 0.959 | 0.689 | 39 |
| with multivector units | 0.912 | 0.913 | 0.956 | 0.678 | 38 |
| H-B test: V0 + decomposition + hybrid | 0.697 | 0.700 | 0.806 | 0.467 | 23 |

Findings:
- Every kept component earns its place: removing decomposition or BM25, or swapping item units for multivector units, lowers Recall@5 (0.916, 0.918 and 0.912 against 0.938).
- The cross-encoder lifts a weak pipeline (V0 0.719 to V3 0.815) but adds almost nothing to the strong one (0.939 vs 0.938) while p95 latency rises from 39 ms to 1900 ms.
- The outcome boost lowers recall (0.930): the writer cites proof items, never past proposals, so outcome ranking only matters for phrasing.
<!-- results:end -->

### 4.6 Claim verification

`rag/verify.py` sits between the writer and the critic. Each sentence with a claim gets one of three labels:
- **supported**: every cited id is in the evidence pack and every metric appears in a cited item;
- **partly supported**: at least one cited id is real and backs every metric, but other cited ids are unknown; the unknown citations are dropped;
- **unsupported**: anything else (only unknown sources, or a metric the evidence does not contain); the sentence is removed before the critic or the human sees it.

<!-- results:start -->
Before/after counts: in rule mode, unsupported claims per proposal are 0.00 before verification and 0.00 after, for every variant, and partly supported claims are 0.0. This is **zero by construction**: the template writer only copies evidence, so it cannot invent a claim. The before/after comparison becomes meaningful only with a model writer, which has not been run. The CI gate already enforces the "after" value (it must stay at zero) and an upper bound on the "before" value.
<!-- results:end -->

### 4.7 Decision metrics

<!-- results:start -->
Dev set, all personas, rules (no API key).

| RAG variant | Bid/skip F1 | Scam precision | Scam recall | Price in fair band | p50 ms | p95 ms | USD per job |
|---|---|---|---|---|---|---|---|
| best | 0.989 | 1.000 | 1.000 | 0.870 | 176 | 258 | 0.0000 |
| v8_corrective | 0.932 | 1.000 | 1.000 | 0.871 | 197 | 400 | 0.0000 |
| keyword | 0.982 | 1.000 | 1.000 | 0.872 | 164 | 227 | 0.0000 |

The corrective loop works at retrieval level but loses end to end: refusing evidence lowers the Matcher's coverage, and bid/skip F1 drops from 0.989 to 0.932, while off-domain jobs are already skipped by the coverage rules. A keyword retriever is close behind (0.982), so on this synthetic data most decision quality comes from the rules.
<!-- results:end -->

### 4.8 GigSim outcomes

<!-- results:start -->
Fixed job set, 25 jobs per persona, rules (no API key).

| RAG variant | Proposals | Unsupported / proposal (before) | Rubric score* | GigSim reply rate | p95 latency (s) | Cost per proposal (USD) |
|---|---|---|---|---|---|---|
| v0_naive | 74 | 0.00 | 0.970 | 0.730 | 0.35 | 0.0000 |
| v1_decompose | 74 | 0.00 | 0.970 | 0.716 | 0.36 | 0.0000 |
| v2_hybrid | 74 | 0.00 | 0.971 | 0.730 | 0.36 | 0.0000 |
| v3_rerank | 74 | 0.00 | 0.962 | 0.770 | 1.54 | 0.0000 |
| v4_outcome | 74 | 0.00 | 0.970 | 0.676 | 0.35 | 0.0000 |
| v5_multivector | 74 | 0.00 | 0.970 | 0.824 | 0.34 | 0.0000 |
| v8_corrective | 68 | 0.00 | 0.978 | 0.824 | 0.40 | 0.0000 |
| best | 74 | 0.00 | 0.967 | 0.676 | 0.38 | 0.0000 |
| keyword | 72 | 0.00 | 0.968 | 0.694 | 0.33 | 0.0000 |

*The Critic's rule rubric (0-1), not a calibrated LLM judge.
<!-- results:end -->

### 4.9 Where better retrieval did not become more replies, and why

<!-- results:start -->
Reply rate ranges from 0.676 to 0.824 across variants and does not follow Recall@5. The shipped pipeline sits at the bottom of that range (0.676) and V5 near the top (0.824). But the simulator's own hidden client score for the same proposals barely moves: overall values are 0.775 to 0.7912 (for example V0 0.7851, best 0.777, V8 0.7912). With about 74 proposals per variant the standard error of a reply rate is about 5 points, so differences under about 10 points are noise. The reply differences are the simulator's randomness, not proposal quality.
<!-- results:end -->

Why: simulated clients reward naming every required skill, a specific opening and a metric. The rule-mode writer names the skills from the requirements whatever evidence it gets, and any case study supplies a metric, so retrieval decides *which* proof is cited, not *whether* the proposal reads as relevant. The gap should appear with a model writer, whose claims depend on its evidence; that run has not been done.

### 4.10 Judge calibration

The LLM judge (`evals/judge/`) is not yet calibrated. Calibration needs 30 human labels (`evals/judge/labels.csv`), and these are **pending**, so **Cohen's kappa is not reported**. Until then the "judge score" column is the Critic's rule rubric.

## 5. Part C: Orchestration

### 5.1 Typed state and hand-offs

- **State** (`agent/state.py`, `agent/conversation.py`) is typed, with one key per agent. The parallel branches never write the same key, so they need no reducer. Counters (`steps`, `tokens`, `usd`, `revisions`) and logs (`trace`, `errors`, `critiques`) use `operator.add` reducers.
- **Hand-offs** are Pydantic models on every edge (`agent/handoffs.py`): `JobSpec`, `RiskReport`, `FitReport`, `PriceQuote`, `ProposalDraft` and others. The same models are the API's response models, so the UI is type-checked against what the graph produces. Hand-off types are allow-listed in the checkpoint serializer so resume keeps working.
- **State, trace and memory are kept apart**: per-thread checkpointed state; the execution trace in `state.trace`, the audit log and Langfuse; and promoted knowledge only in a LangGraph store separate from the checkpointer.

### 5.2 Control flow

- **Injection stripping happens once at intake**, before the fan-out, so no branch sees the raw post.
- **Fan-out with `Send`**: Analyst, Risk and Matcher each get their own state copy and run in parallel, joining at `decide`.
- **Skip / watch / bid**: the decision is deterministic, each skip names its rule, and every threshold is in config. A close call is watched (shown in the inbox, not drafted).
- **Critic loop**: the critic can send the draft back to the writer at most twice (`critic_max_loops: 2`).
- **Interrupt approvals**: `approval` calls `interrupt()` with exactly what will be sent, plus the risk report, the evidence behind every claim and the verification summary. Since `interrupt` re-runs the node on resume, it only does a dry run. The human approves, edits (re-checked by Compliance) or rejects with a reason.
- **Autonomy**: `suggest` (default) leaves low-fit skips as suggestions; `auto_skip` closes them. Scams always close. There is no auto-send path.
- **Budgets and failures**: exceeded step, token or cost budgets move a thread to `needs_attention`. Nodes have timeouts; transient failures are retried with backoff, then the thread goes to `dead_letter`. Cheap nodes fall back to a smaller model, then to rules.

### 5.3 Durability, crash-resume and replay

The checkpointer is SQLite locally and Postgres in production; `submit` uses idempotency keys derived from `run_id`. `test_crash_resume_exactly_once_on_postgres` kills a run right after the platform accepted the submit, resumes from the Postgres checkpoint and checks the proposal is submitted exactly once; it runs on embedded Postgres (`pgserver`). `agent/replay.py` replays a thread from any node as a fork (tested).

### 5.4 Long-term memory with promotion rules

Nothing is remembered from a single event, and raw tool output never goes straight into memory.

- **Style memory.** Approved edits are diffed into staged observations (cut the first sentence, removed a word, much shorter text, added closing line). One becomes a rule only after `promote_after: 2` separate edits. Rules go into the writer's prompt and a deterministic post-pass, so they hold on the rule path too. Deleting a rule (Settings memory viewer) also clears its staging count.
- **Outcome memory.** At submit only features are staged (category, price position, length bucket, evidence types), never text. A category gets an entry after `min_outcomes: 5` resolved proposals; a feature becomes a lesson only with `min_support: 3` proposals and a reply-rate lift of at least `min_lift` over the category. Pricing then shifts its target percentile and says so in its rationale.

Tests cover promotion after two edits, ignoring single-word noise, outcome promotion only with enough evidence, and learning from GigSim events.

### 5.5 Conversation graph

Intents: question, negotiation, interview request, scam signal, other. Rules decide scams, which get a fixed safe reply; a model can never overrule them. Client messages are stripped of injections per sentence (posts per line), so a real question next to an injected sentence survives. Interview replies offer Workspace free slots and sending creates tentative holds; negotiation never goes below the persona's floor. Only `send_reply`, behind the interrupt, may send.

### 5.6 R&D question C: not run

Question C asks how a single ReAct agent, `langgraph-supervisor` and our hand-written graph compare. **This comparison was not run**, because it requires a model to drive the ReAct and supervisor agents and no model key was available. There are no results for it.

## 6. Part D: Web interface

The UI is React + TypeScript (Vite), served by FastAPI in production so the browser talks to one origin and the session cookie and SSE work without CORS.

- **Screens.** Login and onboarding (persona or own profile, GigSim or Upwork, rates, categories, weekly Connects budget, portfolio upload); an inbox ranked by fit with risk badges, price and Connects cost; a job page with the requirement-to-evidence matrix and bid/skip reasoning; a proposal studio with evidence on hover for every claim, Critic and Compliance notes, the claim check, and approve, edit or reject with a reason; approvals (read from the checkpoint, so they survive restarts); a live pipeline kanban; client messages with suggested replies and interview slots; node-by-node run views with checkpoint history and a trace link; analytics; and settings with the memory viewer.
- **Streaming.** Worker events go to a per-user Redis channel; any API replica relays them over SSE.
- **Typed client.** `src/lib/api-types.ts` is generated from FastAPI's OpenAPI schema (`make gen-api`).
- **Tests.** Five Playwright tests (onboarding, approve, reject with a reason, edit a draft, degraded banner) with their own GigSim and API, run in CI.
- **Mobile and degraded states.** The layout works at phone width. A banner shows when the marketplace is unavailable, and another in rule mode.

## 7. Part E: Production

### 7.1 Worker and idempotency

Arq on Redis runs graph steps and two crons: `scout` (starts saved searches that are due, at most once per 15 minutes each) and `sync` (marketplace events into the pipeline, memory and reply drafts). Jobs have deterministic ids (`run:<thread>`, `resume:<thread>:<approval id>`), so duplicate requests are dropped by the queue, and bid thread ids derive from the job id, so a job is never analysed twice. No new drafts start once the weekly Connects budget is spent. Without `REDIS_URL` the same code runs in-process.

### 7.2 Tracing

Langfuse (with client-side PII masking) records every node and tool call. The trace id is derived from the thread id, sent to the MCP servers as `X-Trace-Id` and written into every audit row, so UI, API, worker, audit log and Langfuse share one trace id per run.

### 7.3 Guardrails and the injection eval

Injection patterns (config data) are stripped from posts and messages before any model sees them, the rest is fenced in `<untrusted>` tags, and Compliance blocks any echo of removed text. Scam patterns and the five policy-pack rules are also config.

<!-- results:start -->
| Setting | Jobs drafted | Success in writer draft | Success in sent text | Approval bypassed |
|---|---|---|---|---|
| defences off | 12 | 0.0% | 0.0% | 0 |
| defences on | 15 | 0.0% | 0.0% | 0 |

This result is **not evidence that the defences work**. In rule mode the template writer never reads the job text, so 0.0% before defences is expected. The meaningful before/after measurement needs a model and has not been run. What the run does show is that no planted-injection job bypassed the approval step.
<!-- results:end -->

### 7.4 Budgets and service levels

Declared targets (`slo` in config): a job analysed at p95 8 s and $0.004, a proposal to approval at p95 30 s and $0.02. Optimisations: skip early (risk and fit before drafting), small models for routing and risk, and caching embeddings by text hash.

<!-- results:start -->
Measured in rule mode: p95 of 258 ms per job analysed (best variant) and 0.38 s per proposal, at 0.0000 USD. These are far inside the targets but say nothing about the model profile, whose numbers have not been measured.
<!-- results:end -->

### 7.5 Docker Compose stack

`infra/docker-compose.yml` runs web, API, worker, the three MCP servers, GigSim, Postgres, Redis, Qdrant and Ollama, all with `restart: unless-stopped`; a single-container shape exists for PaaS tiers. The Postgres, queue and HTTP-MCP paths are also tested without Docker.

### 7.6 CI with an eval gate

- `ci.yml`: gitleaks over the full history, lint, tests, the numbers-trace check, Playwright and image builds.
- `eval.yml`: a smoke eval on 30 dev jobs that fails the PR if Recall@5, nDCG@10, bid/skip F1, scam recall or price-in-band fall below `evals/thresholds.json`, or unsupported claims rise above it. Floors sit a few points below the full-run numbers to absorb small-sample noise.

### 7.7 Deployment on a VM with HTTPS

`infra/deploy/setup_vm.sh` sets up a Linux VM (4 GB RAM or more) in one command: Docker, firewall ports 80/443, generated secrets (never committed), a swap file on small VMs, the stack behind Caddy with automatic HTTPS (a free `sslip.io` hostname or a custom domain), and a reviewer account preloaded with the AI/ML persona, whose login is shared only privately.

## 8. Signature extension: X2 proposal experiments

Two opening strategies were run as an A/B test in GigSim: goal_first (the default) and proof_first (open with
the strongest proven result). Both arms drafted and submitted proposals for the same jobs (paired design), each
in a fresh GigSim, and the test is McNemar's exact test on the discordant pairs (details in docs/EXTENSION.md).

<!-- results:start -->
| Arm | Proposals | Replies | Reply rate | Hidden client score |
|---|---|---|---|---|
| A goal_first | 117 | 94 | 0.803 | 0.764 |
| B proof_first | 117 | 90 | 0.769 | 0.764 |

Difference (B - A) -0.034; McNemar exact p = 0.6177. Not significant at 0.05, so goal_first stays the default.
The identical hidden client score shows the simulator rewards content, not order.
<!-- results:end -->

## 9. Limitations and honest caveats

1. **Stand-in starter kit.** The official kit had not been released, so all data comes from a stand-in kit and simulator built to the brief's description. The official kit replaces these files (the marketplace is reached only through the port), and `python -m evals.run_all` regenerates every number. Simulated clients score with a transparent heuristic, which is easy to audit but easy to overfit; GigBid never reads the hidden scores.
2. **Rule mode.** No model key was configured. The unsupported-claim rate is zero by construction, the "judge score" is the Critic's rule rubric, the injection result shows nothing because the writer does not read the job text, and cost and latency are rule-mode values.
3. **Experiments not run.** R&D questions A (tool granularity) and C (ReAct vs `langgraph-supervisor` vs our graph) need a model and were not run. Judge calibration awaits 30 human labels, so Cohen's kappa is not reported. MCP Inspector screenshots are pending.
4. **Threats to validity** (from `docs/DATA_CARD.md`):
   - *Synthetic data with a known generator.* The decision rules and scam patterns were written by the same person who wrote the generator, so the near-perfect bid/skip and scam scores say nothing about real jobs. The official held-out test set is the real test.
   - *Gold is defined by skill-tag overlap, and the index carries skill-tag metadata.* Variants that index metadata (the header in `best`, the summary unit in V5) get a partly circular advantage. Metadata on every chunk is required by the brief, but expect smaller gains on human-labelled gold.
   - *Rule path, not LLM path* (point 2).
   - *Choices made on the dev set.* The shipped combination and the V8 refusal threshold were picked on the dev set they are reported on, so those numbers are optimistic.
   - *Small samples for outcomes.* About 75 proposals per variant gives a standard error of about 5 points; differences under about 10 points are noise.

## 10. What ships

GigBid ships the `best` retrieval pipeline (`rag/variants/best.py`): one unit per portfolio item with a metadata header, hybrid BM25 + dense retrieval, and the whole job post plus each extracted requirement as queries, fused with RRF. On this dev set it has the highest Recall@5 of every configuration measured apart from adding the cross-encoder, which matches it at about 1.9 s p95; it runs on CPU with no API cost. The cross-encoder, outcome boost and corrective loop stay available but off: the ablation shows no recall gain from them, and the corrective loop lowers bid/skip F1. Better retrieval did not raise the simulated reply rate (differences are within the simulator's noise in rule mode), so the case for this pipeline rests on evidence quality, which a model-writer run should show as fewer unsupported claims before verification.
