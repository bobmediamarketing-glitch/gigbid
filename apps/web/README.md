# GigBid web app

React + TypeScript (Vite). FastAPI serves the built app in production, so the browser talks to one origin:
the session cookie and Server-Sent Events work without CORS.

```bash
make gigsim      # simulator on :8100
make api         # FastAPI on :8000
make web         # this app on :5173, proxying /api to :8000
```

## The typed API contract
`src/lib/api-types.ts` is **generated**, so don't edit it by hand. After changing an API model, run:

```bash
make gen-api     # export OpenAPI from FastAPI, regenerate the TS types
```

The agents' own Pydantic hand-offs (`JobSpec`, `RiskReport`, `ProposalDraft`, ...) are API response models, so
the UI is type-checked against exactly what the graph produces.

## Screens
| Route | Screen |
|---|---|
| `/login`, `/onboarding` | Sign in or up; pick a persona or your own profile; connect GigSim or Upwork; set rates, categories and the weekly Connects budget; upload a portfolio |
| `/inbox` | Jobs ranked by fit, with risk badges, the recommended action, price and Connects cost; analyse, skip or open |
| `/jobs/:id` | JobSpec, risk report, a requirement-to-evidence matrix, price rationale and the bid/skip reasoning |
| `/studio/:thread` | The draft, with evidence on hover or focus for every claim. Critic and Compliance notes, claim check, regenerate a paragraph, dry-run cost; approve, edit or reject with a reason |
| `/approvals` | Everything waiting for you (it survives refreshes and restarts, because it's read from the checkpoint) |
| `/pipeline` | Kanban from drafted to hired or lost, updated live from marketplace events |
| `/messages` | Client threads with a suggested reply and interview slots; approve before sending |
| `/runs`, `/runs/:thread` | Node-by-node live progress (SSE), checkpoint history and a trace link |
| `/analytics` | Reply and hire rate by category, Connects against outcomes, cost and latency per proposal, rejection and skip reasons |
| `/settings` | Autonomy, budgets, saved searches, connected accounts, and the memory viewer (see and delete learned rules) |

## Tests
```bash
make e2e         # 5 Playwright tests: onboarding, approve, reject with a reason, edit a draft, degraded-mode banner
```
They start their own GigSim (:8101) and API (:8001), with fresh databases under `test-results/`.
The HTML report is written to `playwright-report/`.
