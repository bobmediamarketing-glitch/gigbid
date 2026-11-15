PY ?= .venv/Scripts/python

.PHONY: dev test eval eval-table seed demo lint gigsim api web gen-api e2e

seed:            ## regenerate the stand-in starter kit (personas, GigSim seed, dev set)
	$(PY) scripts/make_standin_kit.py

gigsim:          ## run the marketplace simulator on :8100
	$(PY) -m uvicorn gigsim.app:app --port 8100 --reload

test:
	$(PY) -m pytest -q

dev:
	docker compose -f infra/docker-compose.yml up --build

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

demo:
	@echo "demo script lands with the web app"

lint:
	$(PY) -m ruff check . || true
