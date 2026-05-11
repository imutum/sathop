"""worker.main + receiver.main entry points: thin asyncio.run wrappers.

Both look like:
    config = load()
    r = Component(config)
    try: await r.run()
    finally: await r.client.aclose()  # receiver also: await r.aclose()

Tests substitute fakes for the Component class so we never hit the
network or spin a runtime; the assertions are about exit-path ordering
(aclose must run even when run() raises) and the receiver's extra aclose().
"""

from __future__ import annotations

import pytest

from sathop.receiver import main as receiver_main
from sathop.worker import main as worker_main


class _FakeClient:
    def __init__(self) -> None:
        self.aclose_called = False

    async def aclose(self) -> None:
        self.aclose_called = True


class _FakeWorker:
    instances: list[_FakeWorker] = []

    def __init__(self, _cfg: object) -> None:
        self.client = _FakeClient()
        self.run_called = False
        self.raise_in_run: BaseException | None = None
        _FakeWorker.instances.append(self)

    async def run(self) -> None:
        self.run_called = True
        if self.raise_in_run is not None:
            raise self.raise_in_run


class _FakeReceiver(_FakeWorker):
    """Receiver entry awaits both r.client.aclose() and r.aclose()."""

    def __init__(self, _cfg: object) -> None:
        super().__init__(_cfg)
        self.self_aclose_called = False

    async def aclose(self) -> None:
        self.self_aclose_called = True


# ─── worker/main.py ─────────────────────────────────────────────────────


async def test_worker_main_runs_then_aclose(monkeypatch):
    _FakeWorker.instances.clear()
    monkeypatch.setattr(worker_main, "load", lambda: object())
    monkeypatch.setattr(worker_main, "Worker", _FakeWorker)
    await worker_main.main()
    [w] = _FakeWorker.instances
    assert w.run_called
    assert w.client.aclose_called


async def test_worker_main_aclose_runs_even_when_run_raises(monkeypatch):
    _FakeWorker.instances.clear()
    monkeypatch.setattr(worker_main, "load", lambda: object())
    monkeypatch.setattr(worker_main, "Worker", _FakeWorker)

    sentinel = RuntimeError("boom")

    class _Boom(_FakeWorker):
        def __init__(self, cfg):  # noqa: D401
            super().__init__(cfg)
            self.raise_in_run = sentinel

    monkeypatch.setattr(worker_main, "Worker", _Boom)
    with pytest.raises(RuntimeError, match="boom"):
        await worker_main.main()
    [w] = _FakeWorker.instances
    assert w.run_called
    assert w.client.aclose_called  # finally branch still ran


# ─── receiver/main.py ────────────────────────────────────────────────────


async def test_receiver_main_runs_and_closes_both_resources(monkeypatch):
    _FakeWorker.instances.clear()
    monkeypatch.setattr(receiver_main, "load", lambda: object())
    monkeypatch.setattr(receiver_main, "Receiver", _FakeReceiver)
    await receiver_main.main()
    [r] = _FakeWorker.instances
    assert r.run_called
    assert r.client.aclose_called
    assert r.self_aclose_called  # type: ignore[attr-defined]


async def test_receiver_main_closes_both_on_exception(monkeypatch):
    """If r.run() raises, both r.client.aclose() AND r.aclose() must still
    fire — the receiver holds a httpx client pool and an internal puller
    that need symmetric cleanup."""
    _FakeWorker.instances.clear()
    monkeypatch.setattr(receiver_main, "load", lambda: object())

    class _Boom(_FakeReceiver):
        def __init__(self, cfg):  # noqa: D401
            super().__init__(cfg)
            self.raise_in_run = RuntimeError("boom")

    monkeypatch.setattr(receiver_main, "Receiver", _Boom)
    with pytest.raises(RuntimeError, match="boom"):
        await receiver_main.main()
    [r] = _FakeWorker.instances
    assert r.client.aclose_called
    assert r.self_aclose_called  # type: ignore[attr-defined]


# ─── run() — asyncio.run thin wrapper ────────────────────────────────────


def test_worker_run_delegates_to_asyncio_run(monkeypatch):
    seen: list[object] = []

    def fake_run(coro):
        seen.append(coro)
        coro.close()

    monkeypatch.setattr(worker_main.asyncio, "run", fake_run)
    worker_main.run()
    assert len(seen) == 1


def test_receiver_run_delegates_to_asyncio_run(monkeypatch):
    seen: list[object] = []

    def fake_run(coro):
        seen.append(coro)
        coro.close()

    monkeypatch.setattr(receiver_main.asyncio, "run", fake_run)
    receiver_main.run()
    assert len(seen) == 1
