# ADR 0005: Worker, tracing and deployment

**Status:** accepted · **Date:** 2026-11-15

## Decisions
1. **Arq on Redis for background work.** It is async-native like the graphs, light, and has cron built in.
   The API enqueues one job per graph step, with a deterministic job id (`run:<thread>`,
   `resume:<thread>:<approval id>`), so duplicate requests and double clicks are dropped by the queue itself.
   Without `REDIS_URL` the API runs the same code in-process, which keeps dev, tests and single-container
   deploys simple.
2. **Events flow back through Redis pub/sub.** The worker publishes node and run events on
   `gigbid:events:<user>`; each API process relays them to the browsers it holds over SSE. Any API replica can
   serve any user.
3. **MCP servers as separate services, with signed callers.** In compose, the API and worker talk to the three
   servers over Streamable HTTP. Each call carries a short-lived JWT (`MCP_CALLER_SECRET`) naming the user and
   their marketplace credentials, so the servers stay multi-tenant without a token table per user.
   DNS-rebinding protection stays on, with the service names allow-listed.
4. **Langfuse for tracing.** It has OpenTelemetry under the hood, a LangChain/LangGraph callback and PII
   masking at the client. The trace id is derived from the thread id, so the UI, API, worker, MCP audit rows
   and Langfuse agree without passing ids around.
5. **Postgres with a connection pool** for checkpoints, the memory store and app tables. SQLite stays the
   zero-setup local default.
6. **Qdrant as the vector store service.** Embeddings are still computed locally with fastembed and cached;
   Qdrant only stores and searches them. With `QDRANT_URL` unset, an in-process index gives the same top
   results (tested).
7. **Two deployment shapes from the same code:** the full compose stack on a VM, or one container (API +
   in-process MCP + embedded GigSim) for free PaaS tiers.

## Consequences
The Postgres, Redis-queue and HTTP-MCP paths are all covered by tests that run without Docker:
- `pgserver` for embedded Postgres
- `fakeredis` for the queue
- real subprocesses for the MCP servers

CI additionally builds every image.
