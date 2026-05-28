# jita-mcp

Remote MCP server that gives Claude and Gemini ground truth on EVE Online ship
fittings: stat validation and effective DPS/EHP with skills and bonuses
applied. The LLM brings EVE meta knowledge (what's good for what content); this
server answers "does this fit actually work."

## Architecture

```
Claude / Gemini (web)
  └── MCP connector (Streamable HTTP)
        ├── pyfa eve.db  — ships, modules, ammo, dogma, traits (built from
        │                  vendor/pyfa/staticdata via db_update.py)
        ├── eos          — dogma / fitting calculation engine (vendor/pyfa/eos)
        └── Fuzzwork SDE — universe data (regions/systems/stations), reserved
                           for future tools
```

Three independent inputs (our code, the engine + its eve.db, the Fuzzwork
SDE) get baked into one runtime container via a multi-stage Dockerfile. Each
input has its own cache layer so a change in one doesn't invalidate the others.

Live market prices (ESI) intentionally aren't wired up — the tool surface
focuses on the fitting calculus the LLM can't do on its own.

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

### Bootstrap

```bash
git clone --recurse-submodules <repo-url> jita-mcp
cd jita-mcp
git submodule update --init --recursive    # only if you forgot --recurse-submodules
uv sync                                    # creates .venv, installs deps
python3 scripts/fetch_sde.py               # downloads + decompresses SDE (~130MB)
```

### Day-to-day

`uv` is the entry point for everything — no task runner, no Makefile.

| Command                       | What it does                                           |
| ----------------------------- | ------------------------------------------------------ |
| `uv sync`                     | Install / sync Python deps                             |
| `uv run pytest`               | Run the test suite                                     |
| `uv run ruff check`           | Lint                                                   |
| `uv run ruff format`          | Format                                                 |
| `uv run jita-mcp`              | Start the MCP server on :8080                          |
| `python3 scripts/fetch_sde.py` | Idempotent SDE download (pinned by `sde.checksum`)    |

### SDE

The Static Data Export (~700MB uncompressed) is sourced from Fuzzwork and
**pinned by MD5 in `sde.checksum`** so dev/CI/prod builds are reproducible.
`python3 scripts/fetch_sde.py` is idempotent — it skips the download when the
local file already matches the pinned MD5. To pull whatever is currently live
upstream (useful for the SDE-watch workflow), run:

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
jita_mcp/
  server.py              MCP entry point, tool registration
  config.py              env-driven settings
  tools/                 one module per MCP tool
  engine/eos_setup.py    wires pyfa's eos into sys.path; config shim
  engine/_pyfa_shim/     drop-in replacements for pyfa root modules
                         (shadows pyfa's wx-tainted config.py)
  db/eve.py              ship/module/dogma lookups via eos.db (eve.db)
  db/sde.py              reserved for non-ship Fuzzwork lookups
tests/                   pytest, real-DB tests marked @pytest.mark.sde
scripts/
  fetch_sde.py           idempotent Fuzzwork SDE downloader
  build_eve_db.py        runs pyfa's db_update.py through our shim
vendor/
  pyfa/                  git submodule → pyfa-org/Pyfa (vendor/pyfa/eos
                         is the calculation engine; eve.db built locally)
Dockerfile               4-stage build (sde, eos, app, runtime)
sde.checksum             pinned Fuzzwork SDE MD5
```

## License

GPL-3.0-or-later. Required because the project links the eos fitting engine,
which is GPL-3.0.
