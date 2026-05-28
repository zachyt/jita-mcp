"""ESI market client: get current Jita 4-4 sell-min prices in bulk.

ESI rules baked into the client:
  - Identifying User-Agent (required; CCP bans unidentifiable agents)
  - Respect Cache-Control / Expires (required; ban-worthy to circumvent)
  - Use ETag / If-None-Match for cheap revalidation (304 doesn't burn budget)
  - Back off if our error budget gets low (X-ESI-Error-Limit-Remain < 20)
  - Bounded concurrency via asyncio.Semaphore
"""

from __future__ import annotations

import asyncio
import time
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from jita_mcp.market.cache import PriceCache

USER_AGENT = "jita-mcp/0.1 (+https://github.com/zachyt/jita-mcp)"
ESI_BASE = "https://esi.evetech.net/latest"
REGION_THE_FORGE = 10000002
STATION_JITA_4_4 = 60003760

# Bounds for politeness, not enforced by ESI directly.
_MAX_CONCURRENT_REQUESTS = 20
_ERROR_BUDGET_FLOOR = 20  # if X-ESI-Error-Limit-Remain drops below this, back off
_DEFAULT_TTL_SECONDS = 300  # fallback if no Expires header

# Module-level price cache survives across calls (in-memory dict — fine).
# httpx.AsyncClient and asyncio.Semaphore are NOT cached because they're tied
# to the event loop that created them; reusing across loops (e.g. pytest-
# asyncio's per-test loops) raises "Event loop is closed". We create both
# fresh inside get_jita_sell_min — the overhead is one TCP handshake per
# batch, negligible against ESI's 5-min cache.
_cache = PriceCache()


def _new_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        timeout=httpx.Timeout(15.0, connect=5.0),
    )


def _parse_expires(header: str | None) -> float:
    """Parse an HTTP-date Expires header to unix epoch seconds."""
    if not header:
        return time.time() + _DEFAULT_TTL_SECONDS
    try:
        return parsedate_to_datetime(header).timestamp()
    except (TypeError, ValueError):
        return time.time() + _DEFAULT_TTL_SECONDS


async def _backoff_if_budget_low(resp: httpx.Response) -> None:
    """If we're running out of error budget, sleep until the window resets."""
    try:
        remain = int(resp.headers.get("X-ESI-Error-Limit-Remain", "100"))
        reset = int(resp.headers.get("X-ESI-Error-Limit-Reset", "60"))
    except (TypeError, ValueError):
        return
    if remain < _ERROR_BUDGET_FLOOR:
        await asyncio.sleep(reset)


async def _fetch_one(
    type_id: int,
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
) -> None:
    """Fetch one typeID and update the cache.

    Sends If-None-Match if we have an ETag; handles 304 (extend TTL),
    200 (replace), and gracefully tolerates network/5xx errors (leaves
    stale cache in place so callers fall back to last-known price).
    """
    cached = _cache.get(type_id)
    headers: dict[str, str] = {}
    if cached and cached.etag:
        headers["If-None-Match"] = cached.etag

    url = f"{ESI_BASE}/markets/{REGION_THE_FORGE}/orders/"
    params: dict[str, str | int] = {
        "datasource": "tranquility",
        "order_type": "sell",
        "type_id": type_id,
    }

    async with semaphore:
        try:
            resp = await client.get(url, params=params, headers=headers)
        except httpx.HTTPError:
            return  # leave cache as-is; caller handles missing price gracefully

    await _backoff_if_budget_low(resp)

    if resp.status_code == 304 and cached is not None:
        _cache.touch_expiry(type_id, _parse_expires(resp.headers.get("Expires")))
        return

    if resp.status_code != 200:
        return  # 5xx / 4xx — leave cache untouched

    orders: list[dict[str, Any]] = resp.json()
    jita_prices = [
        float(o["price"]) for o in orders if int(o.get("location_id", 0)) == STATION_JITA_4_4
    ]
    price: float | None = min(jita_prices) if jita_prices else None

    _cache.put(
        type_id,
        price=price,
        etag=resp.headers.get("ETag"),
        expires_at=_parse_expires(resp.headers.get("Expires")),
    )


async def get_jita_sell_min(type_ids: list[int]) -> dict[int, float | None]:
    """Batch lookup: returns {typeID: price_at_Jita_4_4 or None}.

    None means either (a) we couldn't reach ESI and have no cached value, or
    (b) ESI returned no sell orders for that type. Cached fresh entries are
    returned without an HTTP call.
    """
    if not type_ids:
        return {}

    unique_ids = list(set(type_ids))
    need_fetch = [tid for tid in unique_ids if not _cache.is_fresh(tid)]
    if need_fetch:
        semaphore = asyncio.Semaphore(_MAX_CONCURRENT_REQUESTS)
        async with _new_client() as client:
            await asyncio.gather(*(_fetch_one(tid, client, semaphore) for tid in need_fetch))

    out: dict[int, float | None] = {}
    for tid in type_ids:
        entry = _cache.get(tid)
        out[tid] = entry.price if entry is not None else None
    return out
