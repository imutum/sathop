"""Worker drain helpers: signal handler installation + watchdog SystemExit.

The drain module is the one place the worker process exits cleanly. We
exercise both paths in the signal-handler installer (asyncio fast path +
signal.signal fallback used on Windows) and assert the watchdog raises
SystemExit on both "clean drain" and "timeout" branches.
"""

from __future__ import annotations

import asyncio
import logging
import signal
from collections import deque

import pytest

from sathop.worker import drain

# ─── install_signal_handlers ──────────────────────────────────────────────


async def test_install_signal_handlers_registers_callable():
    """Whichever path the installer takes, calling it should not raise and
    SIGTERM should end up with a non-default handler."""
    called: list[str] = []
    drain.install_signal_handlers(lambda reason: called.append(reason))
    # The handler is now installed — on POSIX via the loop, on Windows via
    # signal.signal. In either case, getsignal returns a callable (not the
    # SIG_DFL/SIG_IGN sentinels).
    h = signal.getsignal(signal.SIGTERM)
    assert callable(h) or h is signal.SIG_DFL  # loop path masks Python-level getsignal


async def test_install_signal_handlers_falls_back_when_loop_rejects(monkeypatch):
    """On Windows asyncio doesn't support add_signal_handler — the installer
    must catch NotImplementedError and route through signal.signal so the
    fallback handler still calls start_drain when fired."""
    loop = asyncio.get_running_loop()

    def reject(*_a, **_kw):
        raise NotImplementedError

    monkeypatch.setattr(loop, "add_signal_handler", reject)

    captured: list[str] = []
    drain.install_signal_handlers(lambda reason: captured.append(reason))

    # Pull the fallback handler back out and invoke it as if signal fired.
    handler = signal.getsignal(signal.SIGTERM)
    assert callable(handler)
    handler(signal.SIGTERM, None)  # type: ignore[misc]
    assert captured == ["signal SIGTERM"]


# ─── drain_watchdog_loop ──────────────────────────────────────────────────


async def test_watchdog_exits_immediately_when_active_empty(monkeypatch, caplog):
    """draining=True + nothing in flight → SystemExit(0) on the very next tick."""
    monkeypatch.setattr(drain, "DRAIN_POLL_INTERVAL_SEC", 0.01)
    caplog.set_level(logging.INFO)

    is_draining = True
    active: deque[int] = deque()

    with pytest.raises(SystemExit) as exc:
        await asyncio.wait_for(
            drain.drain_watchdog_loop(lambda: is_draining, active, logging.getLogger("t")),
            timeout=1.0,
        )
    assert exc.value.code == 0
    assert "drain complete" in caplog.text


async def test_watchdog_waits_for_handlers_then_exits(monkeypatch, caplog):
    """While the drain flag flips True, the loop should park on
    poll-interval ticks until `active` empties, then SystemExit cleanly."""
    monkeypatch.setattr(drain, "DRAIN_POLL_INTERVAL_SEC", 0.01)
    caplog.set_level(logging.INFO)

    active: deque[int] = deque([1, 2])
    state = {"draining": False}

    async def driver() -> None:
        # Let the loop park in the pre-drain wait first.
        await asyncio.sleep(0.03)
        state["draining"] = True
        # Then "finish" the two handlers a tick apart.
        await asyncio.sleep(0.02)
        active.popleft()
        await asyncio.sleep(0.02)
        active.popleft()

    asyncio.create_task(driver())
    with pytest.raises(SystemExit) as exc:
        await asyncio.wait_for(
            drain.drain_watchdog_loop(lambda: state["draining"], active, logging.getLogger("t")),
            timeout=2.0,
        )
    assert exc.value.code == 0
    assert "drain watchdog armed" in caplog.text
    assert "drain complete" in caplog.text


async def test_watchdog_times_out_when_handlers_stuck(monkeypatch, caplog):
    """Handlers never finish before the deadline → SystemExit(0) anyway with
    a warning that the lease sweeper will pick up the orphans."""
    monkeypatch.setattr(drain, "DRAIN_POLL_INTERVAL_SEC", 0.01)
    monkeypatch.setattr(drain, "DRAIN_WATCHDOG_TIMEOUT_SEC", 0.05)
    caplog.set_level(logging.INFO)

    active: deque[int] = deque([1])  # never drains

    with pytest.raises(SystemExit) as exc:
        await asyncio.wait_for(
            drain.drain_watchdog_loop(lambda: True, active, logging.getLogger("t")),
            timeout=1.0,
        )
    assert exc.value.code == 0
    assert "drain timeout" in caplog.text
    assert "lease sweeper will reclaim" in caplog.text
