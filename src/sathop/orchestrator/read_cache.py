"""Short-lived, per-process caches for expensive dashboard reads."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from time import monotonic
from typing import Generic, TypeVar

T = TypeVar("T")


class AsyncTTLCache(Generic[T]):
    """Share one successful load across concurrent requests on the same event loop.

    The TTL starts when loading finishes. A non-positive TTL disables reuse;
    failures and cancellations propagate without caching a result. Callers must
    treat returned values as read-only and supply a factory, not a coroutine,
    so cache hits don't start work or hold request resources.
    """

    def __init__(self, ttl_seconds: float) -> None:
        self.ttl_seconds = ttl_seconds
        self._entry: tuple[float, T] | None = None
        self._lock = asyncio.Lock()
        self._generation = 0

    def clear(self) -> None:
        """Drop the value and prevent an in-flight load from repopulating it."""
        self._entry = None
        self._generation += 1

    def _fresh_entry(self) -> tuple[float, T] | None:
        entry = self._entry
        if entry is not None and self.ttl_seconds > 0 and monotonic() - entry[0] < self.ttl_seconds:
            return entry
        return None

    async def get(self, load: Callable[[], Awaitable[T]]) -> T:
        entry = self._fresh_entry()
        if entry is not None:
            return entry[1]
        async with self._lock:
            # A preceding request may have populated the cache while we waited.
            entry = self._fresh_entry()
            if entry is not None:
                return entry[1]
            generation = self._generation
            value = await load()
            if generation == self._generation:
                self._entry = (monotonic(), value)
            return value
