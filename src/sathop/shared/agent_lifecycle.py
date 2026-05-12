"""Graceful-drain skeleton shared by worker and receiver agents."""

from __future__ import annotations

import asyncio
import logging
import signal
import time
from collections.abc import Callable, Coroutine, Sized
from typing import Any, TypeVar

from sathop.shared.orch_client import AuthTokenInvalid

DEFAULT_TIMEOUT_SEC = 60
DRAIN_POLL_INTERVAL_SEC = 1.0

T = TypeVar("T")


class GracefulAgentExit(Exception):
    pass


class AgentTaskGroup:
    def __init__(self, tg: asyncio.TaskGroup) -> None:
        self._tg = tg

    def create_task(self, coro: Coroutine[Any, Any, T]) -> asyncio.Task[T]:
        return self._tg.create_task(_run_agent_task(coro))


async def _run_agent_task(coro: Coroutine[Any, Any, T]) -> T:
    try:
        return await coro
    except SystemExit as e:
        if e.code in (0, None):
            raise GracefulAgentExit from None
        raise


async def run_agent(create_tasks: Callable[[AgentTaskGroup], None], *, log: logging.Logger) -> None:
    try:
        async with asyncio.TaskGroup() as tg:
            create_tasks(AgentTaskGroup(tg))
    except* AuthTokenInvalid:
        log.error("orchestrator rejected token (401) — exiting for container restart")
        raise SystemExit(1) from None
    except* GracefulAgentExit:
        pass


def install_signal_handlers(start_drain: Callable[[str], None]) -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, start_drain, f"signal {sig.name}")
        except NotImplementedError:
            signal.signal(sig, lambda _s, _f, name=sig.name: start_drain(f"signal {name}"))


async def drain_watchdog_loop(
    is_draining: Callable[[], bool],
    active: Sized,
    log: logging.Logger,
    *,
    timeout_sec: int = DEFAULT_TIMEOUT_SEC,
    active_noun: str = "handler",
    reclaim_message: str = "lease sweeper will reclaim",
) -> None:
    while not is_draining():
        await asyncio.sleep(DRAIN_POLL_INTERVAL_SEC)
    deadline = time.monotonic() + timeout_sec
    log.info("drain watchdog armed; %d %s(s) in flight", len(active), active_noun)
    while time.monotonic() < deadline:
        if not active:
            log.info("drain complete — all %ss finished", active_noun)
            raise SystemExit(0)
        await asyncio.sleep(DRAIN_POLL_INTERVAL_SEC)
    log.warning(
        "drain timeout (%ds) reached with %d %s(s) still in flight — forcing exit; %s",
        timeout_sec,
        len(active),
        active_noun,
        reclaim_message,
    )
    raise SystemExit(0)
