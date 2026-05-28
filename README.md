# jita-mcp

An MCP server that lets Claude (and any other MCP-compatible LLM) actually fit
EVE Online ships. The LLM brings the meta knowledge — what's good for what
content — and `jita-mcp` answers the ground-truth questions: *does this fit
work, what does it actually do, what does it cost?*

Stats are computed by pyfa's fitting engine, so ship bonuses, skill
multipliers, ammo selection, drone DPS, implant effects, and stacking
penalties are all applied correctly. Module prices come live from ESI
(Jita 4-4 sell-min, cached per ESI's rules).

## What you can ask Claude

> "Build me a kinetic-DPS Condor at All V. Use jita-mcp."

> "I have a Vexor with Hammerhead IIs. What's the best low-slot DPS mod and
> tank for a buffer fit? Keep it under 50M ISK."

> "Validate this Manticore fit and tell me if it's cap-stable."

> "Export this fit to EFT and list every skill I need."

## Tools

| Tool | What it does |
| --- | --- |
| `get_ship_info` | Slot layout, fitting room, base HP and resists, capacities (cargo + drone bay + every specialised hold), ship bonuses, required skills. |
| `get_modules_for_goal` | Ranked module candidates for a goal + slot (max DPS, max EHP, max speed, specific damage types). Auto-picks best ammo for damage goals. Returns Jita 4-4 prices per candidate. |
| `calculate_fit` | Validates a complete fit. Returns CPU/PG/calibration/drone bay usage, DPS by damage type, EHP per layer, resists, capacitor stability, mobility, sensor stats, total ISK cost, and a list of any problems with actionable messages. |
| `export_eft` | Formats a fit as the EFT string EVE / pyfa accept on paste-in, plus the full recursive skill prerequisite list. |

The full schemas are exposed via MCP's `list_tools`; Claude reads them
automatically.

## Quick start

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
# 1. Clone with submodules (pyfa is vendored)
git clone --recurse-submodules https://github.com/zachyt/jita-mcp
cd jita-mcp

# 2. Install deps + build pyfa's data DB (one-time, ~10s)
uv sync
uv run python scripts/build_eve_db.py

# 3. (Optional) Download the Fuzzwork SDE if you want it ready for future
#    universe-data tools
python3 scripts/fetch_sde.py

# 4. Start the server
uv run jita-mcp                              # listens on :8080
```

### Adding it to Claude Code

```bash
claude mcp add jita-mcp --transport http http://localhost:8080/mcp
```

Restart your Claude Code session and the five tools become available. After
that, just talk to Claude about EVE fits — it'll call the tools as needed.

### Adding it to Claude.ai (web)

Settings → Connectors → Add custom connector → point at your server's HTTPS URL.
Requires public HTTPS, so you'll want to deploy it (see *Deployment* below) or
use a tunnel like `ngrok`.

## Day-to-day commands

| Command | What it does |
| --- | --- |
| `uv sync` | Install / sync Python deps |
| `uv run jita-mcp` | Start the MCP server on `:8080` |
| `uv run pytest` | Run the test suite |
| `uv run ruff check` | Lint |
| `uv run python scripts/build_eve_db.py` | Rebuild `eve.db` from pyfa staticdata |

## Configuration

All via environment variables (defaults in `jita_mcp/config.py`):

| Var | Default | Purpose |
| --- | --- | --- |
| `JITA_MCP_HOST` | `0.0.0.0` | Bind address |
| `JITA_MCP_PORT` | `8080` | Bind port |
| `JITA_MCP_SDE_PATH` | `data/sde.sqlite` | Fuzzwork SDE path (optional) |

## Deployment

Build the production container with:

```bash
docker build -t jita-mcp:latest .
docker run -p 8080:8080 jita-mcp:latest
```

The Dockerfile is multi-stage and bakes everything needed (`eve.db`, the eos
source, our Python deps) into the runtime image. Approximate sizes: ~400 MB
compressed, ~2 GB on disk.

Point any HTTPS-fronted host (Fly.io, Lightsail, your own VPS) at the
container and add the URL as a custom connector in Claude.

## License

GPL-3.0-or-later. The project links pyfa's eos engine (LGPL-3.0) and ships
pyfa's bundled data; GPL-3.0 satisfies both.

## Credits

- [Pyfa](https://github.com/pyfa-org/Pyfa) — the fitting engine and the EVE
  data pipeline this server depends on
- [Fuzzwork](https://www.fuzzwork.co.uk/) — the SDE database dumps
- CCP — for keeping ESI public and free
