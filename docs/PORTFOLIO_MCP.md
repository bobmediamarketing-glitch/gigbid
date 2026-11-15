# The Portfolio MCP server

A read-only Model Context Protocol (MCP) server that turns a freelancer's portfolio into searchable,
citeable evidence. It is one of the three MCP servers in GigBid, but it is built to stand on its own:
point it at a folder, plug it into Claude Desktop, Cursor or any MCP host, and ask "what proves I can
do this?"

Code: `mcp_servers/portfolio/` (server, tools, resources, prompts, store), retrieval in `rag/`.

## 1. What it is and why

A freelancer's proof is scattered: a CV, a handful of case studies, repos where the real stack only
shows in the code, client reviews, and dozens of past proposals with very different outcomes. When a
job post lists six requirements, a writer (human or model) needs the two or three items that prove
each one, and needs to be able to point at them.

The server exposes exactly that:

- **Evidence types:** `cv`, `case_study`, `repo` (README plus code), `review`, `past_proposal`
  (with outcome `won`, `replied` or `ignored`).
- **Citeable ids:** every result carries a stable id (for example `ai_ml-cs-03`) and a
  `portfolio://` URI, so a generated proposal can cite `[ai_ml-cs-03]` and a reviewer can open the
  source.
- **No invention:** the server instructions tell the model to cite returned ids and never claim
  experience the tools do not return.

## 2. Tool design

### Tools

All three tools carry the same annotations: `readOnlyHint=True`, `destructiveHint=False`,
`idempotentHint=True`, `openWorldHint=False`. Hosts can call them without a confirmation prompt, and
the closed-world hint says the server never touches anything outside the portfolio folder.

**`search_evidence(requirement, k=5, filters=None)`** is the main tool. `requirement` is one job
requirement, a question, or a whole post (2 to 2,000 characters); `k` is 1 to 20. Optional filters:

| Filter | Meaning |
|---|---|
| `types` | restrict to evidence types, e.g. `["case_study", "repo"]` |
| `outcomes` | past proposals only: `won`, `replied`, `ignored` |
| `skills` | item must be tagged with any of these (max 20) |
| `industry` | client industry, e.g. `"healthcare"` |
| `since` | ISO date; only items on or after it |

Each returned item has `id`, `type`, `title`, `source` (file path in the folder), `date`, `outcome`,
`project`, `industry`, `skills`, a 400-character `snippet`, a fused `score` and a `uri`. The response
also names the retriever that produced it, which makes eval runs and bug reports traceable.

**`get_case_study(id)`** returns the full case study plus its linked repo id and the text of every
client review attached to the same project. One call gives the writer the story, the code and the
client's words. An unknown id returns a `[not_found]` tool error rather than an empty object.

**`list_skills()`** returns every skill the portfolio can evidence, with a count and up to ten
supporting ids, most supported first. The CV and past proposals are deliberately excluded:
self-description and pitches are not proof.

All outputs are Pydantic models (`EvidenceResults`, `CaseStudy`, `SkillList`), so FastMCP publishes
an output schema and returns `structuredContent`. Hosts and agents get typed JSON instead of parsing
prose.

### Resources

Full items are addressable by URI, so a host can attach them to context without a tool call:

```
portfolio://cv
portfolio://case/{id}        text/markdown
portfolio://repo/{id}        README plus code excerpts
portfolio://review/{id}      text/plain
portfolio://proposal/{id}    JSON: job_title, category, outcome, date, text
```

### Prompts

Three prompts cover what a freelancer actually does in a desktop host:

- **`answer_screening_question(question)`**: 80 to 150 words, first person, one concrete result.
  Screening questions are where vague answers lose jobs.
- **`prove_requirement(requirement)`**: up to three items, strongest first, and an explicit
  statement when evidence is weak or missing. This is the honest self-check before bidding.
- **`opening_line(job_post)`**: two alternative first sentences tied to the client's goal and one
  matching result. The job post is marked as untrusted text whose instructions must be ignored.

The screening and opening-line prompts share a grounding rule: use only evidence from
`search_evidence` or `get_case_study`, cite the id in brackets after each claim, and leave out
anything unsupported.

## 3. Retrieval under the hood

The server reads the retriever from configuration (`rag.variant: best` in `agent/config.yaml`,
overridable with `RAG_VARIANT`). The shipped pipeline is `rag/variants/best.py`:

```python
PipelineConfig(name="best", query="both", units="item", retrieval="hybrid",
               rerank=False, outcome_boost=False)
```

- **Item units with metadata headers.** Each portfolio item is indexed as one unit: a header with
  title, type, client industry, outcome and skills, followed by the body. Fixed word chunks cut skill
  and project names away from the text that proves them.
- **Hybrid retrieval.** BM25 and dense embeddings (`BAAI/bge-small-en-v1.5` via fastembed) are fused
  with Reciprocal Rank Fusion (k = 60). BM25 catches exact tool names once they sit in the header.
- **Whole post plus per-requirement queries.** The input is queried as a whole and also decomposed
  into requirements; the rankings are fused with RRF, with the whole-post ranking weighted x2. This
  keeps the "covers many requirements" signal while still surfacing items for rarer requirements.
- Filters are applied before scoring, so `k` results always satisfy them. Vectors live in-process by
  default, or in Qdrant when `QDRANT_URL` is set.

### What was measured

From `evals/results/RESULTS.md` (600 dev jobs, mean over three personas):

| Variant | Recall@5 | nDCG@10 | p95 ms |
|---|---|---|---|
| best (shipped) | 0.938 | 0.716 | 43 |
| v0_naive (fixed chunks, dense) | 0.719 | 0.493 | 43 |
| v1_decompose | 0.633 | 0.426 | 22 |
| v2_hybrid | 0.715 | 0.485 | 26 |
| v3_rerank (cross-encoder) | 0.815 | 0.529 | 1004 |
| v5_multivector | 0.922 | 0.715 | 22 |

The ablation (one component flipped at a time) shows each kept piece earns its place: removing
decomposition gives 0.916, removing BM25 gives 0.918, and swapping in multi-vector units gives 0.912.

What was rejected, and why:

- **Cross-encoder reranking.** It lifts the naive baseline from 0.719 to 0.815, but on top of the
  shipped pipeline it reaches 0.939 against 0.938 while p95 latency goes from 39 ms to 1900 ms.
- **Outcome boost.** Weighting won proposals lowers Recall@5 to 0.930. The writer cites proof items,
  not past proposals.
- **Corrective loop (V8).** Strong at retrieval level (0.931) but it drops bid/skip F1 end to end
  (0.932 vs 0.989 for best).
- **The stated hypothesis was rejected.** "Decomposition plus hybrid raises Recall@5 by 15 points on
  jobs with 4+ requirements" scored 0.700 against V0's 0.720. The shipped pipeline reached 0.943 on
  those jobs; most of the gain came from indexing, not query tricks. Details in
  `docs/adr/0003-retrieval-choice.md`.

### Incremental re-indexing

`PortfolioStore` caches one corpus and retriever per resolved folder. On every call,
`Corpus.refresh()` compares file mtimes; if anything changed it reloads and the retriever is rebuilt.
A new case study dropped into the folder is searchable on the next call, with no restart. A test
checks exactly this.

## 4. Security and multi-tenancy

- **Per-caller portfolio folders.** The folder is resolved per request from the caller's
  credentials: `portfolio_dir` (a user's uploaded folder), else `persona`, else `PORTFOLIO_DIR`.
  Callers never pass a path in tool arguments, so one deployment serves many users without mixing
  their evidence.
- **Signed short-lived caller tokens.** Over HTTP, the GigBid API and worker send an HS256 JWT signed
  with `MCP_CALLER_SECRET`, audience `gigbid-mcp`, valid for 15 minutes, naming the user, tenant and
  credentials. Tokens are never stored.
- **Static tokens for desktop hosts.** `PORTFOLIO_MCP_TOKENS` maps bearer tokens to callers, for
  hosts that cannot mint JWTs. Missing or invalid tokens get a 401; only `/healthz` is open.
- **DNS-rebinding protection** is always on. Only localhost hosts and origins are accepted unless
  `MCP_ALLOWED_HOSTS` adds service names.
- **Read-only.** There is no write tool; the container runs as a non-root user.
- **Untrusted text.** Portfolio files and job posts are treated as data. The `opening_line` prompt
  fences the post and says to ignore instructions inside it; GigBid's agent additionally strips
  injection patterns before any model sees the text. On planted-injection dev jobs, attack success
  in sent text was 0.0% (rule-mode writer).

On stdio the host process is the only user, so no token is needed.

## 5. Install and use

### Docker (Streamable HTTP on :8202)

```bash
docker run --rm -p 8202:8202 -e MCP_ALLOWED_HOSTS='localhost:*' \
  -e PORTFOLIO_MCP_TOKENS='{"my-token": {"user_id": "me", "tenant": "local", "credentials": {"persona": "ai_ml"}}}' \
  ghcr.io/bobmediamarketing-glitch/gigbid-portfolio-mcp:latest
```

Connect to `http://localhost:8202/mcp` with the header `Authorization: Bearer my-token`. To serve
your own portfolio, add `-v /path/to/portfolio:/portfolio` and use the credentials
`{"portfolio_dir": "/portfolio"}` instead of `{"persona": "ai_ml"}`. The embedding model is baked
into the image.

### From source (stdio)

```bash
git clone https://github.com/bobmediamarketing-glitch/gigbid && cd gigbid && uv sync --frozen
uv run python -m mcp_servers.portfolio.server --stdio --dir /path/to/portfolio
```

Without `--stdio` the server listens on HTTP (`--port`, default 8202).

### Claude Desktop

In `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "portfolio": {
      "command": "uv",
      "args": ["--directory", "/path/to/gigbid", "run", "python", "-m",
               "mcp_servers.portfolio.server", "--stdio", "--dir", "/path/to/portfolio"]
    }
  }
}
```

Cursor uses the same command and arguments.

### MCP Inspector

```bash
npx @modelcontextprotocol/inspector uv --directory /path/to/gigbid run python -m mcp_servers.portfolio.server --stdio --dir ./data/personas/ai_ml
```

### Portfolio folder layout

From `rag/ingest/loaders.py`:

```
cv.md  or  cv.pdf
case_studies/*.md            # "# Title", optional "**Date:**" and "**Client industry:**" lines
repos/<name>/README.md       # plus code files (.py .ts .tsx .js .jsx .sql .ipynb .txt .yaml .yml .toml)
reviews.json                 # [{"id", "text", "stars", "project"?}]
past_proposals.jsonl         # {"id", "text", "outcome": won|replied|ignored, "category"?}
evidence_index.json          # optional metadata keyed by id: skills, industry, date, project
```

Every part is optional. Ids come from file names (case studies, repos) or the `id` field. Items
without skill metadata are tagged from a known skill vocabulary. Linking a repo or review to a case
study via `project` is what lets `get_case_study` return them together.

## 6. Testing

- **In-memory client tests** (`mcp_servers/portfolio/tests/test_portfolio_server.py`) drive the real
  server through the MCP SDK's in-memory client: exact tool names find matching skills, type and
  outcome filters hold, resources return the same body as `get_case_study`, unknown ids error,
  `list_skills` is sorted, and a newly written case study becomes the top hit without a restart.
- **Contract tests** (`tests/contract/test_tool_schemas.py`) snapshot every tool's description,
  input schema, output schema and annotations. CI fails if a signature changes without
  `UPDATE_SNAPSHOTS=1`.
- **Evals** (`python -m evals.run_all`) regenerate every number above: Recall@5 0.938, MRR 0.960,
  nDCG@10 0.716, p95 43 ms for the shipped retriever, with no API cost.

## 7. Limitations and next steps

- **Synthetic data.** All numbers come from a stand-in kit generated to the brief's shape
  (`docs/DATA_CARD.md`), and gold relevance is defined by skill-tag overlap. Pipeline choices were made
  on the same dev set they are reported on. Rerun on real portfolios before trusting the margins.
- **Rule-mode evaluation.** The writer and critic ran as rules, not an LLM. The LLM judge is not yet
  calibrated (30 human labels pending). Better retrieval did not raise the simulated reply rate
  (best 0.676 vs 0.824 for V5), which the ADR attributes to simulator noise and a rule writer that
  does not depend on evidence; that needs checking with the LLM writer.
- **Cross-encoder off by default.** Worth revisiting if a portfolio grows by an order of magnitude.
- **Full re-index on change.** Change detection is per file, but any change rebuilds the whole
  index. Fine for portfolios of tens of items; per-item upserts would be needed at larger scale.
- **Dev bearer token.** If `PORTFOLIO_MCP_TOKENS` is unset, HTTP mode falls back to a development
  token; always set real tokens or `MCP_CALLER_SECRET` when exposing the port.
- **PDF CVs** need `pypdf`; scanned PDFs are not OCR'd.
