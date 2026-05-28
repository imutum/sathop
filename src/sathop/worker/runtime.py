"""Worker runtime orchestration."""

from __future__ import annotations

import asyncio
import logging
import shutil
import time
from pathlib import Path

import httpx
import psutil

from sathop import __version__
from sathop.shared import agent_lifecycle
from sathop.shared.periodic import run_periodic
from sathop.shared.protocol import (
    LeaseItem,
    LeaseRequest,
    ProgressEvent,
    WorkerHeartbeat,
    WorkerRegister,
)
from sathop.shared.safe_path import safe_join
from sathop.shared.state_machine import (
    DeleteConfirmed,
    DownloadFinished,
    DownloadStarted,
    GranuleEvent,
    ProcessFinished,
    ProcessStarted,
    UploadCompleted,
    UploadedObject,
    UploadStarted,
)

from . import bundle, downloader, storage, tls
from ._paths import work_dir_path
from .agent import OrchestratorClient
from .cleanup import CacheCleaner
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


class LeaseRevoked(Exception):
    pass


class WorkerRemoved(BaseException):
    """Inherits BaseException so run_periodic's `except Exception` won't swallow it."""


DOWNLOAD_PROGRESS_MIN_INTERVAL_SECONDS = 2.0
DOWNLOAD_PROGRESS_MIN_DELTA_PERCENT = 5.0
LEASE_MAX_BACKOFF_FACTOR = 6
DRAIN_WATCHDOG_TIMEOUT_SEC = 60
EXIT_CODE_REMOVED = 42


class Worker:
    def __init__(self, s: Settings) -> None:
        self.s = s
        self.client = OrchestratorClient(s.orchestrator_url, s.token)
        self.downloader = downloader.load(s.aria2_rpc, s.aria2_secret)
        self.storage = storage.load(
            use_minio=s.use_minio,
            public_base_url=s.public_url,
            storage_root=s.storage_root,
            minio_access_key=s.minio_access_key,
            minio_secret_key=s.minio_secret_key,
            minio_bucket=s.minio_bucket,
        )
        self.stages = WorkerStages()
        self.cleaner = CacheCleaner(s, lambda: set(self._handlers.keys()))
        self._pause_lease = False
        self._remote_pause = False
        self._gc_event = asyncio.Event()
        self._draining = False
        self._download_sem = asyncio.Semaphore(s.download_concurrency)
        self._process_sem = asyncio.Semaphore(s.process_concurrency)
        self._upload_sem = asyncio.Semaphore(s.upload_concurrency)
        self._handlers: dict[str, asyncio.Task[None]] = {}
        self._effective_capacity = s.capacity
        self._ca_pem: str | None = None
        self._lease_backoff_factor = 1
        self.progress = ProgressServer(self.client, port=s.progress_port)
        for path in (s.work_root, s.bundle_cache, s.venv_cache, s.shared_cache, s.storage_root):
            path.mkdir(parents=True, exist_ok=True)

    def _start_drain(self, reason: str) -> None:
        if self._draining:
            return
        self._draining = True
        log.warning("entering graceful drain (%s) — will exit after in-flight handlers complete", reason)

    def _bump_backoff(self) -> int:
        self._lease_backoff_factor = min(LEASE_MAX_BACKOFF_FACTOR, self._lease_backoff_factor * 2)
        return self.s.lease_poll_interval * self._lease_backoff_factor

    async def _sleep_after_lease_failure(self, reason: str) -> None:
        sleep_for = self._bump_backoff()
        log.warning("lease failed (%s) — slowing poll ×%d", reason, self._lease_backoff_factor)
        await asyncio.sleep(sleep_for)

    @staticmethod
    def _lease_failure_reason(e: Exception) -> str:
        if isinstance(e, httpx.HTTPStatusError):
            code = e.response.status_code
            return "worker disabled" if code == 403 else f"HTTP {code}"
        return str(e)

    def _start_handler(self, item: LeaseItem) -> None:
        gid = item.granule_id
        task = asyncio.create_task(self._handle(item))
        self._handlers[gid] = task
        task.add_done_callback(lambda _task, _gid=gid: self._handlers.pop(_gid, None))

    def _install_signal_handlers(self) -> None:
        agent_lifecycle.install_signal_handlers(self._start_drain)

    async def _drain_watchdog_loop(self) -> None:
        await agent_lifecycle.drain_watchdog_loop(
            lambda: self._draining,
            self._handlers,
            log,
            timeout_sec=DRAIN_WATCHDOG_TIMEOUT_SEC,
            active_noun="handler",
            reclaim_message="lease sweeper will reclaim",
        )

    def _ensure_tls(self) -> str | None:
        if not self.s.public_url.lower().startswith("https://"):
            return None
        pem = tls.ensure_self_signed(self.s.public_url, self.s.tls_cert_path, self.s.tls_key_path)
        log.info(
            "TLS cert ready at %s (host=%s, %d bytes PEM)",
            self.s.tls_cert_path,
            self.s.public_url,
            len(pem),
        )
        return pem

    async def _register(self) -> None:
        await self.client.register(
            WorkerRegister(
                worker_id=self.s.worker_id,
                version=__version__,
                capacity=self.s.capacity,
                public_url=self.s.public_url,
                ca_pem=self._ca_pem,
            )
        )

    async def run(self) -> None:
        self._install_signal_handlers()
        self._ca_pem = self._ensure_tls()
        await self._register()
        log.info(
            "registered as %s v%s (downloader=%s, storage=%s, tls=%s)",
            self.s.worker_id,
            __version__,
            type(self.downloader).__name__,
            type(self.storage).__name__,
            "on" if self._ca_pem else "off",
        )

        def create_tasks(tg: asyncio.TaskGroup) -> None:
            tg.create_task(self._heartbeat_loop())
            tg.create_task(self._pipeline_loop())
            tg.create_task(self._janitor_loop())
            tg.create_task(self._backpressure_loop())
            tg.create_task(self.cleaner.loop(self._gc_event))
            tg.create_task(self._drain_watchdog_loop())
            tg.create_task(self.progress.serve())
            if getattr(self.storage, "needs_static_server", False):
                tg.create_task(
                    storage.serve_static(
                        self.s.storage_root,
                        self.s.storage_port,
                        tls_cert=self.s.tls_cert_path if self._ca_pem else None,
                        tls_key=self.s.tls_key_path if self._ca_pem else None,
                    )
                )

        await agent_lifecycle.run_agent(create_tasks, log=log)

    async def _heartbeat_loop(self) -> None:
        await run_periodic(
            self._heartbeat_once,
            interval=self.s.heartbeat_interval,
            log=log,
            name="heartbeat",
        )

    async def _heartbeat_once(self) -> None:
        try:
            du = psutil.disk_usage(str(self.s.storage_root))
            vm = psutil.virtual_memory()
            stage_snapshot = self.stages.snapshot()
            resp = await self.client.heartbeat(
                WorkerHeartbeat(
                    worker_id=self.s.worker_id,
                    version=__version__,
                    disk_used_gb=(du.total - du.free) / 1024**3,
                    disk_total_gb=du.total / 1024**3,
                    cpu_percent=psutil.cpu_percent(interval=None),
                    mem_percent=vm.percent,
                    paused=self._pause_lease or self._remote_pause,
                    active_granule_ids=list(self._handlers.keys()),
                    **stage_snapshot.heartbeat_fields(),
                )
            )
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 410:
                raise WorkerRemoved from e
            if e.response.status_code != 404:
                raise
            log.warning("heartbeat 404 — worker row missing, re-registering")
            try:
                await self._register()
                log.info("re-registered after 404")
            except httpx.HTTPStatusError as reg_e:
                if reg_e.response.status_code == 410:
                    raise WorkerRemoved from reg_e
                log.warning("re-register failed (will retry next beat): %s", reg_e)
            except Exception as reg_e:
                log.warning("re-register failed (will retry next beat): %s", reg_e)
            return
        if resp.removed:
            raise WorkerRemoved
        if resp.update_requested:
            self._start_drain("update_requested via orchestrator")
        if self._remote_pause != resp.operator_paused:
            log.info("remote pause %s", "engaged" if resp.operator_paused else "released")
            self._remote_pause = resp.operator_paused
        if resp.gc_requested:
            log.info("orchestrator requested cache GC — waking gc loop")
            self._gc_event.set()
        for gid in resp.revoked_granule_ids:
            task = self._handlers.get(gid)
            if task is not None and not task.done():
                log.info("[%s] cancelling handler — orchestrator revoked lease", gid)
                task.cancel()
        desired = resp.desired_capacity
        new_eff = min(self.s.capacity, max(0, desired)) if desired is not None else self.s.capacity
        if new_eff != self._effective_capacity:
            log.info(
                "effective capacity %d → %d (env=%d, override=%s)",
                self._effective_capacity,
                new_eff,
                self.s.capacity,
                desired,
            )
            self._effective_capacity = new_eff

    async def _pipeline_loop(self) -> None:
        while True:
            ceiling = min(self._effective_capacity, self.s.process_concurrency + self.s.download_concurrency)
            free = ceiling - len(self._handlers)
            if free <= 0 or self._pause_lease or self._remote_pause or self._draining:
                await asyncio.sleep(self.s.lease_poll_interval)
                continue
            try:
                resp = await self.client.lease(LeaseRequest(worker_id=self.s.worker_id, capacity=free))
                self._lease_backoff_factor = 1
            except httpx.HTTPStatusError as e:
                await self._sleep_after_lease_failure(self._lease_failure_reason(e))
                continue
            except Exception as e:
                await self._sleep_after_lease_failure(str(e))
                continue

            if not resp.items:
                await asyncio.sleep(self.s.lease_poll_interval)
                continue

            for item in resp.items:
                self._start_handler(item)

    async def _handle(self, item: LeaseItem) -> None:
        gid = item.granule_id
        work_dir = work_dir_path(self.s.work_root, gid)
        work_dir.mkdir(parents=True, exist_ok=True)
        input_dir = work_dir / "input"
        input_dir.mkdir()
        nonce, progress_url = self.progress.issue(gid, item.batch_id)

        stage = self.stages.tracker()
        try:
            paths = await self._download_inputs(item, input_dir, stage)
            handle, result = await self._process_inputs(item, paths, progress_url, stage)

            if not result.ok:
                await self._emit_best_effort(processing_failed_from_result(gid, self.s.worker_id, result))
                log.warning("[%s] processing failed exit=%s", gid, result.exit_code)
                return

            await self._upload_outputs(item, handle, result.outputs, stage)

        except LeaseRevoked:
            log.info("[%s] handler aborted (lease revoked)", gid)
        except Exception as e:
            log.exception("[%s] unhandled error", gid)
            await self._emit_best_effort(processing_failed_from_exception(gid, self.s.worker_id, e))
        finally:
            stage.exit()
            self.progress.revoke(nonce)
            shutil.rmtree(work_dir, ignore_errors=True)

    async def _download_inputs(self, item: LeaseItem, input_dir: Path, stage: StageTracker) -> list[Path]:
        gid = item.granule_id
        paths: list[Path] = []
        async with staged(stage, PENDING_DOWNLOAD, self._download_sem, DOWNLOADING):
            await self._emit_lease_event(DownloadStarted(granule_id=gid, worker_id=self.s.worker_id))
            log.info("[%s] downloading %d input(s)", gid, len(item.inputs))
            for spec in item.inputs:
                dst = safe_join(input_dir, spec.filename)
                auth = auth_for(item.credentials, spec.credential, gid, log)
                cb = self._make_download_progress_cb(gid, item.batch_id, spec.filename)
                await self.downloader.fetch(spec.url, dst, auth=auth, progress_cb=cb)
                if spec.checksum:
                    await downloader.verify_sha256(dst, spec.checksum)
                paths.append(dst)
        await self._emit_lease_event(DownloadFinished(granule_id=gid, worker_id=self.s.worker_id))
        return paths

    async def _process_inputs(
        self,
        item: LeaseItem,
        paths: list[Path],
        progress_url: str,
        stage: StageTracker,
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
            await self._emit_lease_event(ProcessStarted(granule_id=gid, worker_id=self.s.worker_id))
            result = await run_bundle(
                handle,
                gid,
                item.batch_id,
                paths,
                item.meta,
                self.s.work_root,
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
        await self._emit_lease_event(ProcessFinished(granule_id=gid, worker_id=self.s.worker_id))
        async with staged(stage, PENDING_UPLOAD, self._upload_sem, UPLOADING):
            await self._emit_lease_event(UploadStarted(granule_id=gid, worker_id=self.s.worker_id))
            uploaded: list[UploadedObject] = []
            key_tpl = handle.manifest.outputs.object_key_template
            for out in outputs:
                key = render_key(key_tpl, out, item.meta)
                uploaded.append(await self.storage.put(out, key))
            await self._emit_lease_event(
                UploadCompleted(
                    granule_id=gid,
                    worker_id=self.s.worker_id,
                    objects=uploaded,
                )
            )
        log.info("[%s] uploaded %d object(s)", gid, len(uploaded))

    async def _emit_lease_event(self, event: GranuleEvent) -> None:
        """Emit an event whose 4xx means the lease no longer exists; the caller
        aborts the handler via `LeaseRevoked` so we don't keep doing work for a
        granule the orchestrator has reassigned. 5xx is logged and swallowed —
        treat it as transient."""
        try:
            await self.client.emit_event(event)
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

    async def _emit_best_effort(self, event: GranuleEvent) -> None:
        """Emit an event whose failure must not loop us back into another
        failure path (the failure-report itself, the janitor's delete-confirm).
        Log and swallow."""
        try:
            await self.client.emit_event(event)
        except Exception as e:
            log.warning("[%s] emit %s failed: %s", event.granule_id, event.kind, e)

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

    async def _backpressure_loop(self) -> None:
        await run_periodic(
            self._backpressure_once,
            interval=self.s.backpressure_interval,
            log=log,
            name="backpressure check",
        )

    async def _backpressure_once(self) -> None:
        du = psutil.disk_usage(str(self.s.storage_root))
        used = (du.total - du.free) / du.total
        was = self._pause_lease
        if was and used < self.s.disk_resume_pct:
            self._pause_lease = False
        elif not was and used > self.s.disk_pause_pct:
            self._pause_lease = True
        if self._pause_lease != was:
            log.warning("backpressure: disk=%.1f%% pause_lease=%s", used * 100, self._pause_lease)

    async def _janitor_loop(self) -> None:
        await run_periodic(self._janitor_once, interval=30, log=log, name="janitor")

    async def _janitor_once(self) -> None:
        to_delete = await self.client.get_deletable(self.s.worker_id)
        for dg in to_delete:
            for key in dg.object_keys:
                await self.storage.delete(key)
            await self._emit_best_effort(
                DeleteConfirmed(
                    granule_id=dg.granule_id,
                    worker_id=self.s.worker_id,
                    object_keys=list(dg.object_keys),
                )
            )
            if dg.object_keys:
                log.info("[%s] deleted %d object(s) after ack", dg.granule_id, len(dg.object_keys))
