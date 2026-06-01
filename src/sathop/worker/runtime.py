"""Worker runtime orchestration."""

from __future__ import annotations

import asyncio
import logging
import time

import httpx
import psutil

from sathop import __version__
from sathop.shared import agent_lifecycle
from sathop.shared.periodic import run_periodic
from sathop.shared.protocol import (
    LeaseItem,
    LeaseRequest,
    WorkerHeartbeat,
    WorkerRegister,
)
from sathop.shared.release import write_pending_version
from sathop.shared.state_machine import DeleteConfirmed

from . import downloader, storage, tls
from .agent import OrchestratorClient
from .cleanup import CacheCleaner
from .config import Settings
from .event_buffer import EventBuffer
from .handler import GranuleHandler
from .progress import ProgressServer
from .progress_buffer import ProgressBuffer
from .stages import WorkerStages

log = logging.getLogger("sathop.worker")


class WorkerRemoved(BaseException):
    """Inherits BaseException so run_periodic's `except Exception` won't swallow it."""


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
        self._handlers: dict[str, asyncio.Task[None]] = {}
        self._live_download = s.download_concurrency
        self._live_process = s.process_concurrency
        self._reconfiguring = False
        self._ca_pem: str | None = None
        self._lease_backoff_factor = 1
        self._empty_backoff_factor = 1
        self._progress_buf = ProgressBuffer(self.client)
        self.progress = ProgressServer(self._progress_buf.enqueue_event, port=s.progress_port)
        self._events = EventBuffer(self.client)
        self._handler = GranuleHandler(
            s, self.client, self.downloader, self.storage, self.progress, self.stages, self._events
        )
        for path in (s.work_root, s.bundle_cache, s.venv_cache, s.shared_cache, s.storage_root):
            path.mkdir(parents=True, exist_ok=True)

    def _start_drain(self, reason: str) -> None:
        if self._draining:
            return
        self._draining = True
        log.warning("entering graceful drain (%s) — will exit after in-flight handlers complete", reason)

    def _stamp_pending_version(self, version: str) -> None:
        """Write the entrypoint's one-shot upgrade stamp so the post-drain restart
        installs `version`. Best-effort: a write failure (read-only repo dir, or
        running outside the container) degrades to a same-version restart rather
        than aborting the drain."""
        try:
            path = write_pending_version(version)
            log.info("stamped pending upgrade → v%s at %s", version, path)
        except Exception as e:
            log.warning("could not stamp pending upgrade v%s (will restart same version): %s", version, e)

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
        task = asyncio.create_task(self._handler.handle(item))
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
            tg.create_task(self._events.loop())
            tg.create_task(self._progress_buf.loop())
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
                    download_concurrency=self._live_download,
                    process_concurrency=self._live_process,
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
            if resp.update_to_version:
                self._stamp_pending_version(resp.update_to_version)
            self._start_drain(
                f"upgrade→v{resp.update_to_version} via orchestrator"
                if resp.update_to_version
                else "restart via orchestrator"
            )
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
        self._reconcile_concurrency(resp.download_concurrency, resp.process_concurrency)

    def _reconcile_concurrency(self, ov_dl: int | None, ov_pr: int | None) -> None:
        target_dl = ov_dl if ov_dl is not None else self.s.download_concurrency
        target_pr = ov_pr if ov_pr is not None else self.s.process_concurrency
        if target_dl == self._live_download and target_pr == self._live_process:
            return
        if self._reconfiguring:
            return  # in-flight reconfig; re-evaluated next heartbeat
        if target_dl < self._live_download or target_pr < self._live_process:
            asyncio.create_task(self._apply_reconfig(target_dl, target_pr))  # shrink path
            return
        if target_dl > self._live_download:  # grow path (instant)
            self._handler.grow_download(target_dl - self._live_download)
            log.info("download concurrency %d -> %d (live grow)", self._live_download, target_dl)
            self._live_download = target_dl
        if target_pr > self._live_process:
            self._handler.grow_process(target_pr - self._live_process)
            log.info("process concurrency %d -> %d (live grow)", self._live_process, target_pr)
            self._live_process = target_pr

    async def _apply_reconfig(self, target_dl: int, target_pr: int) -> None:
        # _reconfiguring gates leasing (not _draining) so this never trips the
        # terminal drain watchdog. try/finally guarantees the flag clears even on
        # cancellation/error — otherwise a stuck True would freeze all future
        # reconciliation. On error live_* stay unchanged, so the next heartbeat retries.
        self._reconfiguring = True
        try:
            log.warning(
                "reconfig concurrency dl %d->%d pr %d->%d — draining in-flight",
                self._live_download,
                target_dl,
                self._live_process,
                target_pr,
            )
            deadline = time.monotonic() + DRAIN_WATCHDOG_TIMEOUT_SEC
            while self._handlers and time.monotonic() < deadline:
                await asyncio.sleep(1)
            if self._handlers:
                log.warning(
                    "reconfig drain timeout — rebuilding with %d in-flight (lease sweeper reclaims)",
                    len(self._handlers),
                )
            self._handler = GranuleHandler(
                self.s,
                self.client,
                self.downloader,
                self.storage,
                self.progress,
                self.stages,
                self._events,
                download_concurrency=target_dl,
                process_concurrency=target_pr,
            )
            self._live_download, self._live_process = target_dl, target_pr
            log.info("concurrency reconfig applied dl=%d pr=%d", target_dl, target_pr)
        finally:
            self._reconfiguring = False

    async def _pipeline_loop(self) -> None:
        while True:
            ceiling = self._live_download + self._live_process
            free = ceiling - len(self._handlers)
            if free <= 0 or self._pause_lease or self._remote_pause or self._draining or self._reconfiguring:
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
                # No pending work for us: decay the empty-poll rate (×2 up to the
                # cap) so an idle fleet stops hammering /lease — the orchestrator
                # pays its full per-request tax even on an empty claim. Reset to
                # base the instant a lease returns work, so pickup stays fast
                # under load. Distinct from the failure backoff above.
                sleep_for = self.s.lease_poll_interval * self._empty_backoff_factor
                self._empty_backoff_factor = min(LEASE_MAX_BACKOFF_FACTOR, self._empty_backoff_factor * 2)
                await asyncio.sleep(sleep_for)
                continue

            self._empty_backoff_factor = 1
            for item in resp.items:
                self._start_handler(item)

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
            self._events.enqueue(
                DeleteConfirmed(
                    granule_id=dg.granule_id,
                    worker_id=self.s.worker_id,
                    object_keys=list(dg.object_keys),
                )
            )
            if dg.object_keys:
                log.info("[%s] deleted %d object(s) after ack", dg.granule_id, len(dg.object_keys))
