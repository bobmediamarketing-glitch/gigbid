# GigSim (stand-in)

Stand-in marketplace simulator, used until the official AI-4016 GigSim is released (see
`docs/adr/0001-standin-starter-kit.md`). Seed data comes from `scripts/make_standin_kit.py`.

```bash
uvicorn gigsim.app:app --port 8100
```

Auth: `Authorization: Bearer gigsim-<persona>-token` (personas: `ai_ml`, `fullstack`, `data_analyst`).
Writes need an `Idempotency-Key` header and accept `dry_run`. Rate limit, error rate, clock speed and
Connects rules come from env vars and `policy/v*.yaml`. Admin endpoints (`X-Admin-Token`):
`/admin/outage`, `/admin/advance`, `/admin/reset`, `/admin/score` (evaluation only).
