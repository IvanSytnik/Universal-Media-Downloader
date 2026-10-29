# Developer shortcuts. Run `make help` for the list of targets.
#
# Local targets (install, lint, format, test*) run against the active
# Python environment; Docker targets (up, down, logs, migrate) drive the
# Compose stack.

.DEFAULT_GOAL := help

PYTHON  ?= python3
COMPOSE ?= docker compose

# Coverage gate for the core layers — keep in sync with .github/workflows/ci.yml.
COV_ARGS := --cov=src/domain --cov=src/application --cov-report=term-missing --cov-fail-under=90

.PHONY: help install lint format test test-cov up down logs migrate

help: ## Show this help
	@awk 'BEGIN {FS = ":.*##"; printf "Usage: make \033[36m<target>\033[0m\n\nTargets:\n"} \
		/^[a-zA-Z_-]+:.*##/ { printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

install: ## Install the project with dev dependencies (editable)
	$(PYTHON) -m pip install -e ".[dev]"

lint: ## Run ruff (lint + format check) and mypy --strict
	$(PYTHON) -m ruff check src tests
	$(PYTHON) -m ruff format --check src tests
	$(PYTHON) -m mypy --strict src tests/unit/test_ytdlp_downloader.py

format: ## Auto-format and apply safe lint fixes
	$(PYTHON) -m ruff format src tests
	$(PYTHON) -m ruff check --fix src tests

test: ## Run the test suite
	$(PYTHON) -m pytest

test-cov: ## Run tests with the domain/application coverage gate
	$(PYTHON) -m pytest $(COV_ARGS)

up: ## Build and start the full stack in the background
	$(COMPOSE) up --build -d

down: ## Stop the stack (volumes are kept)
	$(COMPOSE) down

logs: ## Follow bot and worker logs
	$(COMPOSE) logs -f bot worker

migrate: ## Apply Alembic migrations (one-shot migrate service)
	$(COMPOSE) run --rm migrate
