# Only composition / multi-step targets live here. For everything else, use uv
# directly: `uv sync`, `uv run pytest`, `uv run ruff check`, `uv run eve-mcp`.

.PHONY: help setup fetch-sde clean

help:
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-12s %s\n", $$1, $$2}'

setup: ## One-shot bootstrap: pull submodules, sync deps, fetch SDE
	git submodule update --init --recursive
	uv sync
	python3 scripts/fetch_sde.py

fetch-sde: ## Download the SDE pinned in sde.checksum (idempotent)
	python3 scripts/fetch_sde.py

clean: ## Remove venv, caches, downloaded SDE
	rm -rf .venv .pytest_cache .ruff_cache .pyright data/sde.sqlite data/sde.sqlite.md5
