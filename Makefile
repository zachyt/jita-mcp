.PHONY: help setup sync submodules fetch-sde test lint fmt check run clean

help:
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-14s %s\n", $$1, $$2}'

setup: submodules sync fetch-sde ## One-shot: pull submodules, sync deps, fetch SDE

submodules: ## Initialize / update git submodules (Pyfa)
	git submodule update --init --recursive

sync: ## Install / sync Python deps via uv
	uv sync

fetch-sde: ## Download the SDE pinned in sde.checksum (idempotent)
	python3 scripts/fetch_sde.py

test: ## Run the test suite
	uv run pytest

lint: ## Lint with ruff
	uv run ruff check

fmt: ## Format with ruff
	uv run ruff format

check: lint test ## Lint and test

run: ## Start the MCP server on $EVE_MCP_PORT (default 8080)
	uv run eve-mcp

clean: ## Remove venv, caches, downloaded SDE
	rm -rf .venv .pytest_cache .ruff_cache .pyright data/sde.sqlite data/sde.sqlite.md5
