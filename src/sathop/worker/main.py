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
import shutil
import time
import traceback
from collections import Counter
from collections.abc import Callable
from pathlib import Path

import psutil

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

from . import bundle, downloader, storage
from .agent import OrchestratorClient
from .config import Settings, load
from .processor import ProcessResult, run_bundle
from .progress import ProgressServer

log = logging.getLogger("sathop.worker")

_PROCESSING_FAILURE_TAIL_CHARS = 2000
_WORKER_TRACEBACK_TAIL_CHARS = 1500
_DOWNLOAD_PROGRESS_MIN_INTERVAL_SECONDS = 2.0
_DOWNLOAD_PROGRESS_MIN_DELTA_PERCENT = 5.0
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
        self._pause_lease = False
        self._download_sem = asyncio.Semaphore(s.download_concurrency)
        # Strong refs for handler tasks: asyncio.create_task() only weak-refs
        # tasks, so without this set Python's GC may collect a long-running
        # _handle() mid-flight and silently cancel it. See asyncio docs.
        self._handlers: set[asyncio.Task[None]] = set()
        # Updated from heartbeat replies; orchestrator may clamp below s.capacity.
        self._effective_capacity = s.capacity
        self.progress = ProgressServer(self.client, port=s.progress_port)
        for p in (s.work_root, s.bundle_cache, s.venv_cache, s.shared_cache, s.storage_root):
            p.mkdir(parents=True, exist_ok=True)

    async def run(self) -> None:
        await self.client.register(
            WorkerRegister(
                worker_id=self.s.worker_id,
                version="0.1.0",
                capacity=self.s.capacity,
                public_url=self.s.public_url,
            )
        )
        log.info(
            "registered as %s (downloader=%s, storage=%s)",
            self.s.worker_id,
            type(self.downloader).__name__,
            type(self.storage).__name__,
        )

        async with asyncio.TaskGroup() as tg:
            tg.create_task(self._heartbeat_loop())
            tg.create_task(self._pipeline_loop())
            tg.create_task(self._janitor_loop())
            tg.create_task(self._backpressure_loop())
            tg.create_task(self.progress.serve())
            if getattr(self.storage, "needs_static_server", False):
                tg.create_task(storage.serve_static(self.s.storage_root, self.s.storage_port))

    async def _heartbeat_loop(self) -> None:
        while True:
            try:
                du = psutil.disk_usage(str(self.s.storage_root))
                vm = psutil.virtual_memory()
                resp = await self.client.heartbeat(
                    WorkerHeartbeat(
                        worker_id=self.s.worker_id,
                        disk_used_gb=(du.total - du.free) / 1024**3,
                        disk_total_gb=du.total / 1024**3,
                        cpu_percent=psutil.cpu_percent(interval=None),
                        mem_percent=vm.percent,
                        queue_queued=self.stage["queued"],
                        queue_downloading=self.stage["downloading"],
                        queue_processing=self.stage["processing"],
                        queue_uploading=self.stage["uploading"],
                        paused=self._pause_lease,
                    )
                )
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
            free = self._effective_capacity - sum(self.stage.values())
            if free <= 0 or self._pause_lease:
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
                t = asyncio.create_task(self._handle(item))
                self._handlers.add(t)
                t.add_done_callback(self._handlers.discard)

    async def _handle(self, item: LeaseItem) -> None:
        gid = item.granule_id
        work_dir = self.s.work_root / f"g-{gid}-{int(time.time())}"
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
                        exit_code=result.exit_code,
                    )
                )
                log.warning("[%s] processing failed exit=%s", gid, result.exit_code)
                return

            await self._upload_outputs(item, handle, result.outputs, _enter, _exit)

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
        # Lease wrote state=QUEUED. Hold that bucket until the download
        # semaphore frees up, then promote QUEUED→DOWNLOADING so the UI only
        # flags rows whose bytes are actually moving.
        enter_stage("queued")
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
        enter_stage("processing")
        await self._report_state(gid, GranuleState.PROCESSING)
        handle = await asyncio.to_thread(
            bundle.ensure,
            item.bundle_ref,
            self.s.bundle_cache,
            self.s.venv_cache,
            self.s.shared_cache,
            self.s.orchestrator_url,
            self.s.token,
        )
        result = await asyncio.to_thread(
            run_bundle,
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
        enter_stage("uploading")
        uploaded: list[UploadedObject] = []
        key_tpl = handle.manifest.outputs.get("object_key_template", "{stem}{ext}")
        for out in outputs:
            key = _render_key(key_tpl, out, item.meta)
            uploaded.append(self.storage.put(out, key))
        await self.client.report_upload(gid, self.s.worker_id, uploaded)
        exit_stage()
        log.info("[%s] uploaded %d object(s)", gid, len(uploaded))

    async def _report_state(self, gid: str, state: GranuleState) -> None:
        """Best-effort phase report. A failure here only delays UI state until
        the next successful report (or upload), so we log and continue rather
        than aborting the granule."""
        try:
            await self.client.report_state(gid, self.s.worker_id, state)
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
