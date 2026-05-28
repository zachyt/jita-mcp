"""ESI price cache. Backed by SQLite; TTL configured via settings."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from jita_mcp.config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS price_cache (
    type_id    INTEGER PRIMARY KEY,
    jita_sell  REAL,
    jita_buy   REAL,
    fetched_at INTEGER NOT NULL
);
"""


class PriceCache:
    def __init__(self, path: Path, ttl_seconds: int) -> None:
        self.path = path
        self.ttl_seconds = ttl_seconds
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def get(self, type_id: int) -> dict | None:
        row = self._conn.execute(
            "SELECT jita_sell, jita_buy, fetched_at FROM price_cache WHERE type_id = ?",
            (type_id,),
        ).fetchone()
        if row is None:
            return None
        if time.time() - row["fetched_at"] > self.ttl_seconds:
            return None
        return {"jita_sell": row["jita_sell"], "jita_buy": row["jita_buy"]}

    def put(self, type_id: int, jita_sell: float | None, jita_buy: float | None) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO price_cache "
            "(type_id, jita_sell, jita_buy, fetched_at) VALUES (?, ?, ?, ?)",
            (type_id, jita_sell, jita_buy, int(time.time())),
        )
        self._conn.commit()


_cache: PriceCache | None = None


def get_price_cache() -> PriceCache:
    global _cache
    if _cache is None:
        _cache = PriceCache(settings.price_cache_path, settings.price_cache_ttl_seconds)
    return _cache
