"""In-memory ESI price cache.

Per-typeID entry stores (price, etag, expires_at). The cache survives within
one server process — restarting `jita-mcp` clears it. SQLite-backed
persistence is intentionally not implemented for v1; ESI's 5-min TTL means
a fresh cache repopulates fast.
"""

from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class CacheEntry:
    """A cached ESI price plus the metadata we need to refresh it cheaply.

    `price is None` means we asked ESI and there were no sell orders at
    Jita 4-4 for this type. We cache the absence too so we don't re-poll for
    items that genuinely have no market.
    """

    price: float | None
    etag: str | None
    expires_at: float  # unix epoch seconds


class PriceCache:
    """Process-local TTL+ETag cache."""

    def __init__(self) -> None:
        self._store: dict[int, CacheEntry] = {}

    def get(self, type_id: int) -> CacheEntry | None:
        return self._store.get(type_id)

    def is_fresh(self, type_id: int, now: float | None = None) -> bool:
        entry = self._store.get(type_id)
        if entry is None:
            return False
        return (now if now is not None else time.time()) < entry.expires_at

    def put(
        self,
        type_id: int,
        price: float | None,
        etag: str | None,
        expires_at: float,
    ) -> None:
        self._store[type_id] = CacheEntry(price=price, etag=etag, expires_at=expires_at)

    def touch_expiry(self, type_id: int, expires_at: float) -> None:
        """For 304 Not Modified responses — extend TTL without changing price."""
        entry = self._store.get(type_id)
        if entry is not None:
            entry.expires_at = expires_at

    def clear(self) -> None:
        self._store.clear()

    def __len__(self) -> int:
        return len(self._store)
