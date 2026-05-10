"""Worker main loop.

Concurrent coroutines:
  - heartbeat:    periodic resource/queue report to orchestrator
  - pipeline:     lease → download → process → upload → report
  - janitor:      poll deletable list, remove acked objects from local storage
  - backpressure: gate new leases when disk is tight
  - http:         (LocalStorage only) serve storage_root as HTTP
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import signal
import time
import traceback
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import httpx
import psutil

from sathop import __version__
from sathop.shared.protocol import (
    Credential,
    GranuleState,
    LeaseItem,
    LeaseRequest,
    ProcessFailure,
    ProgressEvent,
    UploadedObject,
    WorkerHeartbeat,
    WorkerRegister,
)

from . import bundle, downloader, storage, tls
from . import shared as shared_sync
from ._paths import safe_segment
from .agent import OrchestratorClient
from .config import Settings, load
from .processor import ProcessResult, run_bundle
from .progress import ProgressServer

log = logging.getLogger("sathop.worker")

_PROCESSING_FAILURE_TAIL_CHARS = 2000
_WORKER_TRACEBACK_TAIL_CHARS = 1500
# Bundle subprocess stdout/stderr tails forwarded to orchestrator on failure.
# 16 KB ≈ 4 screens of text — enough to see full Python tracebacks plus a
# reasonable prelude, without bloating the failure POST body. Orchestrator
# caps to the same value when persisting.
_PROCESS_OUTPUT_TAIL_CHARS = 16000


class LeaseRevoked(Exception):
    """Orchestrator says we no longer own this granule (lease swept while we
    were working, or we restarted and forgot the prior lease). Abort the
    handler immediately — any further upload/state report would 409 too, and
    keeping the work going wastes the download/CPU."""


_DOWNLOAD_PROGRESS_MIN_INTERVAL_SECONDS = 2.0
_DOWNLOAD_PROGRESS_MIN_DELTA_PERCENT = 5.0
# Drain watchdog: once draining is set, wait up to this long for in-flight
# handlers to finish naturally before forcing exit. Tuned for the typical
# bundle (1-3 min process); a runaway 10 min process gets cut off and the
# orchestrator's lease sweeper picks the granule back up after the 30 min
# lease expiry. Trade-off matches docker-compose stop_grace_period: 60s.
_DRAIN_WATCHDOG_TIMEOUT_SEC = 60
_DRAIN_POLL_INTERVAL_SEC = 1.0
_StageTransition = Callable[[str], None]
_StageExit = Callable[[], None]


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
        self.stage: Counter[str] = Counter()
        # Worker-side disk-watermark pause; set by _backpressure_loop.
        self._pause_lease = False
        # Operator-set pause delivered via heartbeat reply (pause_requested).
        # Combined with _pause_lease in pipeline_loop's gate check; reported
        # together as `paused` on the heartbeat so old UIs see one flag.
        self._remote_pause = False
        # Set by heartbeat when the orchestrator delivers a one-shot gc_requested.
        # _gc_loop awaits the event and runs an out-of-cycle prune_caches pass.
        self._gc_event = asyncio.Event()
        # Set to True on SIGTERM/SIGINT or operator-requested restart. The
        # pipeline loop stops requesting new leases; in-flight handlers run to
        # completion. _drain_watchdog_loop forces exit after the timeout if
        # handlers don't finish on their own (e.g. a stuck process subprocess).
        self._draining = False
        self._download_sem = asyncio.Semaphore(s.download_concurrency)
        # CPU 是 process 阶段的硬瓶颈 — modis 重投影/解压都是计算密集型，让
        # 多个粒同时跑只会线性拉长每个粒的耗时（实测 6 并发下单粒 6.2 min，
        # 限并发到核数后单粒应回落到 ~1 min）。capacity 控制 in-flight 总数
        # 仍然 > process 并发，所以下载/上传可以与处理重叠。
        self._process_sem = asyncio.Semaphore(s.process_concurrency)
        # Upload concurrency cap: protects worker uplink + receiver pull
        # bandwidth from getting drowned when N granules finish processing
        # at the same time and try to ship to MinIO/WAN simultaneously.
        # Default = process_concurrency so a stock worker behaves identically
        # to pre-knob versions.
        self._upload_sem = asyncio.Semaphore(s.upload_concurrency)
        # Granule ID → handler task. Keyed lookup lets the heartbeat loop
        # cancel ghost tasks (lease revoked by orchestrator) by gid; the
        # mapping also doubles as the strong-ref keepalive that asyncio
        # docs warn about (create_task is weakly referenced).
        self._handlers: dict[str, asyncio.Task[None]] = {}
        # Updated from heartbeat replies; orchestrator may clamp below s.capacity.
        self._effective_capacity = s.capacity
        self.progress = ProgressServer(self.client, port=s.progress_port)
        for p in (s.work_root, s.bundle_cache, s.venv_cache, s.shared_cache, s.storage_root):
            p.mkdir(parents=True, exist_ok=True)

    def _start_drain(self, reason: str) -> None:
        """Idempotent. Logs once on first call; subsequent calls are no-ops so
        a SIGTERM hot on the heels of a SIGINT (or vice versa) doesn't spam
        the log or reset any state."""
        if self._draining:
            return
        self._draining = True
        log.warning("entering graceful drain (%s) — will exit after in-flight handlers complete", reason)

    def _install_signal_handlers(self) -> None:
        """SIGTERM = docker stop / kubectl drain; SIGINT = Ctrl+C in dev.
        Either should trigger drain instead of immediate exit. We try the
        asyncio API first (clean integration with the running loop) and fall
        back to signal.signal on Windows where add_signal_handler raises
        NotImplementedError. The fallback runs the callback in a separate
        thread and that thread can't touch loop-bound state safely, so it
        only flips a plain boolean — which is exactly what _start_drain does."""
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, self._start_drain, f"signal {sig.name}")
            except NotImplementedError:
                signal.signal(sig, lambda _s, _f, name=sig.name: self._start_drain(f"signal {name}"))

    async def _drain_watchdog_loop(self) -> None:
        """While not draining: sleep. Once draining: poll handler count; exit 0
        when all handlers have finished or after the timeout. Hard exit (not
        TaskGroup cancel) because janitor / heartbeat / progress server would
        otherwise keep the process alive — we want a clean docker SIGTERM-
        triggered exit so the container restart policy can take over."""
        while not self._draining:
            await asyncio.sleep(_DRAIN_POLL_INTERVAL_SEC)
        deadline = time.monotonic() + _DRAIN_WATCHDOG_TIMEOUT_SEC
        log.info("drain watchdog armed; %d handler(s) in flight", len(self._handlers))
        while time.monotonic() < deadline:
            if not self._handlers:
                log.info("drain complete — all handlers finished, exiting")
                os._exit(0)
            await asyncio.sleep(_DRAIN_POLL_INTERVAL_SEC)
        log.warning(
            "drain timeout (%ds) reached with %d handler(s) still in flight — forcing exit; "
            "lease sweeper will reclaim",
            _DRAIN_WATCHDOG_TIMEOUT_SEC,
            len(self._handlers),
        )
        os._exit(0)

    def _ensure_tls(self) -> str | None:
        """SATHOP_PUBLIC_URL https? ⇒ generate (or reuse) a self-signed cert
        covering its host and return the PEM for upload as ca_pem. Plain http
        ⇒ skip TLS entirely. Operator can pre-place a publicly-trusted cert
        at the same paths to bypass self-signing."""
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

    async def run(self) -> None:
        self._install_signal_handlers()
        ca_pem = self._ensure_tls()
        await self.client.register(
            WorkerRegister(
                worker_id=self.s.worker_id,
                version=__version__,
                capacity=self.s.capacity,
                public_url=self.s.public_url,
                ca_pem=ca_pem,
            )
        )
        log.info(
            "registered as %s v%s (downloader=%s, storage=%s, tls=%s)",
            self.s.worker_id,
            __version__,
            type(self.downloader).__name__,
            type(self.storage).__name__,
            "on" if ca_pem else "off",
        )

        async with asyncio.TaskGroup() as tg:
            tg.create_task(self._heartbeat_loop())
            tg.create_task(self._pipeline_loop())
            tg.create_task(self._janitor_loop())
            tg.create_task(self._backpressure_loop())
            tg.create_task(self._gc_loop())
            tg.create_task(self._drain_watchdog_loop())
            tg.create_task(self.progress.serve())
            if getattr(self.storage, "needs_static_server", False):
                tg.create_task(
                    storage.serve_static(
                        self.s.storage_root,
                        self.s.storage_port,
                        tls_cert=self.s.tls_cert_path if ca_pem else None,
                        tls_key=self.s.tls_key_path if ca_pem else None,
                    )
                )

    async def _heartbeat_loop(self) -> None:
        while True:
            try:
                du = psutil.disk_usage(str(self.s.storage_root))
                vm = psutil.virtual_memory()
                # 5 个 worker-side 阶段直接上报，跟 stage Counter 一一对应。
                # 全局阶段（待分配/待分发/待清理/已完成/待重试）orchestrator
                # 自己从 DB GranuleState 算，不在 heartbeat 里。
                resp = await self.client.heartbeat(
                    WorkerHeartbeat(
                        worker_id=self.s.worker_id,
                        version=__version__,
                        disk_used_gb=(du.total - du.free) / 1024**3,
                        disk_total_gb=du.total / 1024**3,
                        cpu_percent=psutil.cpu_percent(interval=None),
                        mem_percent=vm.percent,
                        queue_pending_download=self.stage["pending_download"],
                        queue_downloading=self.stage["downloading"],
                        queue_pending_processing=self.stage["pending_processing"],
                        queue_processing=self.stage["processing"],
                        queue_pending_upload=self.stage["pending_upload"],
                        queue_uploading=self.stage["uploading"],
                        paused=self._pause_lease or self._remote_pause,
                        active_granule_ids=list(self._handlers.keys()),
                    )
                )
                if resp.restart_requested:
                    # Operator clicked "重启". Don't os._exit here — instead
                    # flip the drain flag so the pipeline stops accepting
                    # new work and in-flight handlers finish naturally. The
                    # drain watchdog calls os._exit once handlers are done
                    # (or after timeout). Docker `restart: unless-stopped`
                    # then brings us back fresh.
                    self._start_drain("restart_requested via orchestrator")
                # Persistent operator-set pause flag. Distinct from the
                # backpressure-driven self._pause_lease so the operator can
                # resume even while the worker would still backpressure-pause
                # itself (and vice versa).
                if self._remote_pause != resp.pause_requested:
                    log.info(
                        "remote pause %s",
                        "engaged" if resp.pause_requested else "released",
                    )
                    self._remote_pause = resp.pause_requested
                if resp.gc_requested:
                    log.info("orchestrator requested cache GC — waking gc loop")
                    self._gc_event.set()
                # Cancel any handler whose lease the orchestrator no longer
                # credits to us — batch cancel, granule cancel, sweeper reclaim
                # all surface here. CancelledError propagates through _handle's
                # finally block (cleanup runs) and is naturally not caught by
                # `except Exception`, so no spurious failure report fires.
                for gid in resp.revoked_granule_ids:
                    t = self._handlers.get(gid)
                    if t is not None and not t.done():
                        log.info("[%s] cancelling handler — orchestrator revoked lease", gid)
                        t.cancel()
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
            except Exception as e:
                log.warning("heartbeat failed: %s", e)
            await asyncio.sleep(self.s.heartbeat_interval)

    async def _pipeline_loop(self) -> None:
        while True:
            # In-flight 上限 = process_sem + download_sem（流水线里两个真实的
            # 物理瓶颈：CPU 槽位 + 并发下载槽位）。多拉的 lease 只会卡在 sem
            # 后面排队，把"待下载/待处理"虚高，看不出谁真在干活，也让别的
            # worker 抢不到。要扩容就调 SATHOP_DOWNLOAD_CONCURRENCY 或
            # SATHOP_PROCESS_CONCURRENCY，没有第二个"管道深度"开关好误配。
            ceiling = min(
                self._effective_capacity,
                self.s.process_concurrency + self.s.download_concurrency,
            )
            free = ceiling - sum(self.stage.values())
            if free <= 0 or self._pause_lease or self._remote_pause or self._draining:
                await asyncio.sleep(self.s.lease_poll_interval)
                continue
            try:
                resp = await self.client.lease(LeaseRequest(worker_id=self.s.worker_id, capacity=free))
            except Exception as e:
                log.warning("lease failed: %s", e)
                await asyncio.sleep(self.s.lease_poll_interval)
                continue

            if not resp.items:
                await asyncio.sleep(self.s.lease_poll_interval)
                continue

            for item in resp.items:
                gid = item.granule_id
                t = asyncio.create_task(self._handle(item))
                self._handlers[gid] = t
                # Pop from the keyed map when done; .pop with a default keeps
                # this safe even if the key was already removed (e.g. by a
                # concurrent revoke handler).
                t.add_done_callback(lambda _t, _g=gid: self._handlers.pop(_g, None))

    async def _handle(self, item: LeaseItem) -> None:
        gid = item.granule_id
        work_dir = self.s.work_root / f"g-{safe_segment(gid)}-{int(time.time())}"
        work_dir.mkdir(parents=True, exist_ok=True)
        input_dir = work_dir / "input"
        input_dir.mkdir()
        nonce, progress_url = self.progress.issue(gid)

        # Track which stage counter we currently hold so the except-block
        # decrements only this granule's contribution. Decrementing every
        # non-zero counter would corrupt concurrent granules' queue display.
        current: str | None = None

        def _enter(stage: str) -> None:
            nonlocal current
            self.stage[stage] += 1
            current = stage

        def _exit() -> None:
            nonlocal current
            if current is not None:
                self.stage[current] -= 1
                current = None

        try:
            paths = await self._download_inputs(item, input_dir, _enter, _exit)
            handle, result = await self._process_inputs(item, paths, progress_url, _enter, _exit)

            if not result.ok:
                await self.client.report_failure(
                    ProcessFailure(
                        granule_id=gid,
                        worker_id=self.s.worker_id,
                        error=_processing_failure_message(result.stderr),
                        stdout_tail=_tail_or_none(result.stdout, _PROCESS_OUTPUT_TAIL_CHARS),
                        stderr_tail=_tail_or_none(result.stderr, _PROCESS_OUTPUT_TAIL_CHARS),
                        exit_code=result.exit_code,
                    )
                )
                log.warning("[%s] processing failed exit=%s", gid, result.exit_code)
                return

            await self._upload_outputs(item, handle, result.outputs, _enter, _exit)

        except LeaseRevoked:
            # Lease already gone from the DB row — failure report would 409
            # too, and the orchestrator's lease sweeper / reclaim path has
            # already moved the row back to PENDING for another worker.
            log.info("[%s] handler aborted (lease revoked)", gid)
        except Exception as e:
            log.exception("[%s] unhandled error", gid)
            try:
                # Carry exception type + tail of traceback so operators can
                # diagnose without ssh'ing into the worker. Orchestrator caps
                # the field at 2000 chars; the tail keeps the deepest frames.
                await self.client.report_failure(
                    ProcessFailure(
                        granule_id=gid,
                        worker_id=self.s.worker_id,
                        error=f"worker {type(e).__name__}: {e}\n\n{_traceback_tail(e)}",
                        exit_code=None,
                    )
                )
            except Exception:
                pass
        finally:
            _exit()
            self.progress.revoke(nonce)
            shutil.rmtree(work_dir, ignore_errors=True)

    async def _download_inputs(
        self,
        item: LeaseItem,
        input_dir: Path,
        enter_stage: _StageTransition,
        exit_stage: _StageExit,
    ) -> list[Path]:
        gid = item.granule_id
        # Lease wrote state=QUEUED. Hold pending_download until the download
        # semaphore frees up, then promote QUEUED→DOWNLOADING so the UI only
        # flags rows whose bytes are actually moving.
        enter_stage("pending_download")
        paths: list[Path] = []
        async with self._download_sem:
            exit_stage()
            enter_stage("downloading")
            await self._report_state(gid, GranuleState.DOWNLOADING)
            log.info("[%s] downloading %d input(s)", gid, len(item.inputs))
            for spec in item.inputs:
                dst = input_dir / spec.filename
                auth = _auth_for(item.credentials, spec.credential, gid)
                cb = self._make_download_progress_cb(gid, spec.filename)
                await self.downloader.fetch(spec.url, dst, auth=auth, progress_cb=cb)
                if spec.checksum:
                    await downloader.verify_sha256(dst, spec.checksum)
                paths.append(dst)
        exit_stage()
        await self._report_state(gid, GranuleState.DOWNLOADED)
        return paths

    async def _process_inputs(
        self,
        item: LeaseItem,
        paths: list[Path],
        progress_url: str,
        enter_stage: _StageTransition,
        exit_stage: _StageExit,
    ) -> tuple[bundle.BundleHandle, ProcessResult]:
        gid = item.granule_id
        # bundle.ensure 不占 process slot — 它是 first-time fetch + venv build，
        # 内部已有 per-ref lock，不会 CPU thrash。
        handle = await asyncio.to_thread(
            bundle.ensure,
            item.bundle_ref,
            self.s.bundle_cache,
            self.s.venv_cache,
            self.s.shared_cache,
            self.s.orchestrator_url,
            self.s.token,
        )
        # 等 CPU 槽位时 DB state 留在 DOWNLOADED（"待处理"）— 只有真正拿到
        # process_sem、即将开跑时才报 PROCESSING（"处理中"）。这样耗时统计
        # 里的 process 阶段反映实际处理时长，不把排队等待算进去。
        enter_stage("pending_processing")
        async with self._process_sem:
            exit_stage()
            enter_stage("processing")
            await self._report_state(gid, GranuleState.PROCESSING)
            # run_bundle is now async + uses asyncio.create_subprocess_shell;
            # CancelledError propagates straight in and `_kill_and_wait` tears
            # the child down before the exception bubbles up to _handle.
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
        exit_stage()
        return handle, result

    async def _upload_outputs(
        self,
        item: LeaseItem,
        handle: bundle.BundleHandle,
        outputs: list[Path],
        enter_stage: _StageTransition,
        exit_stage: _StageExit,
    ) -> None:
        gid = item.granule_id
        await self._report_state(gid, GranuleState.PROCESSED)
        # Hold pending_upload until the upload semaphore frees up. State stays
        # at PROCESSED on the orchestrator (no DB transition for "waiting on
        # upload sem") — the heartbeat counter is the sole signal so the
        # operator UI can tell "uploading" from "waiting to upload".
        enter_stage("pending_upload")
        async with self._upload_sem:
            exit_stage()
            enter_stage("uploading")
            # Capture instant we left the sem queue so the orchestrator can
            # split this window into upload_wait (sem) vs upload (work).
            upload_started_at = datetime.now(UTC)
            uploaded: list[UploadedObject] = []
            key_tpl = handle.manifest.outputs.get("object_key_template", "{stem}{ext}")
            for out in outputs:
                key = _render_key(key_tpl, out, item.meta)
                uploaded.append(self.storage.put(out, key))
            await self.client.report_upload(gid, self.s.worker_id, uploaded, upload_started_at)
        exit_stage()
        log.info("[%s] uploaded %d object(s)", gid, len(uploaded))

    async def _report_state(self, gid: str, state: GranuleState) -> None:
        """Phase report. 404/409 ⇒ orchestrator no longer recognises our
        lease, so we raise LeaseRevoked to abort the handler. Other errors
        (5xx, network blips) stay best-effort — the next phase boundary
        will retry the report."""
        try:
            await self.client.report_state(gid, self.s.worker_id, state)
        except httpx.HTTPStatusError as e:
            if e.response.status_code in (404, 409):
                log.warning(
                    "[%s] lease revoked while reporting %s (HTTP %d) — aborting handler",
                    gid,
                    state.value,
                    e.response.status_code,
                )
                raise LeaseRevoked from e
            log.warning("[%s] state report %s failed: %s", gid, state.value, e)
        except Exception as e:
            log.warning("[%s] state report %s failed: %s", gid, state.value, e)

    def _make_download_progress_cb(self, gid: str, filename: str) -> downloader.ProgressCb:
        """Per-input progress reporter: emit on ≥5% delta or ≥2s elapsed, plus a
        single forced emit at 100%. Caps upstream POSTs to ~0.5 Hz/file."""
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
            enough_time_passed = now - last_ts >= _DOWNLOAD_PROGRESS_MIN_INTERVAL_SECONDS
            enough_percent_passed = pct is not None and pct >= last_pct + _DOWNLOAD_PROGRESS_MIN_DELTA_PERCENT
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
                        detail=_download_progress_detail(downloaded, total),
                    ),
                )
            except Exception as e:
                log.debug("[%s] download progress emit failed: %s", gid, e)

        return cb

    async def _backpressure_loop(self) -> None:
        """Toggle `_pause_lease` around disk watermarks (hysteresis prevents flapping)."""
        while True:
            try:
                du = psutil.disk_usage(str(self.s.storage_root))
                used = (du.total - du.free) / du.total
                was = self._pause_lease
                if was and used < self.s.disk_resume_pct:
                    self._pause_lease = False
                elif not was and used > self.s.disk_pause_pct:
                    self._pause_lease = True
                if self._pause_lease != was:
                    log.warning(
                        "backpressure: disk=%.1f%% pause_lease=%s",
                        used * 100,
                        self._pause_lease,
                    )
            except Exception as e:
                log.warning("backpressure check failed: %s", e)
            await asyncio.sleep(self.s.backpressure_interval)

    async def _gc_loop(self) -> None:
        """Periodic local disk cleanup. Two jobs:
          1. Evict oldest cached venvs (+ matching bundle source dirs) once
             the venv cache exceeds SATHOP_VENV_CACHE_LIMIT_GB. ensure()
             refreshes the LRU sidecar on each lease, so an actively-used
             bundle can never be the oldest.
          2. Drop shared-file cache files whose name is no longer in the
             orchestrator registry — bundles can drift faster than the cache
             notices, and an orphan can shadow a re-uploaded name on the
             next ensure().

        SATHOP_GC_INTERVAL=0 disables the periodic firing but keeps the
        event-driven path: an operator-triggered GC (heartbeat reply
        gc_requested=True) still runs. Each job runs under asyncio.to_thread
        because they're stat()/rmtree-heavy."""
        periodic = self.s.gc_interval_sec > 0
        if not periodic:
            log.info("gc loop periodic disabled (SATHOP_GC_INTERVAL=0); event-driven GC still active")
        limit_bytes = int(self.s.venv_cache_limit_gb * 1024**3)
        # Fire once at startup so a worker that crashed mid-cycle (cache over
        # quota, orphans accumulated) catches up before its first lease.
        self._gc_event.set()
        while True:
            if periodic:
                try:
                    await asyncio.wait_for(self._gc_event.wait(), timeout=self.s.gc_interval_sec)
                except TimeoutError:
                    pass
            else:
                await self._gc_event.wait()
            self._gc_event.clear()
            try:
                r = await asyncio.to_thread(
                    bundle.prune_caches,
                    self.s.venv_cache,
                    self.s.bundle_cache,
                    limit_bytes,
                )
                if r["removed"]:
                    log.info(
                        "venv LRU evicted %d entr(ies), freed %.1f GB (now %.1f GB total)",
                        r["removed"],
                        r["freed_bytes"] / 1024**3,
                        r["total_bytes"] / 1024**3,
                    )
                shared_r = await asyncio.to_thread(
                    shared_sync.prune_orphans,
                    self.s.shared_cache,
                    self.s.orchestrator_url,
                    self.s.token,
                )
                if shared_r["removed"]:
                    log.info(
                        "shared orphan cleanup removed %d file(s), freed %.1f MB",
                        shared_r["removed"],
                        shared_r["freed_bytes"] / 1024**2,
                    )
            except Exception as e:
                log.warning("gc loop iteration failed: %s", e)

    async def _janitor_loop(self) -> None:
        while True:
            try:
                to_delete = await self.client.get_deletable(self.s.worker_id)
                for dg in to_delete:
                    for key in dg.object_keys:
                        self.storage.delete(key)
                    await self.client.confirm_deleted(dg)
                    if dg.object_keys:
                        log.info("[%s] deleted %d object(s) after ack", dg.granule_id, len(dg.object_keys))
            except Exception as e:
                log.warning("janitor failed: %s", e)
            await asyncio.sleep(30)


def _auth_for(creds: dict[str, Credential], name: str | None, gid: str) -> Credential | None:
    if not name:
        return None
    c = creds.get(name)
    if c is None:
        log.warning("[%s] credential %r not provided by batch", gid, name)
    return c


def _processing_failure_message(stderr: str) -> str:
    return (stderr or "no output")[-_PROCESSING_FAILURE_TAIL_CHARS:]


def _tail_or_none(s: str, n: int) -> str | None:
    """Return the last n chars of s, or None if s is empty/None. Used for
    optional `stdout_tail`/`stderr_tail` carried on ProcessFailure: an
    empty string would clear a previous attempt's tail in the DB and the
    UI would show 'empty stdout' instead of 'no stdout reported'."""
    if not s:
        return None
    return s if len(s) <= n else s[-n:]


def _traceback_tail(exc: Exception) -> str:
    return "".join(traceback.format_exception(exc))[-_WORKER_TRACEBACK_TAIL_CHARS:]


def _download_progress_detail(downloaded: int, total: int | None) -> str:
    downloaded_mb = downloaded / 1_000_000
    if total:
        return f"{downloaded_mb:.1f}/{total / 1_000_000:.1f} MB"
    return f"{downloaded_mb:.1f} MB"


def _render_key(template: str, out: Path, meta: dict) -> str:
    fields = {
        "stem": out.stem,
        "ext": out.suffix,
        "name": out.name,
        **{k: str(v) for k, v in meta.items()},
    }
    try:
        return template.format(**fields)
    except KeyError:
        return out.name


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    w = Worker(load())
    try:
        await w.run()
    finally:
        await w.client.aclose()


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
