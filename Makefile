.DEFAULT_GOAL := help
.PHONY: help install dev lint format typecheck test build check

API_PORT ?= 8000
WEB_PORT ?= 5173
# Slows the fake LLM down just enough to watch tokens stream. It has no effect on real models.
FAKE_LLM_DELAY_MS ?= 30

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-12s %s\n", $$1, $$2}'

install: ## Install Python and web dependencies
	uv sync
	npm --prefix web ci

# npm writes this file on install, so a reinstall only happens when the lockfile changes.
web/node_modules/.package-lock.json: web/package-lock.json
	npm --prefix web ci

dev: web/node_modules/.package-lock.json ## Run the API and UI (fake LLM by default; LLM_MODE=bedrock for real models)
	@trap 'kill 0' INT TERM EXIT; \
	FAKE_LLM_DELAY_MS=$(FAKE_LLM_DELAY_MS) uv run uvicorn policy_drafter.api:create_app \
		--factory --port $(API_PORT) --timeout-graceful-shutdown 1 & \
	API_PORT=$(API_PORT) npm --prefix web run dev -- --port $(WEB_PORT) --strictPort & \
	wait

lint: ## Lint and check formatting
	uv run ruff check .
	uv run ruff format --check .
	npm --prefix web run lint

format: ## Apply formatting and safe lint fixes
	uv run ruff check --fix .
	uv run ruff format .

typecheck: ## Type check Python and TypeScript
	uv run mypy
	npm --prefix web run typecheck

test: ## Run the tests, which are all offline
	uv run pytest
	npm --prefix web test

build: ## Build the web UI
	npm --prefix web run build

check: lint typecheck test build ## Everything CI runs
