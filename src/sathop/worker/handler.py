"""Granule data-plane: drive one leased Granule through download → process →
upload, emitting state-machine events at each boundary.

Split out of `runtime.py` so the per-granule journey has its own seam: a
`GranuleHandler` can be built with fake client/downloader/storage and driven
with a single `handle(item)` call — no lease loop, heartbeat, backpressure, or
signal handlers to stand up. The control-plane `Worker` owns those and just
hands each leased item to `handle`.

The two event-emission policies are module functions (not handler methods) so
they're testable in isolation and reusable by the control-plane janitor:
`emit_lease_event` aborts the handler on a lost lease; `emit_best_effort`
swallows everything (used where a second failure must not cascade)."""

from __future__ import annotations

import asyncio
import logging
import shutil
import time
from pathlib import Path

import httpx

from sathop.shared.protocol import LeaseItem, ProgressEvent
from sathop.shared.safe_path import safe_join
from sathop.shared.state_machine import (
    DownloadFinished,
    DownloadStarted,
    GranuleEvent,
    ProcessFinished,
    ProcessStarted,
    UploadCompleted,
    UploadedObject,
    UploadStarted,
)

from . import bundle, downloader, storage
from ._paths import work_dir_path
from .agent import OrchestratorClient
from .config import Settings
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


class LeaseRevoked(Exception):
    """Raised mid-handle when the orchestrator no longer recognises our lease
    (a state-event came back 404/409); the handler aborts cleanly."""


async def emit_lease_event(client: OrchestratorClient, event: GranuleEvent) -> None:
    """Emit an event whose 4xx means the lease no longer exists; the caller
    aborts the handler via `LeaseRevoked` so we don't keep doing work for a
    granule the orchestrator has reassigned. 5xx is logged and swallowed —
    treat it as transient."""
    try:
        await client.emit_event(event)
    except httpx.HTTPStatusError as e:
        if e.response.status_code in (404, 409):
            log.warning(
                "[%s] lease revoked while emitting %s (HTTP %d) — aborting handler",
                event.granule_id,
                event.kind,
                e.response.status_code,
            )
            raise LeaseRevoked from e
        log.warning("[%s] emit %s failed: %s", event.granule_id, event.kind, e)
    except Exception as e:
        log.warning("[%s] emit %s failed: %s", event.granule_id, event.kind, e)


async def emit_best_effort(client: OrchestratorClient, event: GranuleEvent) -> None:
    """Emit an event whose failure must not loop us back into another failure
    path (the failure-report itself, the janitor's delete-confirm). Log and
    swallow."""
    try:
        await client.emit_event(event)
    except Exception as e:
        log.warning("[%s] emit %s failed: %s", event.granule_id, event.kind, e)


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
    ) -> None:
        self.s = settings
        self.client = client
        self.downloader = downloader
        self.storage = storage
        self.progress = progress
        self.stages = stages
        self._download_sem = asyncio.Semaphore(settings.download_concurrency)
        self._process_sem = asyncio.Semaphore(settings.process_concurrency)
        self._upload_sem = asyncio.Semaphore(settings.upload_concurrency)

    async def handle(self, item: LeaseItem) -> None:
        gid = item.granule_id
        work_dir = work_dir_path(self.s.work_root, gid)
        work_dir.mkdir(parents=True, exist_ok=True)
        input_dir = work_dir / "input"
        input_dir.mkdir()
        nonce, progress_url = self.progress.issue(gid, item.batch_id)

        stage = self.stages.tracker()
        try:
            paths = await self._download_inputs(item, input_dir, stage)
            handle, result = await self._process_inputs(item, paths, progress_url, stage, work_dir)

            if not result.ok:
                await emit_best_effort(
                    self.client, processing_failed_from_result(gid, self.s.worker_id, result)
                )
                log.warning("[%s] processing failed exit=%s", gid, result.exit_code)
                return

            await self._upload_outputs(item, handle, result.outputs, stage)

        except LeaseRevoked:
            log.info("[%s] handler aborted (lease revoked)", gid)
        except Exception as e:
            log.exception("[%s] unhandled error", gid)
            await emit_best_effort(self.client, processing_failed_from_exception(gid, self.s.worker_id, e))
        finally:
            stage.exit()
            self.progress.revoke(nonce)
            shutil.rmtree(work_dir, ignore_errors=True)

    async def _download_inputs(self, item: LeaseItem, input_dir: Path, stage: StageTracker) -> list[Path]:
        gid = item.granule_id
        paths: list[Path] = []
        async with staged(stage, PENDING_DOWNLOAD, self._download_sem, DOWNLOADING):
            await emit_lease_event(self.client, DownloadStarted(granule_id=gid, worker_id=self.s.worker_id))
            log.info("[%s] downloading %d input(s)", gid, len(item.inputs))
            for spec in item.inputs:
                dst = safe_join(input_dir, spec.filename)
                auth = auth_for(item.credentials, spec.credential, gid, log)
                cb = self._make_download_progress_cb(gid, item.batch_id, spec.filename)
                await self.downloader.fetch(spec.url, dst, auth=auth, progress_cb=cb)
                if spec.checksum:
                    await downloader.verify_sha256(dst, spec.checksum)
                paths.append(dst)
        await emit_lease_event(self.client, DownloadFinished(granule_id=gid, worker_id=self.s.worker_id))
        return paths

    async def _process_inputs(
        self,
        item: LeaseItem,
        paths: list[Path],
        progress_url: str,
        stage: StageTracker,
        work_dir: Path,
    ) -> tuple[bundle.BundleHandle, ProcessResult]:
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
            await emit_lease_event(self.client, ProcessStarted(granule_id=gid, worker_id=self.s.worker_id))
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
        return handle, result

    async def _upload_outputs(
        self,
        item: LeaseItem,
        handle: bundle.BundleHandle,
        outputs: list[Path],
        stage: StageTracker,
    ) -> None:
        gid = item.granule_id
        await emit_lease_event(self.client, ProcessFinished(granule_id=gid, worker_id=self.s.worker_id))
        async with staged(stage, PENDING_UPLOAD, self._upload_sem, UPLOADING):
            await emit_lease_event(self.client, UploadStarted(granule_id=gid, worker_id=self.s.worker_id))
            uploaded: list[UploadedObject] = []
            key_tpl = handle.manifest.outputs.object_key_template
            for out in outputs:
                key = render_key(key_tpl, out, item.meta)
                uploaded.append(await self.storage.put(out, key))
            await emit_lease_event(
                self.client,
                UploadCompleted(
                    granule_id=gid,
                    worker_id=self.s.worker_id,
                    objects=uploaded,
                ),
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
