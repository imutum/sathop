"""Worker graceful drain helpers.

The watchdog raises `SystemExit(0)` when handlers settle (or the deadline
hits); the runtime's `except* SystemExit` swallows the wrapper so `main`'s
`finally` aclose runs before the process exits."""

from __future__ import annotations

import asyncio
import signal
import time
from collections.abc import Callable, Sized

DRAIN_WATCHDOG_TIMEOUT_SEC = 60
DRAIN_POLL_INTERVAL_SEC = 1.0


def install_signal_handlers(start_drain: Callable[[str], None]) -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, start_drain, f"signal {sig.name}")
        except NotImplementedError:
            signal.signal(sig, lambda _s, _f, name=sig.name: start_drain(f"signal {name}"))


async def drain_watchdog_loop(is_draining: Callable[[], bool], active: Sized, log) -> None:
    while not is_draining():
        await asyncio.sleep(DRAIN_POLL_INTERVAL_SEC)
    deadline = time.monotonic() + DRAIN_WATCHDOG_TIMEOUT_SEC
    log.info("drain watchdog armed; %d handler(s) in flight", len(active))
    while time.monotonic() < deadline:
        if not active:
            log.info("drain complete — all handlers finished")
            raise SystemExit(0)
        await asyncio.sleep(DRAIN_POLL_INTERVAL_SEC)
    log.warning(
        "drain timeout (%ds) reached with %d handler(s) still in flight — forcing exit; lease sweeper will reclaim",
        DRAIN_WATCHDOG_TIMEOUT_SEC,
        len(active),
    )
    raise SystemExit(0)
