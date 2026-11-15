# Tools

Every capability an agent uses is an MCP tool with a schema, an owner and a test. Schemas are frozen by
`tests/contract/snapshots/*.json`; CI fails if a signature changes without regenerating them.

Auth column: **bearer** = HTTP endpoint requires `Authorization: Bearer <token>` (per-user token table in env);
stdio/in-memory transports run as the host process user.

## Our servers

| Tool | Server | R/W | Annotations | Auth | Notes |
|---|---|---|---|---|---|
| `marketplace_health` | marketplace | read | readOnly, idempotent, openWorld | bearer | drives the "marketplace unavailable" banner |
| `get_platform_policy` | marketplace | read | readOnly, idempotent, openWorld | bearer | Connects rules; change request lands here |
| `search_jobs` | marketplace | read | readOnly, idempotent, openWorld | bearer | Scout |
| `get_job` | marketplace | read | readOnly, idempotent, openWorld | bearer | output is untrusted text |
| `get_client_history` | marketplace | read | readOnly, idempotent, openWorld | bearer | Risk Assessor |
| `get_price_stats` | marketplace | read | readOnly, idempotent, openWorld | bearer | Pricing Strategist |
| `get_connects_balance` | marketplace | read | readOnly, idempotent, openWorld | bearer | Pricing Strategist |
| `list_messages` | marketplace | read | readOnly, idempotent, openWorld | bearer | Client Liaison; output is untrusted text |
| `list_events` | marketplace | read | readOnly, idempotent, openWorld | bearer | pipeline board updates |
| `create_proposal_draft` | marketplace | write | not destructive, idempotent (key), openWorld | bearer | idempotency key + dry_run; after approval only |
| `submit_proposal` | marketplace | write | **destructive**, idempotent (key), openWorld | bearer | spends Connects; idempotency key + dry_run |
| `send_message` | marketplace | write | **destructive**, idempotent (key), openWorld | bearer | idempotency key + dry_run |
| `search_evidence` | portfolio | read | readOnly, idempotent, closed world | bearer | retriever variant from config |
| `get_case_study` | portfolio | read | readOnly, idempotent, closed world | bearer | |
| `list_skills` | portfolio | read | readOnly, idempotent, closed world | bearer | |
| `free_slots` | workspace | read | readOnly, idempotent, closed world | bearer | local mock calendar |
| `list_holds` | workspace | read | readOnly, idempotent, closed world | bearer | |
| `create_interview_hold` | workspace | write | not destructive, idempotent (key) | bearer | tentative only, invites nobody |
| `create_email_draft` | workspace | write | not destructive, idempotent (key) | bearer | draft only, never sends |

Portfolio resources: `portfolio://case/{id}`, `portfolio://proposal/{id}`, `portfolio://repo/{id}`,
`portfolio://review/{id}`, `portfolio://cv`. Prompts: `answer_screening_question`, `prove_requirement`, `opening_line`.

Every marketplace and workspace call is written to an append-only, PII-masked audit log
(`data/audit/*.jsonl`: user, tenant, tool, arguments, result summary, trace id).

## Third-party servers (not written by us)

| Server | Used for | Trust rationale |
|---|---|---|
| Upwork official MCP (`https://mcp.upwork.com/mcp`) | live-mode marketplace behind the same port | Operated by the platform itself under OAuth 2.1; every write is a draft the user confirms on Upwork, so GigBid cannot send on its own. |
| GitHub official MCP (`github/github-mcp-server`) | ingesting the freelancer's repos (READMEs, code) | Maintained by GitHub, read-only token scoped to the user's public repos; we use only repo/file read tools. |

Tool names for the Upwork server are mapped in `agent/config.yaml` (`marketplace.upwork_live.tool_map`) and
checked against `list_tools()` on connect, so an upstream rename fails loudly.
