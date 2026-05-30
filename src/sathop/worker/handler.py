"""Granule data-plane: drive one leased Granule through download → process →
upload, emitting state-machine events at each boundary.

Split out of `runtime.py` so the per-granule journey has its own seam: a
`GranuleHandler` can be built with fake client/downloader/storage and driven
with a single `handle(item)` call — no lease loop, heartbeat, backpressure, or
signal handlers to stand up. The control-plane `Worker` owns those and just
hands each leased item to `handle`.

All transitions are buffered (not POSTed inline): the handler hands each event
to a shared `EventBuffer`, which coalesces events across all in-flight granules
into batched POSTs — the orchestrator pays its per-request cost once per flush,
not once per event, and the handler never awaits the orchestrator mid-pipeline.
Lease revocation is heartbeat-driven (the control-plane cancels the handler
task), so a lost lease surfaces as `CancelledError`, not a per-event 4xx."""

from __future__ import annotations

import asyncio
import logging
import shutil
import time
from pathlib import Path

from sathop.shared.protocol import LeaseItem, ProgressEvent
from sathop.shared.safe_path import safe_join
from sathop.shared.state_machine import (
    DownloadStarted,
    ProcessStarted,
    UploadCompleted,
    UploadedObject,
)

from . import bundle, downloader, storage
from ._paths import work_dir_path
from .agent import OrchestratorClient
from .config import Settings
from .event_buffer import EventBuffer
from .processor import ProcessResult, run_bundle
from .progress import ProgressServer
from .runtime_helpers import (
    auth_for,
    processing_failed_from_exception,
    processing_failed_from_result,
)
from .stages import (
    DOWNLOADING,
    PENDING_DOWNLOAD,
    PENDING_PROCESSING,
    PENDING_UPLOAD,
    PROCESSING,
    UPLOADING,
    StageTracker,
    WorkerStages,
    staged,
)
from .storage import render_key

log = logging.getLogger("sathop.worker")

DOWNLOAD_PROGRESS_MIN_INTERVAL_SECONDS = 2.0
DOWNLOAD_PROGRESS_MIN_DELTA_PERCENT = 5.0


class GranuleHandler:
    """Processes one leased Granule per `handle` call. A single instance is
    shared across concurrent handlers — the three semaphores cap how many
    granules occupy each pipeline section at once."""

    def __init__(
        self,
        settings: Settings,
        client: OrchestratorClient,
        downloader: downloader.Downloader,
        storage: storage.Storage,
        progress: ProgressServer,
        stages: WorkerStages,
        events: EventBuffer,
        *,
        download_concurrency: int | None = None,
        process_concurrency: int | None = None,
    ) -> None:
        self.s = settings
        self.client = client
        self.downloader = downloader
        self.storage = storage
        self.progress = progress
        self.stages = stages
        self._events = events
        dl = download_concurrency if download_concurrency is not None else settings.download_concurrency
        pr = process_concurrency if process_concurrency is not None else settings.process_concurrency
        self._download_sem = asyncio.Semaphore(dl)
        self._process_sem = asyncio.Semaphore(pr)
        self._upload_sem = asyncio.Semaphore(settings.upload_concurrency)

    def grow_download(self, delta: int) -> None:
        for _ in range(max(0, delta)):
            self._download_sem.release()

    def grow_process(self, delta: int) -> None:
        for _ in range(max(0, delta)):
            self._process_sem.release()

    async def handle(self, item: LeaseItem) -> None:
        gid = item.granule_id
        work_dir = work_dir_path(self.s.work_root, gid)
        work_dir.mkdir(parents=True, exist_ok=True)
        input_dir = work_dir / "input"
        input_dir.mkdir()
        nonce, progress_url = self.progress.issue(gid, item.batch_id)

        stage = self.stages.tracker()
        try:
            paths, download_ms = await self._download_inputs(item, input_dir, stage)
            handle, result, process_ms = await self._process_inputs(
                item, paths, download_ms, progress_url, stage, work_dir
            )

            if not result.ok:
                self._events.enqueue(processing_failed_from_result(gid, self.s.worker_id, result))
                log.warning("[%s] processing failed exit=%s", gid, result.exit_code)
                return

            await self._upload_outputs(item, handle, result.outputs, process_ms, stage)

        except asyncio.CancelledError:
            # Lease revoked: the heartbeat loop cancels this task. Don't emit —
            # the orchestrator already reassigned the granule.
            log.info("[%s] handler aborted (lease revoked)", gid)
            raise
        except Exception as e:
            log.exception("[%s] unhandled error", gid)
            self._events.enqueue(processing_failed_from_exception(gid, self.s.worker_id, e))
        finally:
            stage.exit()
            self.progress.revoke(nonce)
            shutil.rmtree(work_dir, ignore_errors=True)

    async def _download_inputs(
        self, item: LeaseItem, input_dir: Path, stage: StageTracker
    ) -> tuple[list[Path], int]:
        gid = item.granule_id
        paths: list[Path] = []
        async with staged(stage, PENDING_DOWNLOAD, self._download_sem, DOWNLOADING):
            self._events.enqueue(DownloadStarted(granule_id=gid, worker_id=self.s.worker_id))
            log.info("[%s] downloading %d input(s)", gid, len(item.inputs))
            t0 = time.monotonic()
            for spec in item.inputs:
                dst = safe_join(input_dir, spec.filename)
                auth = auth_for(item.credentials, spec.credential, gid, log)
                cb = self._make_download_progress_cb(gid, item.batch_id, spec.filename)
                await self.downloader.fetch(spec.url, dst, auth=auth, progress_cb=cb)
                if spec.checksum:
                    await downloader.verify_sha256(dst, spec.checksum)
                paths.append(dst)
            download_ms = int((time.monotonic() - t0) * 1000)
        # DownloadFinished folded into ProcessStarted(download_ms) — one fewer
        # orchestrator round-trip on the handler critical path.
        return paths, download_ms

    async def _process_inputs(
        self,
        item: LeaseItem,
        paths: list[Path],
        download_ms: int,
        progress_url: str,
        stage: StageTracker,
        work_dir: Path,
    ) -> tuple[bundle.BundleHandle, ProcessResult, int]:
        gid = item.granule_id
        handle = await asyncio.to_thread(
            bundle.ensure,
            item.bundle_ref,
            self.s.bundle_cache,
            self.s.venv_cache,
            self.s.shared_cache,
            self.s.orchestrator_url,
            self.s.token,
        )
        async with staged(stage, PENDING_PROCESSING, self._process_sem, PROCESSING):
            self._events.enqueue(
                ProcessStarted(granule_id=gid, worker_id=self.s.worker_id, download_ms=download_ms)
            )
            t0 = time.monotonic()
            result = await run_bundle(
                handle,
                gid,
                item.batch_id,
                paths,
                item.meta,
                work_dir,
                item.execution_env,
                progress_url,
            )
            process_ms = int((time.monotonic() - t0) * 1000)
        return handle, result, process_ms

    async def _upload_outputs(
        self,
        item: LeaseItem,
        handle: bundle.BundleHandle,
        outputs: list[Path],
        process_ms: int,
        stage: StageTracker,
    ) -> None:
        gid = item.granule_id
        # ProcessFinished + UploadStarted folded into UploadCompleted(process_ms):
        # the granule stays PROCESSING through the (sub-second) upload, then jumps
        # straight to UPLOADED — two fewer round-trips per granule.
        async with staged(stage, PENDING_UPLOAD, self._upload_sem, UPLOADING):
            uploaded: list[UploadedObject] = []
            key_tpl = handle.manifest.outputs.object_key_template
            for out in outputs:
                key = render_key(key_tpl, out, item.meta)
                uploaded.append(await self.storage.put(out, key))
            self._events.enqueue(
                UploadCompleted(
                    granule_id=gid,
                    worker_id=self.s.worker_id,
                    objects=uploaded,
                    process_ms=process_ms,
                )
            )
        log.info("[%s] uploaded %d object(s)", gid, len(uploaded))

    def _make_download_progress_cb(self, gid: str, batch_id: str, filename: str) -> downloader.ProgressCb:
        last_pct = -1.0
        last_ts = 0.0
        done = False

        async def cb(downloaded: int, total: int | None) -> None:
            nonlocal last_pct, last_ts, done
            if done:
                return
            now = time.monotonic()
            pct = (downloaded / total * 100.0) if total else None
            is_final = pct is not None and pct >= 100.0
            enough_time_passed = now - last_ts >= DOWNLOAD_PROGRESS_MIN_INTERVAL_SECONDS
            enough_percent_passed = pct is not None and pct >= last_pct + DOWNLOAD_PROGRESS_MIN_DELTA_PERCENT
            if not (is_final or enough_time_passed or enough_percent_passed):
                return
            last_ts = now
            if pct is not None:
                last_pct = pct
            done = is_final
            try:
                await self.client.report_progress(
                    gid,
                    ProgressEvent(
                        step=f"download:{filename}",
                        pct=pct,
                        detail=downloader.progress_detail(downloaded, total),
                        batch_id=batch_id,
                    ),
                )
            except Exception as e:
                log.debug("[%s] download progress emit failed: %s", gid, e)

        return cb
