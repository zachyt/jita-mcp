"""SDE: read-only access to the Fuzzwork static data export.

Reserved for *non-ship* lookups — regions, solar systems, stations, market
groups, etc. — that pyfa's eve.db doesn't carry. Ship / module / dogma
queries go through db/eve.py (pyfa's eos).

If no such tools exist yet, this module is just the connection wrapper.
Add typed lookup methods here as they're needed.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from jita_mcp.config import settings


class SDE:
    def __init__(self, path: Path) -> None:
        self.path = path
        uri = f"file:{path}?mode=ro"
        self._conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row

    def close(self) -> None:
        self._conn.close()


_sde: SDE | None = None


def get_sde() -> SDE:
    global _sde
    if _sde is None:
        _sde = SDE(settings.sde_path)
    return _sde
