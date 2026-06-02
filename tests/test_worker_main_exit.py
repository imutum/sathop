"""worker.main must exit with a clean SystemExit(EXIT_CODE_REMOVED) when the
orchestrator removes the worker. `sys.exit` inside an `except*` handler is
re-wrapped into a BaseExceptionGroup (PEP 654), which degrades the exit code to 1
and makes the entrypoint restart-loop a cleanly-removed worker — so this asserts
a bare SystemExit with the right code propagates."""

from __future__ import annotations

import pytest

from sathop.worker import main as worker_main
from sathop.worker.runtime import EXIT_CODE_REMOVED, WorkerRemoved


class _Aclose:
    async def aclose(self) -> None: ...


class _FakeWorker:
    def __init__(self) -> None:
        self.client = _Aclose()
        self.downloader = _Aclose()

    async def run(self) -> None:
        raise WorkerRemoved


async def test_main_exits_clean_removed_code(monkeypatch):
    monkeypatch.setattr(worker_main, "load", lambda: None)
    monkeypatch.setattr(worker_main, "Worker", lambda _s: _FakeWorker())

    with pytest.raises(SystemExit) as exc:
        await worker_main.main()

    # The key assertion: a bare SystemExit with code 42 — NOT a BaseExceptionGroup.
    assert exc.value.code == EXIT_CODE_REMOVED
