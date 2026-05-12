"""Generic periodic-loop helper — body invocation, error swallow, kill switch."""

from __future__ import annotations

import asyncio
import logging

import pytest

from sathop.shared.periodic import run_periodic


async def test_body_runs_repeatedly_until_cancelled():
    """Body is called on every tick; loop continues until the task is cancelled."""
    hits = 0

    async def body() -> None:
        nonlocal hits
        hits += 1

    task = asyncio.create_task(run_periodic(body, interval=0.01, log=logging.getLogger("t"), name="tick"))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert hits >= 2


async def test_body_exceptions_are_logged_and_swallowed(caplog):
    """A body that raises does not break the loop — the helper logs and continues."""
    caplog.set_level(logging.WARNING)
    hits = 0

    async def body() -> None:
        nonlocal hits
        hits += 1
        if hits == 1:
            raise RuntimeError("boom")

    task = asyncio.create_task(run_periodic(body, interval=0.01, log=logging.getLogger("t"), name="tick"))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert hits >= 2
    assert "tick failed: boom" in caplog.text


async def test_disabled_when_non_positive_returns_without_running(caplog):
    """interval ≤ 0 + disabled_when_non_positive=True → log once, never call body."""
    caplog.set_level(logging.INFO)
    called = False

    async def body() -> None:
        nonlocal called
        called = True

    await run_periodic(
        body,
        interval=0,
        log=logging.getLogger("t"),
        name="tick",
        disabled_when_non_positive=True,
    )
    assert called is False
    assert "tick loop disabled" in caplog.text


async def test_initial_delay_holds_off_first_body_call():
    """First body invocation is deferred by initial_delay."""
    first_at: list[float] = []
    started = asyncio.get_event_loop().time()

    async def body() -> None:
        if not first_at:
            first_at.append(asyncio.get_event_loop().time())

    task = asyncio.create_task(
        run_periodic(
            body,
            interval=0.05,
            log=logging.getLogger("t"),
            name="tick",
            initial_delay=0.05,
        )
    )
    await asyncio.sleep(0.1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert first_at, "body never ran"
    assert first_at[0] - started >= 0.04  # ~initial_delay, slop for scheduler
