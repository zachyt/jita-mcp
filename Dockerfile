# syntax=docker/dockerfile:1.7

# Multi-stage build:
#   sde   — Fuzzwork SDE (reserved for future universe/region tools)
#   pyfa  — pyfa's eos calculation engine + eve.db built from staticdata
#   app   — uv venv with our deps + project
#   runtime — assembles the above
# Each stage's cache key is dominated by one independent input so a change
# in one doesn't invalidate the others.

ARG PYTHON_VERSION=3.12


# ---------------------------------------------------------------------------
# Stage: sde
# Downloads + decompresses Fuzzwork's SQLite SDE pinned in sde.checksum.
# Currently used only by future Fuzzwork-backed tools; baked in so it's
# ready the moment we need it.
# ---------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS sde
WORKDIR /work
COPY sde.checksum ./
COPY scripts/fetch_sde.py ./scripts/fetch_sde.py
RUN python3 scripts/fetch_sde.py
# Output: /work/data/sde.sqlite (~530MB)


# ---------------------------------------------------------------------------
# Stage: pyfa
# Carries pyfa's eos source AND builds eve.db (94MB) by running pyfa's
# db_update.py through our import shim. Layer cache invalidates only when
# vendor/pyfa/eos, vendor/pyfa/staticdata, vendor/pyfa/db_update.py, our
# build script, or the engine setup change.
# ---------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS pyfa
COPY --from=ghcr.io/astral-sh/uv:0.5.14 /uv /uvx /bin/

ENV UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/work/.venv \
    UV_PYTHON_PREFERENCE=only-system \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /work

# Minimal uv install of the runtime deps eos needs (sqlalchemy + logbook).
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# Bring in only what build_eve_db.py needs.
COPY jita_mcp ./jita_mcp
COPY scripts/build_eve_db.py ./scripts/build_eve_db.py
COPY vendor/pyfa/eos ./vendor/pyfa/eos
COPY vendor/pyfa/utils ./vendor/pyfa/utils
COPY vendor/pyfa/db_update.py ./vendor/pyfa/db_update.py
COPY vendor/pyfa/staticdata ./vendor/pyfa/staticdata

# Install our project so jita_mcp.engine.eos_setup is importable, then build.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev
RUN .venv/bin/python scripts/build_eve_db.py
# Outputs: /work/vendor/pyfa/eos/ and /work/vendor/pyfa/eve.db


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
COPY --from=sde  /work/data/sde.sqlite       ./data/sde.sqlite
COPY --from=pyfa /work/vendor/pyfa/eos       ./vendor/pyfa/eos
COPY --from=pyfa /work/vendor/pyfa/utils     ./vendor/pyfa/utils
COPY --from=pyfa /work/vendor/pyfa/eve.db    ./vendor/pyfa/eve.db
COPY --from=app  /app/.venv                  ./.venv
COPY --from=app  /app/jita_mcp               ./jita_mcp

# Non-root user for the running process.
RUN useradd --system --uid 1000 --no-create-home eve \
    && chown -R eve:eve /app
USER eve

EXPOSE 8080

CMD ["uvicorn", "jita_mcp.server:app", "--host", "0.0.0.0", "--port", "8080"]
