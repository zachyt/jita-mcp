"""Replacement for pyfa's root config.py.

The real one (vendor/pyfa/config.py) imports wx for path discovery. eos only
touches two attributes — `savePath` and `saveDB` — both used by db.migration
for backup-on-migrate. We never migrate at runtime, but the imports run, so
these must exist.
"""

from pathlib import Path

savePath: Path = Path.home() / ".jita-mcp"
saveDB: str | None = None
