PY ?= .venv/Scripts/python

.PHONY: dev test eval eval-table seed demo lint gigsim

seed:            ## regenerate the stand-in starter kit (personas, GigSim seed, dev set)
	$(PY) scripts/make_standin_kit.py

gigsim:          ## run the marketplace simulator on :8100
	$(PY) -m uvicorn gigsim.app:app --port 8100 --reload

test:
	$(PY) -m pytest -q

dev:
	docker compose -f infra/docker-compose.yml up --build

eval:           ## regenerate every Part B number and evals/results/RESULTS.md
	$(PY) -m evals.run_all

eval-table:     ## rebuild RESULTS.md from existing results JSON
	$(PY) -m evals.run_all --table-only

demo:
	@echo "demo script lands with the web app"

lint:
	$(PY) -m ruff check . || true
