"""Concurrency and expiry contracts for cached dashboard reads."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from sathop.orchestrator import read_cache
from sathop.orchestrator.read_cache import AsyncTTLCache


@pytest.fixture
def clock(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(read_cache, "monotonic", lambda: now[0])
    return now


@pytest.mark.parametrize("value", [None, False, 0, [], {}, b""])
async def test_falsy_values_are_cached_without_starting_another_load(value):
    cache = AsyncTTLCache(ttl_seconds=5)
    load = AsyncMock(return_value=value)
    assert await cache.get(load) is value
    assert await cache.get(load) is value
    load.assert_awaited_once()


async def test_ttl_starts_after_loading_finishes_and_expires_at_boundary(clock):
    cache = AsyncTTLCache[str](ttl_seconds=5)

    async def slow_load():
        clock[0] += 20
        return "first"

    assert await cache.get(slow_load) == "first"
    reload = AsyncMock(return_value="second")
    clock[0] += 4.9
    assert await cache.get(reload) == "first"
    reload.assert_not_awaited()
    clock[0] = 125
    assert await cache.get(reload) == "second"
    reload.assert_awaited_once()


async def test_concurrent_requests_share_one_load():
    cache = AsyncTTLCache[object](ttl_seconds=5)
    entered, release = asyncio.Event(), asyncio.Event()
    value = object()

    async def load():
        entered.set()
        await release.wait()
        return value

    loader = AsyncMock(side_effect=load)
    tasks = [asyncio.create_task(cache.get(loader)) for _ in range(20)]
    await entered.wait()
    release.set()
    results = await asyncio.gather(*tasks)
    assert all(result is value for result in results)
    loader.assert_awaited_once()


@pytest.mark.parametrize("ttl", [0, -1])
async def test_disabled_cache_loads_each_time(ttl):
    cache = AsyncTTLCache[int](ttl_seconds=ttl)
    load = AsyncMock(side_effect=range(4))
    assert await asyncio.gather(*(cache.get(load) for _ in range(4))) == list(range(4))
    assert load.await_count == 4


async def test_failed_refresh_propagates_and_next_request_can_retry(clock):
    cache = AsyncTTLCache[str](ttl_seconds=5)
    load = AsyncMock(side_effect=["first", RuntimeError("database unavailable"), "recovered"])
    assert await cache.get(load) == "first"
    clock[0] += 5
    with pytest.raises(RuntimeError, match="database unavailable"):
        await cache.get(load)
    assert await cache.get(load) == "recovered"
    assert load.await_count == 3


async def test_cancelled_loader_releases_lock_for_waiting_request():
    cache = AsyncTTLCache[str](ttl_seconds=5)
    entered = asyncio.Event()

    async def blocked_load():
        entered.set()
        await asyncio.Event().wait()
        return "unreachable"

    loading = asyncio.create_task(cache.get(blocked_load))
    await entered.wait()
    following = asyncio.create_task(cache.get(AsyncMock(return_value="recovered")))
    await asyncio.sleep(0)  # Let the following request wait on the lock.
    loading.cancel()
    with pytest.raises(asyncio.CancelledError):
        await loading
    assert await asyncio.wait_for(following, timeout=1) == "recovered"


async def test_cancelled_waiter_does_not_cancel_shared_load():
    cache = AsyncTTLCache[str](ttl_seconds=5)
    entered, release = asyncio.Event(), asyncio.Event()

    async def blocked_load():
        entered.set()
        await release.wait()
        return "loaded"

    loading = asyncio.create_task(cache.get(blocked_load))
    await entered.wait()
    unused = AsyncMock()
    waiting = asyncio.create_task(cache.get(unused))
    await asyncio.sleep(0)
    waiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiting
    release.set()
    assert await loading == "loaded"
    assert await cache.get(unused) == "loaded"
    unused.assert_not_awaited()


async def test_clear_during_load_prevents_old_result_from_refilling_cache():
    cache = AsyncTTLCache[str](ttl_seconds=5)
    entered, release = asyncio.Event(), asyncio.Event()

    async def blocked_load():
        entered.set()
        await release.wait()
        return "old"

    loading = asyncio.create_task(cache.get(blocked_load))
    await entered.wait()
    cache.clear()
    release.set()
    assert await loading == "old"  # The original caller can still finish.
    reload = AsyncMock(return_value="new")
    assert await cache.get(reload) == "new"
    assert await cache.get(reload) == "new"
    reload.assert_awaited_once()


async def test_clear_drops_a_completed_value():
    cache = AsyncTTLCache[str](ttl_seconds=5)
    load = AsyncMock(side_effect=["old", "new"])
    assert await cache.get(load) == "old"
    cache.clear()
    assert await cache.get(load) == "new"
