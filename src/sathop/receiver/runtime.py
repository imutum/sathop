"""Receiver runtime orchestration."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import signal
import ssl
import time
from pathlib import Path

import httpx

from sathop import __version__
from sathop.shared.protocol import AckReport, PullItem, PullRequest, ReceiverHeartbeat, ReceiverRegister

from . import puller
from .agent import OrchestratorClient
from .config import Settings
from .health import HealthServer

log = logging.getLogger("sathop.receiver")

DRAIN_WATCHDOG_TIMEOUT_SEC = 30
DRAIN_POLL_INTERVAL_SEC = 1.0


def is_cert_error(e: BaseException) -> bool:
    cur: BaseException | None = e
    seen: set[int] = set()
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        if isinstance(cur, ssl.SSLError):
            return True
        cur = cur.__cause__ or cur.__context__
    return False


class Receiver:
    def __init__(self, s: Settings) -> None:
        self.s = s
        self.client = OrchestratorClient(s.orchestrator_url, s.token)
        self.stats = puller.PullStats()
        s.storage_dir.mkdir(parents=True, exist_ok=True)
        self._verify: bool | str = s.tls_verify
        self._pull_client: httpx.AsyncClient = self._build_pull_client()
        self._health = HealthServer(s.health_port)
        self._draining = False
        self._inflight: set[int] = set()

    def _start_drain(self, reason: str) -> None:
        if self._draining:
            return
        self._draining = True
        log.warning("entering graceful drain (%s) — will exit after in-flight pulls complete", reason)

    def _install_signal_handlers(self) -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, self._start_drain, f"signal {sig.name}")
            except NotImplementedError:
                signal.signal(sig, lambda _s, _f, name=sig.name: self._start_drain(f"signal {name}"))

    async def _drain_watchdog_loop(self) -> None:
        while not self._draining:
            await asyncio.sleep(DRAIN_POLL_INTERVAL_SEC)
        deadline = time.monotonic() + DRAIN_WATCHDOG_TIMEOUT_SEC
        log.info("drain watchdog armed; %d pull(s) in flight", len(self._inflight))
        while time.monotonic() < deadline:
            if not self._inflight:
                log.info("drain complete — all pulls finished, exiting")
                os._exit(0)
            await asyncio.sleep(DRAIN_POLL_INTERVAL_SEC)
        log.warning(
            "drain timeout (%ds) reached with %d pull(s) still in flight — forcing exit; "
            "orchestrator will re-offer un-acked objects",
            DRAIN_WATCHDOG_TIMEOUT_SEC,
            len(self._inflight),
        )
        os._exit(0)

    def _build_pull_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, read=600.0),
            follow_redirects=True,
            verify=self._verify,
            limits=httpx.Limits(max_connections=300, max_keepalive_connections=100),
        )

    async def aclose(self) -> None:
        await self._pull_client.aclose()

    async def _resolve_trust(self) -> None:
        if not self.s.tls_verify:
            log.warning("TLS verification disabled (SATHOP_TLS_VERIFY=false)")
            return
        if not self.s.tls_trust_orch:
            return
        await self._refresh_trust()

    async def _refresh_trust(self) -> None:
        bundle_path = self.s.storage_dir / ".orch-ca-bundle.pem"
        url = f"{self.s.orchestrator_url}/api/receivers/ca-bundle"
        async with httpx.AsyncClient(timeout=15.0, headers={"Authorization": f"Bearer {self.s.token}"}) as c:
            r = await c.get(url)
        if r.status_code == 204:
            log.warning("orchestrator has no worker CAs — using system CAs")
            return
        r.raise_for_status()
        bundle_path.parent.mkdir(parents=True, exist_ok=True)
        bundle_path.write_text(r.text, encoding="utf-8")
        self._verify = str(bundle_path)
        old = self._pull_client
        self._pull_client = self._build_pull_client()
        await old.aclose()
        log.info("trusting orchestrator-managed CA bundle at %s (%d bytes)", bundle_path, len(r.text))

    async def run(self) -> None:
        self._install_signal_handlers()
        await self._resolve_trust()
        await self.client.register(
            ReceiverRegister(
                receiver_id=self.s.receiver_id,
                version=__version__,
                platform=self.s.platform,
            )
        )
        log.info("registered as %s v%s (%s)", self.s.receiver_id, __version__, self.s.platform)

        async with asyncio.TaskGroup() as tg:
            tg.create_task(self._heartbeat_loop())
            tg.create_task(self._pull_loop())
            tg.create_task(self._drain_watchdog_loop())
            tg.create_task(self._health.serve())

    async def _heartbeat_loop(self) -> None:
        while True:
            try:
                free = shutil.disk_usage(str(self.s.storage_dir)).free / 1024**3
                resp = await self.client.heartbeat(
                    ReceiverHeartbeat(
                        receiver_id=self.s.receiver_id,
                        version=__version__,
                        disk_free_gb=free,
                        queue_pulling=self.stats.in_flight,
                        recent_pull_bps=self.stats.recent_bps(),
                    )
                )
                if resp.restart_requested:
                    self._start_drain("restart_requested via orchestrator")
            except Exception as e:
                log.warning("heartbeat failed: %s", e)
            await asyncio.sleep(self.s.poll_interval)

    async def _pull_loop(self) -> None:
        queue: asyncio.Queue[PullItem] = asyncio.Queue(maxsize=self.s.concurrent_pulls * 2)
        async with asyncio.TaskGroup() as tg:
            tg.create_task(self._pull_producer(queue))
            for _ in range(self.s.concurrent_pulls):
                tg.create_task(self._pull_worker(queue))

    async def _pull_producer(self, queue: asyncio.Queue[PullItem]) -> None:
        while True:
            if self._draining:
                await asyncio.sleep(DRAIN_POLL_INTERVAL_SEC)
                continue
            try:
                resp = await self.client.pull(
                    PullRequest(
                        receiver_id=self.s.receiver_id,
                        limit=self.s.concurrent_pulls * 2,
                    )
                )
            except Exception as e:
                log.warning("pull list failed: %s", e)
                await asyncio.sleep(self.s.poll_interval)
                continue

            if not resp.items:
                await asyncio.sleep(self.s.poll_interval)
                continue

            for item in resp.items:
                if item.object_id in self._inflight:
                    continue
                self._inflight.add(item.object_id)
                await queue.put(item)

    async def _pull_worker(self, queue: asyncio.Queue[PullItem]) -> None:
        while True:
            item = await queue.get()
            try:
                await self._fetch_one_inner(item)
            finally:
                self._inflight.discard(item.object_id)
                queue.task_done()

    async def _pull_object(self, url: str, dest: Path, expected_size: int) -> tuple[str, int]:
        if self.s.pull_segments > 1 and expected_size >= self.s.pull_segment_min_bytes and expected_size > 0:
            try:
                return await puller.pull_segmented(
                    self._pull_client,
                    url,
                    dest,
                    expected_size=expected_size,
                    segments=self.s.pull_segments,
                )
            except puller.SegmentNotSupportedError as e:
                log.info("range not supported (%s) — falling back to single-stream", e)
        return await puller.pull_single(self._pull_client, url, dest)

    async def _pull_with_trust_retry(self, url: str, dest: Path, expected_size: int) -> tuple[str, int]:
        try:
            return await self._pull_object(url, dest, expected_size)
        except Exception as e:
            if not (is_cert_error(e) and self.s.tls_trust_orch and self.s.tls_verify):
                raise
            log.warning("pull SSL cert error (%s) — refreshing CA bundle and retrying once", e)
            await self._refresh_trust()
            return await self._pull_object(url, dest, expected_size)

    async def _fetch_one_inner(self, item: PullItem) -> None:
        self.stats.begin()
        pulled_bytes = 0
        try:
            dest = self.s.storage_dir / item.object_key
            try:
                sha, size = await self._pull_with_trust_retry(item.presigned_url, dest, item.size)
                ok = sha == item.sha256 and size == item.size
                if ok:
                    pulled_bytes = size
                else:
                    dest.unlink(missing_ok=True)
                await self.client.ack(
                    AckReport(
                        receiver_id=self.s.receiver_id,
                        object_id=item.object_id,
                        sha256=sha,
                        success=ok,
                        error=None if ok else f"sha/size mismatch {sha}/{size} vs {item.sha256}/{item.size}",
                    )
                )
                if ok:
                    log.info("pulled %s (%d bytes)", item.object_key, size)
                else:
                    log.error("verify failed %s", item.object_key)
            except Exception as e:
                log.warning("pull %s failed: %s", item.object_key, e)
                try:
                    await self.client.ack(
                        AckReport(
                            receiver_id=self.s.receiver_id,
                            object_id=item.object_id,
                            sha256="",
                            success=False,
                            error=str(e),
                        )
                    )
                except Exception:
                    pass
        finally:
            self.stats.end(pulled_bytes)

    async def _fetch_one(self, sem: asyncio.Semaphore, item: PullItem) -> None:
        async with sem:
            await self._fetch_one_inner(item)
