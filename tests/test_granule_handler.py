"""GranuleHandler data-plane orchestration — one granule's download → process
→ upload journey, driven directly with fakes (no lease loop / heartbeat /
backpressure). This is the seam runtime.py's Worker used to bury: previously
the event sequence could only be exercised through the full pipeline loop.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import sathop.worker.handler as H
from sathop.shared.protocol import InputSpec, LeaseItem
from sathop.shared.state_machine import UploadedObject
from sathop.worker.handler import GranuleHandler
from sathop.worker.processor import ProcessResult
from sathop.worker.progress import ProgressServer
from sathop.worker.stages import WorkerStages


class _FakeClient:
    """Placeholder collaborator. The handler stores it but no longer calls it for
    progress (that goes through the ProgressServer sink), so nothing is stubbed."""


class _FakeEvents:
    """Stand-in for the worker's EventBuffer — records enqueued event kinds in
    order so a handler's transition sequence can be asserted without an orch."""

    def __init__(self) -> None:
        self.kinds: list[str] = []
        self.events: list[object] = []

    def enqueue(self, event) -> None:
        self.kinds.append(event.kind)
        self.events.append(event)


class _FakeDownloader:
    async def fetch(self, url, dst: Path, auth=None, progress_cb=None) -> int:
        dst.write_bytes(b"x")
        return 1


class _FakeStorage:
    def __init__(self) -> None:
        self.puts: list[str] = []

    async def put(self, src: Path, object_key: str) -> UploadedObject:
        self.puts.append(object_key)
        return UploadedObject(object_key=object_key, presigned_url="u", sha256="s", size=1)


def _settings(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        worker_id="w1",
        work_root=tmp_path / "work",
        bundle_cache=tmp_path / "bundles",
        venv_cache=tmp_path / "venvs",
        shared_cache=tmp_path / "shared",
        orchestrator_url="http://orch",
        token="",
        download_concurrency=1,
        process_concurrency=1,
        upload_concurrency=1,
    )


def _item() -> LeaseItem:
    return LeaseItem(
        granule_id="g1",
        batch_id="b1",
        bundle_ref="orch:x@1",
        inputs=[InputSpec(url="http://h/f.hdf", filename="f.hdf", product="p")],
        meta={},
    )


def _handler(
    tmp_path: Path, storage: _FakeStorage, client: _FakeClient, events: _FakeEvents
) -> GranuleHandler:
    s = _settings(tmp_path)
    s.work_root.mkdir(parents=True, exist_ok=True)
    return GranuleHandler(
        s,
        client,
        _FakeDownloader(),
        storage,
        ProgressServer(lambda _gid, _ev: None, port=0),  # progress sink: no-op here
        WorkerStages(),
        events,
    )


def _patch_bundle(monkeypatch, result: ProcessResult) -> None:
    fake_handle = SimpleNamespace(
        manifest=SimpleNamespace(outputs=SimpleNamespace(object_key_template="{stem}{ext}"))
    )
    monkeypatch.setattr(H.bundle, "ensure", lambda *a, **k: fake_handle)

    async def fake_run_bundle(*a, **k) -> ProcessResult:
        return result

    monkeypatch.setattr(H, "run_bundle", fake_run_bundle)


async def test_handle_happy_path_emits_collapsed_event_sequence(tmp_path, monkeypatch):
    """Collapsed 3-event path: download_started → process_started (folds in
    download_finished) → upload_completed (folds in process_finished +
    upload_started). Three reliable round-trips instead of six."""
    client, storage, events = _FakeClient(), _FakeStorage(), _FakeEvents()
    _patch_bundle(monkeypatch, ProcessResult(True, [Path("out.tif")], "", "", 0))

    await _handler(tmp_path, storage, client, events).handle(_item())

    assert events.kinds == [
        "download_started",
        "process_started",
        "upload_completed",
    ]
    assert storage.puts == ["out.tif"]


async def test_handle_fast_mode_emits_only_upload_completed_with_durations(tmp_path, monkeypatch):
    """Fast detail mode (verbose=False): the worker skips the DownloadStarted /
    ProcessStarted waypoints entirely — a single upload_completed carries both
    measured stage durations so the orchestrator can still reconstruct timing."""
    client, storage, events = _FakeClient(), _FakeStorage(), _FakeEvents()
    _patch_bundle(monkeypatch, ProcessResult(True, [Path("out.tif")], "", "", 0))

    h = _handler(tmp_path, storage, client, events)
    h._verbose = False
    await h.handle(_item())

    assert events.kinds == ["upload_completed"]
    uc = events.events[0]
    assert uc.download_ms is not None  # folded in (verbose sends it on ProcessStarted)
    assert uc.process_ms is not None
    assert storage.puts == ["out.tif"]


async def test_handle_processing_failure_skips_upload(tmp_path, monkeypatch):
    """A non-ok ProcessResult emits processing_failed and never uploads —
    no upload_completed, no storage writes."""
    client, storage, events = _FakeClient(), _FakeStorage(), _FakeEvents()
    _patch_bundle(monkeypatch, ProcessResult(False, [], "", "boom", 1))

    await _handler(tmp_path, storage, client, events).handle(_item())

    assert events.kinds == [
        "download_started",
        "process_started",
        "processing_failed",
    ]
    assert storage.puts == []
