"""Thin ESI HTTP client for market price lookups."""

from __future__ import annotations

import aiohttp

from eve_mcp.config import settings


async def fetch_min_sell_price(type_id: int) -> float | None:
    """Fetch the minimum sell-order price for type_id in the configured region.

    Returns None if there are no sell orders. Raises on network/HTTP errors so callers
    can decide whether to fall back to a stale cached value.
    """
    url = f"{settings.esi_base_url}/markets/{settings.esi_market_region_id}/orders/"
    params = {"order_type": "sell", "type_id": type_id}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as r:
            r.raise_for_status()
            orders = await r.json()
    sell_prices = [o["price"] for o in orders if o.get("is_buy_order") is False]
    return min(sell_prices) if sell_prices else None
