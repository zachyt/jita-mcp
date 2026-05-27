# eve-mcp

Remote MCP server that gives Claude and Gemini ground truth on EVE Online ship
fittings: stat validation, effective DPS/EHP with skills and bonuses applied,
and live market prices. The LLM brings EVE meta knowledge (what's good for
what content); this server answers "does this fit actually work and what does
it cost."

## Architecture

```
Claude / Gemini (web)
  └── MCP connector (Streamable HTTP)
        ├── SDE      — static data export (ships, modules, dogma, skills)
        ├── eos      — dogma / fitting calculation engine (TBD: vendored Pyfa)
        └── ESI      — live market prices, cached
```

Three independent inputs (our code, the engine, the SDE) get baked into one
runtime container via a multi-stage Dockerfile. Each input has its own cache
layer so a change in one doesn't invalidate the others.

## Tools

| Tool                       | Purpose                                              |
| -------------------------- | ---------------------------------------------------- |
| `get_ship_info`            | Slot layout, fitting room, base resists, bonuses     |
| `get_modules_for_goal`     | Ranked modules toward a goal (ehp, dps, speed, …)    |
| `get_modules_by_attribute` | Ranked modules by a specific dogma attribute         |
| `calculate_fit`            | Validate a full fit; return all stats and errors     |
| `export_eft`               | EFT string + required-skills list for a valid fit    |

## Dev setup

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/). On macOS:

```bash
brew install uv
```

### One-shot bootstrap

```bash
git clone --recurse-submodules <repo-url> eve-mcp
cd eve-mcp
make setup        # pulls submodules, syncs deps, fetches the SDE (~130MB download)
```

If you already cloned without `--recurse-submodules`:

```bash
git submodule update --init --recursive
```

### Day-to-day

`uv` is the entry point for everything; the Makefile only carries multi-step
composition targets.

| Command                  | What it does                                          |
| ------------------------ | ----------------------------------------------------- |
| `uv sync`                | Install / sync Python deps                            |
| `uv run pytest`          | Run the test suite                                    |
| `uv run ruff check`      | Lint                                                  |
| `uv run ruff format`     | Format                                                |
| `uv run eve-mcp`         | Start the MCP server on :8080                         |
| `make setup`             | submodules + `uv sync` + fetch SDE (one-shot bootstrap) |
| `make fetch-sde`         | Idempotent SDE download                               |
| `make clean`             | Remove venv, caches, downloaded SDE                   |

### SDE

The Static Data Export (~700MB uncompressed) is sourced from Fuzzwork and
**pinned by MD5 in `sde.checksum`** so dev/CI/prod builds are reproducible.
`make fetch-sde` is idempotent — it skips the download when the local file
already matches the pinned MD5. To pull whatever is currently live upstream
(useful for the SDE-watch workflow), run:

```bash
python3 scripts/fetch_sde.py --version latest
```

### Submodule (Pyfa)

The fitting engine lives at `vendor/pyfa/` as a git submodule pinned to a
specific Pyfa commit. The pin moves only via an explicit
`git submodule update --remote vendor/pyfa && git commit` — automated by a
scheduled GitHub Action that opens a PR when upstream advances.

## Project layout

```
src/eve_mcp/
  server.py             MCP entry point, tool registration
  config.py             env-driven settings
  tools/                one module per MCP tool
  engine/               dogma / fitting engine wrapper (eos)
  db/sde.py             SDE query helpers (all SQL lives here)
  esi/                  ESI client + price cache
tests/
  fixtures/             tiny synthetic SDE for unit tests
scripts/
  fetch_sde.py          idempotent SDE downloader (TODO)
vendor/
  eos/                  git submodule → forked fitting engine (TODO)
```

## License

GPL-3.0-or-later. Required because the project links the eos fitting engine,
which is GPL-3.0.
