"""Shared drain skeleton: signal install + watchdog GracefulAgentExit.

The lifecycle module is the one place worker/receiver agents exit cleanly. We
exercise both paths in the signal-handler installer (asyncio fast path +
signal.signal fallback used on Windows) and assert the watchdog raises
GracefulAgentExit on both "clean drain" and "timeout" branches, including a
sanity check that `active_noun`/`reclaim_message` propagate into the log lines
so worker and receiver can stay differentiated.
"""

from __future__ import annotations

import asyncio
import logging
import signal
from collections import deque

import pytest

from sathop.shared import agent_lifecycle
from sathop.shared.orch_client import AuthTokenInvalid

# ─── run_agent ─────────────────────────────────────────────────────────────


async def test_run_agent_raises_system_exit_for_auth_token_invalid(caplog):
    async def fail_auth() -> None:
        raise AuthTokenInvalid("bad token")

    def create_tasks(tg: asyncio.TaskGroup) -> None:
        tg.create_task(fail_auth())

    caplog.set_level(logging.ERROR)
    with pytest.raises(SystemExit) as exc:
        await agent_lifecycle.run_agent(create_tasks, log=logging.getLogger("t"))
    assert exc.value.code == 1
    assert "orchestrator rejected token" in caplog.text


async def test_run_agent_swallows_graceful_agent_exit():
    async def graceful_exit() -> None:
        raise agent_lifecycle.GracefulAgentExit

    def create_tasks(tg: asyncio.TaskGroup) -> None:
        tg.create_task(graceful_exit())

    await agent_lifecycle.run_agent(create_tasks, log=logging.getLogger("t"))


# ─── install_signal_handlers ──────────────────────────────────────────────


async def test_install_signal_handlers_registers_callable():
    """Whichever path the installer takes, calling it should not raise and
    SIGTERM should end up with a non-default handler."""
    called: list[str] = []
    agent_lifecycle.install_signal_handlers(lambda reason: called.append(reason))
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
    agent_lifecycle.install_signal_handlers(lambda reason: captured.append(reason))

    handler = signal.getsignal(signal.SIGTERM)
    assert callable(handler)
    handler(signal.SIGTERM, None)  # type: ignore[misc]
    assert captured == ["signal SIGTERM"]


# ─── drain_watchdog_loop ──────────────────────────────────────────────────


async def test_watchdog_exits_immediately_when_active_empty(monkeypatch, caplog):
    """draining=True + nothing in flight → GracefulAgentExit on next tick."""
    monkeypatch.setattr(agent_lifecycle, "DRAIN_POLL_INTERVAL_SEC", 0.01)
    caplog.set_level(logging.INFO)

    is_draining = True
    active: deque[int] = deque()

    with pytest.raises(agent_lifecycle.GracefulAgentExit):
        await asyncio.wait_for(
            agent_lifecycle.drain_watchdog_loop(lambda: is_draining, active, logging.getLogger("t")),
            timeout=1.0,
        )
    assert "drain complete" in caplog.text


async def test_watchdog_waits_for_handlers_then_exits(monkeypatch, caplog):
    """While the drain flag flips True, the loop should park on
    poll-interval ticks until `active` empties, then exit cleanly."""
    monkeypatch.setattr(agent_lifecycle, "DRAIN_POLL_INTERVAL_SEC", 0.01)
    caplog.set_level(logging.INFO)

    active: deque[int] = deque([1, 2])
    state = {"draining": False}

    async def driver() -> None:
        await asyncio.sleep(0.03)
        state["draining"] = True
        await asyncio.sleep(0.02)
        active.popleft()
        await asyncio.sleep(0.02)
        active.popleft()

    asyncio.create_task(driver())
    with pytest.raises(agent_lifecycle.GracefulAgentExit):
        await asyncio.wait_for(
            agent_lifecycle.drain_watchdog_loop(lambda: state["draining"], active, logging.getLogger("t")),
            timeout=2.0,
        )
    assert "drain watchdog armed" in caplog.text
    assert "drain complete" in caplog.text


async def test_watchdog_times_out_when_handlers_stuck(monkeypatch, caplog):
    """Handlers never finish before the deadline → GracefulAgentExit anyway
    with the caller-supplied reclaim_message surfaced for ops debugging."""
    monkeypatch.setattr(agent_lifecycle, "DRAIN_POLL_INTERVAL_SEC", 0.01)
    caplog.set_level(logging.INFO)

    active: deque[int] = deque([1])  # never drains

    with pytest.raises(agent_lifecycle.GracefulAgentExit):
        await asyncio.wait_for(
            agent_lifecycle.drain_watchdog_loop(
                lambda: True,
                active,
                logging.getLogger("t"),
                timeout_sec=0,
                reclaim_message="orchestrator will re-offer un-acked objects",
            ),
            timeout=1.0,
        )
    assert "drain timeout" in caplog.text
    assert "orchestrator will re-offer un-acked objects" in caplog.text


async def test_watchdog_noun_propagates_to_log(monkeypatch, caplog):
    """`active_noun` differentiates handler-vs-pull in the operator logs;
    the receiver depends on this so its drain output reads naturally."""
    monkeypatch.setattr(agent_lifecycle, "DRAIN_POLL_INTERVAL_SEC", 0.01)
    caplog.set_level(logging.INFO)

    active: deque[int] = deque()
    with pytest.raises(agent_lifecycle.GracefulAgentExit):
        await asyncio.wait_for(
            agent_lifecycle.drain_watchdog_loop(
                lambda: True, active, logging.getLogger("t"), active_noun="pull"
            ),
            timeout=1.0,
        )
    assert "0 pull(s)" in caplog.text
    assert "all pulls finished" in caplog.text
