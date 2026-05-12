"""Crash-resilient periodic loop helper."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable


async def run_periodic(
    body: Callable[[], Awaitable[None]],
    *,
    interval: float,
    log: logging.Logger,
    name: str,
    initial_delay: float = 0.0,
    disabled_when_non_positive: bool = False,
) -> None:
    if disabled_when_non_positive and interval <= 0:
        log.info("%s loop disabled (interval=%s)", name, interval)
        return
    if initial_delay > 0:
        await asyncio.sleep(initial_delay)
    while True:
        try:
            await body()
        except Exception as e:
            log.warning("%s failed: %s", name, e)
        await asyncio.sleep(interval)
