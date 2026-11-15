# Runbook

How to run, deploy and operate GigBid, and what to do when something breaks.

## Run it

| Goal | Command | Notes |
|---|---|---|
| Full stack (the graded setup) | `make dev` (`docker compose -f infra/docker-compose.yml up --build`) | http://localhost:8080. Starts web, API, worker, 3 MCP servers, GigSim, Postgres, Redis, Qdrant and Ollama |
| No Docker | `make gigsim`, then `make local` | API on :8000 serves the built web app. Runs graphs in-process, uses SQLite and the in-memory vector index |
| Dev with hot reload | `make gigsim`, `make api`, `make web` | Vite on :5173 proxies `/api` to :8000 |
| Local open models | `docker compose -f infra/docker-compose.yml --profile models up ollama-pull`, then set `GIGBID_MODEL_PROFILE=open_local` | Pulls qwen2.5:7b and llama3.2:3b (several GB) |
| Tests / lint / repo rules | `make test`, `make lint`, `make check` | |
| Evaluation | `make eval` (full, writes `evals/results/`), `make eval-gate` (30-job smoke with thresholds) | |

Copy `.env.example` to `.env` and fill in what you need. Every variable is listed there with what it does.
With no keys at all, GigBid still runs in **rule mode**: drafts come from templates and the banner in the UI says so.

## Topology

```
browser ──> web (nginx) ──/api──> api ──enqueue──> redis ──> worker ──> LangGraph (bid / conversation graphs)
                                   │  <──pub/sub events──┘          │
                                   │                                ├─ signed per-user token ─> mcp-marketplace ─> GigSim | Upwork MCP
                                   │                                ├─────────────────────────> mcp-portfolio ──> Qdrant
                                   │                                └─────────────────────────> mcp-workspace
                                   └─ Postgres: app tables, LangGraph checkpoints, long-term memory store
```

* **One trace id per run.** It is derived from the thread id, set in the API and worker, sent to the MCP servers
  as `X-Trace-Id`, and written into every audit-log row and every Langfuse trace.
* **Multi-user safety.** The API and worker call the MCP servers with a short-lived JWT, signed with
  `MCP_CALLER_SECRET`, that names the user and their marketplace credentials. Every app query filters on
  `user_id`. OAuth tokens are encrypted at rest with Fernet (`TOKEN_ENCRYPTION_KEY`) and never logged.

## Scheduling (E1)

* **Saved searches.** Each one has its own interval (Settings → Saved searches). Users with none get one
  search per job category, every hour. The worker's `scout` cron runs every minute and starts only the
  searches that are due.
* **Live mode (Upwork) is never scouted more than once per 15 minutes per search**
  (`marketplace.upwork_live.min_read_interval_s: 900`):
  - **Rate:** a freelancer checking the feed by hand does it every 15 to 60 minutes. At that pace GigBid
    behaves like one person reading, not a scraper.
  - **Freshness:** new posts get most of their proposals in the first hours, so 15 minutes loses little
    competitiveness.
  - **Quota:** it keeps us well inside the official MCP server's rate limits, even with several saved
    searches per user. GigSim allows a 15-minute minimum (`worker.min_interval_min`).
* **Weekly Connects budget.** Once a user's proposals this week have spent their weekly budget, the scout
  starts no new drafts until the window rolls over.
* **Idempotency.**
  - The bid thread id is derived from the job id (`bid-u<user>-<job>`), so a job is never analysed twice.
  - Queue jobs use deterministic ids (`run:<thread>`, `resume:<thread>:<approval id>`), and Arq drops
    duplicates.
  - Submits carry idempotency keys derived from the run id. A worker killed mid-submit resumes from its
    Postgres checkpoint and submits exactly once; `tests/integration/test_postgres.py` kills a run right
    after the platform accepted the submit to prove it.

## Budgets and service levels (E5)

Declared in `agent/config.yaml` (`slo`):

| | Target p95 | Target cost |
|---|---|---|
| Job analysed (intake → decision → price) | 8 s | $0.004 |
| Proposal (through writer, critic loop and compliance, to approval) | 30 s | $0.02 |

Measured values are in `evals/results/decisions.json` (`p95_ms`, `usd_per_job`) and `outcomes.json` (`p95_s`, `usd_per_proposal`).
In rule mode they are a fraction of a second and $0. The model-profile numbers are filled in by
`make eval` once `GROQ_API_KEY` is set.

Per-run step, token and cost budgets (`budgets:`) move a thread to **needs attention** rather than letting it run on.

The optimisations that keep runs inside budget:
1. **Skip early.** Risk and fit run before any drafting, so skipped jobs never reach the writer or critic.
2. **Small models for routing and risk.** The cheap nodes run on an 8B model and fall back to it on errors.
3. **Evidence caching.** Embeddings and reranker scores are cached by text hash.

## Deploy

**Option A: one VM with Docker (recommended; keeps everything, including Ollama).** Any VM with 4 GB of RAM
or more and Docker works.
```bash
git clone <repo> && cd <repo>
cp .env.example infra/.env   # set JWT_SECRET, TOKEN_ENCRYPTION_KEY, MCP_CALLER_SECRET, POSTGRES_PASSWORD, GROQ_API_KEY
```
```bash
docker compose -f infra/docker-compose.yml up -d --build
```
```bash
docker compose -f infra/docker-compose.yml exec api python -m apps.api.seed_reviewer --persona ai_ml --analyse 6
```
Put a TLS reverse proxy (Caddy, or the host's own) in front of port 8080. Then set `GIGBID_ENV=production` and
`GIGBID_ALLOW_SIGNUP=0` once the reviewer account exists.

**Option B: a single container (free PaaS tiers).** Build `infra/docker/api.Dockerfile`. It serves the web
app and runs graphs, MCP servers and GigSim in-process: set `GIGBID_EMBED_GIGSIM=1` and point
`GIGSIM_BASE_URL` at the same container's `/gigsim`. Add managed Postgres (`DATABASE_URL`) or a persistent disk
for SQLite. No Redis is needed; the API runs the work itself.

**Reviewer login.** Create it with `seed_reviewer` from environment variables. Share the credentials only in
the private Google Classroom comment, never in the repo.

## When something breaks

| Symptom | Likely cause | What to do |
|---|---|---|
| Red "Marketplace unavailable" banner | GigSim or Upwork down, or rate-limited | Runs park as **queued**; nothing is lost. Check `docker compose logs gigsim mcp-marketplace`, then the worker's sync picks up again |
| Runs stay "Analysing" | Worker down or Redis unreachable | `docker compose ps worker redis`; `docker compose restart worker` (it resumes from checkpoints) |
| A run is **dead_letter** | Retries ran out (timeouts or dropped connections), or a tool error | Open the run viewer for the error. Fix the cause, then use **Analyse** to start a fresh thread or replay from a checkpoint |
| A run is **needs_attention** | A step, token or cost budget was hit | See the run viewer. Raise the budget in `agent/config.yaml` only if the run was legitimate |
| Drafts look template-like | No model key: rule mode | Set `GROQ_API_KEY`, or `GIGBID_MODEL_PROFILE=open_local` with Ollama models pulled |
| Login loop after deploy | `JWT_SECRET` changed or missing | Set a stable `JWT_SECRET`; existing sessions end |
| Upwork connect fails | OAuth app or redirect URI mismatch | `UPWORK_REDIRECT_URI` must equal the callback URL registered with Upwork |
| CI fails "gigsim changed" | Someone edited the provided simulator | Revert. The manifest is only updated when replacing gigsim/ with the official kit, in its own commit: `python scripts/ci/check_gigsim.py --update` |

## Backups

* **Postgres** holds everything that matters: users, settings, runs, checkpoints and memory. Back it up with
  `docker compose exec postgres pg_dump -U gigbid gigbid > backup.sql`.
* **The user portfolio uploads volume** (`userdata`) holds own-profile uploads.
