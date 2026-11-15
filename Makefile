PY ?= $(if $(wildcard .venv/Scripts/python.exe),.venv/Scripts/python,.venv/bin/python)

.PHONY: dev local worker check eval-gate test eval eval-table seed demo lint gigsim api web gen-api e2e

seed:            ## regenerate the stand-in starter kit (personas, GigSim seed, dev set)
	$(PY) scripts/make_standin_kit.py

gigsim:          ## run the marketplace simulator on :8100
	$(PY) -m uvicorn gigsim.app:app --port 8100 --reload

test:
	$(PY) -m pytest -q

dev:            ## full stack in Docker: web :8080, API, worker, MCP servers, GigSim, Postgres, Redis, Qdrant, Ollama
	docker compose -f infra/docker-compose.yml up --build

local:          ## no Docker: GigSim + API (serving the built web app) in-process, http://localhost:8000
	npm --prefix apps/web run build && $(PY) -m uvicorn apps.api.main:app --port 8000

worker:         ## Arq worker (needs REDIS_URL)
	$(PY) -m arq worker.tasks.WorkerSettings

check:          ## the CI repo rules: secrets, gigsim unchanged, prompts in agent/prompts, traceable numbers
	$(PY) scripts/ci/check_secrets.py && $(PY) scripts/ci/check_gigsim.py && $(PY) scripts/ci/check_prompts.py && $(PY) scripts/ci/check_numbers.py

eval-gate:      ## the CI smoke eval with thresholds (evals/thresholds.json)
	$(PY) scripts/ci/eval_gate.py

api:            ## API on :8000 (needs GigSim on :8100: make gigsim)
	$(PY) -m uvicorn apps.api.main:app --port 8000 --reload

web:            ## web dev server on :5173 (proxies /api to :8000)
	npm --prefix apps/web run dev

gen-api:        ## regenerate the typed TS client from the API's OpenAPI schema
	$(PY) scripts/export_openapi.py && npm --prefix apps/web run gen:api

e2e:            ## Playwright tests against a fresh GigSim + API serving the production build
	npm --prefix apps/web run build && npm --prefix apps/web run test:e2e

eval:           ## regenerate every Part B number and evals/results/RESULTS.md
	$(PY) -m evals.run_all

eval-table:     ## rebuild RESULTS.md from existing results JSON
	$(PY) -m evals.run_all --table-only

demo:           ## seed the reviewer account (REVIEWER_EMAIL/PASSWORD from env) and analyse a few jobs
	$(PY) -m apps.api.seed_reviewer --persona ai_ml --analyse 6

lint:
	$(PY) -m ruff check . && npm --prefix apps/web run typecheck
