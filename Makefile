.PHONY: setup test lint run eval-dry-run eval-pilot docker-up docker-down clean

PYTHON ?= .venv/bin/python
ifeq ($(OS),Windows_NT)
	PYTHON = .venv/Scripts/python.exe
endif

setup:
	pip install -e ".[dev]"

test:
	$(PYTHON) -m pytest -v

lint:
	$(PYTHON) -m ruff check .
	$(PYTHON) -m mypy schemas ingestion extraction symbolic agents retrieval eval storage api

run:
	$(PYTHON) -m uvicorn api.main:app --reload --port 8000

eval-dry-run:
	$(PYTHON) -m eval.run --config configs/eval.yaml --dry-run --pilot

eval-pilot:
	$(PYTHON) -m eval.run --config configs/eval.yaml --pilot

docker-up:
	docker compose up -d --build

docker-down:
	docker compose down

clean:
	rm -rf .pytest_cache .eval_cache __pycache__ dist build *.egg-info
