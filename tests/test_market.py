"""Tests for the ESI market client + price cache.

HTTP responses are mocked via pytest-httpx so these don't actually hit ESI.
The cache is module-scoped, so we clear it between tests.
"""

from __future__ import annotations

import time

import pytest
from jita_mcp.market import esi
from jita_mcp.market.cache import PriceCache
from pytest_httpx import HTTPXMock


@pytest.fixture(autouse=True)
def _reset_cache() -> None:
    esi._cache.clear()


def _ok_response(price: float, etag: str = "abc", ttl_seconds: int = 300) -> dict:
    return {
        "status_code": 200,
        "json": [
            {"location_id": esi.STATION_JITA_4_4, "price": price, "is_buy_order": False},
            # An order at a different station should be ignored.
            {"location_id": 60000001, "price": 1.0, "is_buy_order": False},
        ],
        "headers": {
            "ETag": etag,
            "Expires": _http_date(time.time() + ttl_seconds),
            "X-ESI-Error-Limit-Remain": "95",
            "X-ESI-Error-Limit-Reset": "60",
        },
    }


def _http_date(epoch: float) -> str:
    from email.utils import formatdate

    return formatdate(epoch, usegmt=True)


@pytest.mark.asyncio
async def test_fetches_and_returns_min_jita_price(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(**_ok_response(price=12345.67))
    prices = await esi.get_jita_sell_min([10631])
    assert prices == {10631: 12345.67}


@pytest.mark.asyncio
async def test_cache_hit_skips_http(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(**_ok_response(price=100.0))
    await esi.get_jita_sell_min([10631])
    # Second call — no new mock registered, so any HTTP would error.
    prices = await esi.get_jita_sell_min([10631])
    assert prices == {10631: 100.0}


@pytest.mark.asyncio
async def test_304_extends_ttl_without_changing_price(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(**_ok_response(price=100.0, etag='"v1"', ttl_seconds=1))
    await esi.get_jita_sell_min([10631])
    # Force the cache entry stale.
    esi._cache.get(10631).expires_at = time.time() - 1  # type: ignore[union-attr]

    # ESI returns 304; price stays 100.
    httpx_mock.add_response(
        status_code=304,
        headers={"Expires": _http_date(time.time() + 300)},
    )
    prices = await esi.get_jita_sell_min([10631])
    assert prices == {10631: 100.0}
    # And the new expiry is honoured.
    entry = esi._cache.get(10631)
    assert entry is not None
    assert entry.expires_at > time.time() + 200


@pytest.mark.asyncio
async def test_no_orders_returns_none(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        status_code=200,
        json=[],  # no orders at all
        headers={
            "ETag": "x",
            "Expires": _http_date(time.time() + 300),
        },
    )
    prices = await esi.get_jita_sell_min([10631])
    assert prices == {10631: None}


@pytest.mark.asyncio
async def test_5xx_leaves_cache_untouched(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(**_ok_response(price=50.0))
    await esi.get_jita_sell_min([10631])
    # Force stale.
    esi._cache.get(10631).expires_at = time.time() - 1  # type: ignore[union-attr]
    httpx_mock.add_response(status_code=503)
    prices = await esi.get_jita_sell_min([10631])
    # Stale price is still surfaced (better than None on transient ESI outage).
    assert prices == {10631: 50.0}


@pytest.mark.asyncio
async def test_filters_orders_at_other_stations(httpx_mock: HTTPXMock) -> None:
    """An order at a Forge station that ISN'T Jita 4-4 must not count."""
    httpx_mock.add_response(
        status_code=200,
        json=[
            {"location_id": 60000001, "price": 1.0, "is_buy_order": False},
            {"location_id": esi.STATION_JITA_4_4, "price": 999.0, "is_buy_order": False},
        ],
        headers={
            "ETag": "x",
            "Expires": _http_date(time.time() + 300),
        },
    )
    prices = await esi.get_jita_sell_min([10631])
    assert prices == {10631: 999.0}


def test_cache_basics() -> None:
    """The PriceCache itself, no HTTP."""
    cache = PriceCache()
    assert cache.get(1) is None
    assert not cache.is_fresh(1)
    cache.put(1, price=10.0, etag="x", expires_at=time.time() + 60)
    assert cache.is_fresh(1)
    assert cache.get(1).price == 10.0  # type: ignore[union-attr]
    cache.put(1, price=10.0, etag="x", expires_at=time.time() - 1)
    assert not cache.is_fresh(1)
    cache.touch_expiry(1, time.time() + 60)
    assert cache.is_fresh(1)
