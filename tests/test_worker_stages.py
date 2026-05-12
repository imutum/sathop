"""Worker stage accounting used by heartbeat queue fields."""

from __future__ import annotations

import asyncio

import pytest

from sathop.worker.stages import (
    DOWNLOADING,
    PENDING_DOWNLOAD,
    PROCESSING,
    WorkerStages,
    staged,
)


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


async def test_staged_flips_pending_to_active_then_clears():
    stages = WorkerStages()
    tracker = stages.tracker()
    sem = asyncio.Semaphore(1)

    seen: list[tuple[int, int]] = []

    async with staged(tracker, PENDING_DOWNLOAD, sem, DOWNLOADING):
        snap = stages.snapshot()
        seen.append((snap.pending_download, snap.downloading))
    final = stages.snapshot()
    seen.append((final.pending_download, final.downloading))

    assert seen == [(0, 1), (0, 0)]


async def test_staged_clears_counter_on_exception():
    stages = WorkerStages()
    tracker = stages.tracker()
    sem = asyncio.Semaphore(1)

    with pytest.raises(RuntimeError, match="boom"):
        async with staged(tracker, PENDING_DOWNLOAD, sem, DOWNLOADING):
            raise RuntimeError("boom")
    assert stages.snapshot().total == 0


async def test_staged_counts_pending_while_semaphore_blocked():
    stages = WorkerStages()
    sem = asyncio.Semaphore(1)
    holder_tracker = stages.tracker()
    waiter_tracker = stages.tracker()

    holding = asyncio.Event()
    release = asyncio.Event()

    async def holder():
        async with staged(holder_tracker, PENDING_DOWNLOAD, sem, DOWNLOADING):
            holding.set()
            await release.wait()

    async def waiter():
        async with staged(waiter_tracker, PENDING_DOWNLOAD, sem, DOWNLOADING):
            pass

    holder_task = asyncio.create_task(holder())
    await holding.wait()

    waiter_task = asyncio.create_task(waiter())
    # Yield once so the waiter reaches the `await sem.acquire()` inside `staged`.
    await asyncio.sleep(0)

    mid = stages.snapshot()
    assert (mid.pending_download, mid.downloading) == (1, 1)

    release.set()
    await holder_task
    await waiter_task
    assert stages.snapshot().total == 0
