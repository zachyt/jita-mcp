# syntax=docker/dockerfile:1.7

# Multi-stage build with three independent inputs (SDE, eos, app deps + code)
# and one runtime stage that assembles them. Each input has its own cache
# layer so a change in one doesn't invalidate the others.

ARG PYTHON_VERSION=3.12


# ---------------------------------------------------------------------------
# Stage: sde
# Downloads + decompresses the SQLite SDE pinned in sde.checksum.
# Layer cache invalidates only when sde.checksum changes.
# ---------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS sde
WORKDIR /work
COPY sde.checksum ./
COPY scripts/fetch_sde.py ./scripts/fetch_sde.py
RUN python3 scripts/fetch_sde.py
# Output: /work/data/sde.sqlite (~530MB)


# ---------------------------------------------------------------------------
# Stage: eos
# Isolates Pyfa's eos subdir as its own COPY layer so unrelated runtime
# layers don't invalidate when upstream Pyfa moves.
# ---------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS eos
WORKDIR /work
COPY vendor/pyfa/eos ./eos
# Output: /work/eos/


# ---------------------------------------------------------------------------
# Stage: app
# Builds a fresh .venv with all runtime deps + our package.
# Two-step install: deps-only first (cache-friendly), then project.
# ---------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS app
# uv version pinned; bump intentionally
COPY --from=ghcr.io/astral-sh/uv:0.5.14 /uv /uvx /bin/

ENV UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_PYTHON_PREFERENCE=only-system \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Deps layer: invalidates only when pyproject.toml / uv.lock change.
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# Project layer: invalidates only when our package source changes.
COPY jita_mcp ./jita_mcp
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev


# ---------------------------------------------------------------------------
# Stage: runtime
# Slim image with only what's needed at runtime — no uv, no build tools.
# ---------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH" \
    JITA_MCP_SDE_PATH=/app/data/sde.sqlite \
    JITA_MCP_HOST=0.0.0.0 \
    JITA_MCP_PORT=8080

WORKDIR /app

# Order: largest / least-changing first so they cache best.
COPY --from=sde /work/data/sde.sqlite ./data/sde.sqlite
COPY --from=eos /work/eos ./vendor/pyfa/eos
COPY --from=app /app/.venv ./.venv
COPY --from=app /app/jita_mcp ./jita_mcp

# Non-root user for the running process.
RUN useradd --system --uid 1000 --no-create-home eve \
    && chown -R eve:eve /app
USER eve

EXPOSE 8080

CMD ["uvicorn", "jita_mcp.server:app", "--host", "0.0.0.0", "--port", "8080"]
