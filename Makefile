PY ?= .venv/Scripts/python

.PHONY: dev test eval seed demo lint gigsim

seed:            ## regenerate the stand-in starter kit (personas, GigSim seed, dev set)
	$(PY) scripts/make_standin_kit.py

gigsim:          ## run the marketplace simulator on :8100
	$(PY) -m uvicorn gigsim.app:app --port 8100 --reload

test:
	$(PY) -m pytest -q

dev:
	docker compose -f infra/docker-compose.yml up --build

eval:
	@echo "eval runners land in evals/runners/ (next milestone)"

demo:
	@echo "demo script lands with the web app"

lint:
	$(PY) -m ruff check . || true
