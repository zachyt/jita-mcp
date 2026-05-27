"""SDE: read-only access to the static data export SQLite database.

Opens the SDE once in read-only mode at startup. All higher-level lookups in this
project go through this module so SQL stays in one place and the schema can be
swapped (Fuzzwork vs. Pyfa-derived vs. self-built) without touching tools.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from eve_mcp.config import settings


class SDE:
    def __init__(self, path: Path) -> None:
        self.path = path
        uri = f"file:{path}?mode=ro"
        self._conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row

    def close(self) -> None:
        self._conn.close()

    def execute(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        return self._conn.execute(sql, params).fetchall()

    def type_by_name(self, name: str) -> dict[str, Any] | None:
        raise NotImplementedError

    def type_by_id(self, type_id: int) -> dict[str, Any] | None:
        raise NotImplementedError

    def search_types(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        raise NotImplementedError


_sde: SDE | None = None


def get_sde() -> SDE:
    global _sde
    if _sde is None:
        _sde = SDE(settings.sde_path)
    return _sde
