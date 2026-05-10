"""Worker stage accounting used by heartbeat queue fields."""

from __future__ import annotations

from sathop.worker.stages import DOWNLOADING, PENDING_DOWNLOAD, PROCESSING, WorkerStages


def test_stage_tracker_moves_one_handler_between_stages():
    stages = WorkerStages()
    tracker = stages.tracker()

    tracker.enter(PENDING_DOWNLOAD)
    assert stages.snapshot().pending_download == 1
    assert stages.snapshot().total == 1

    tracker.enter(DOWNLOADING)
    snap = stages.snapshot()
    assert snap.pending_download == 0
    assert snap.downloading == 1
    assert snap.total == 1

    tracker.exit()
    assert stages.snapshot().total == 0


def test_stage_trackers_do_not_clear_other_handlers():
    stages = WorkerStages()
    first = stages.tracker()
    second = stages.tracker()

    first.enter(PROCESSING)
    second.enter(PROCESSING)
    first.exit()

    snap = stages.snapshot()
    assert snap.processing == 1
    assert snap.heartbeat_fields()["queue_processing"] == 1

    second.exit()
    assert stages.snapshot().total == 0
