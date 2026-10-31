.DEFAULT_GOAL := help
.PHONY: help install lint format typecheck test check

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-12s %s\n", $$1, $$2}'

install: ## Install Python dependencies
	uv sync

lint: ## Lint and check formatting
	uv run ruff check .
	uv run ruff format --check .

format: ## Apply formatting and safe lint fixes
	uv run ruff check --fix .
	uv run ruff format .

typecheck: ## Type check
	uv run mypy

test: ## Run the tests, which are all offline
	uv run pytest

check: lint typecheck test ## Everything CI runs
