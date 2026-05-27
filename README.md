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

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run pytest
uv run eve-mcp     # starts the server on :8080
```

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
