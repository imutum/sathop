from __future__ import annotations

import asyncio
import logging
import shutil
import ssl
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from sathop import __version__
from sathop.shared import agent_lifecycle
from sathop.shared.http import make_orch_client
from sathop.shared.periodic import run_periodic
from sathop.shared.protocol import AckReport, PullItem, PullRequest, ReceiverHeartbeat, ReceiverRegister

from . import puller
from .ack_buffer import AckBuffer
from .agent import OrchestratorClient
from .config import Settings
from .health import HealthServer

log = logging.getLogger("sathop.receiver")

# Matches deploy/receiver/docker-compose.yml::stop_grace_period — drift between
# the two means docker SIGKILLs us mid-drain (too low) or wastes restart time
# (too high). Keep them in lockstep.
DRAIN_WATCHDOG_TIMEOUT_SEC = 30


def _exc_chain(e: BaseException) -> list[BaseException]:
    out: list[BaseException] = []
    cur: BaseException | None = e
    seen: set[int] = set()
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        out.append(cur)
        cur = cur.__cause__ or cur.__context__
    return out


def is_cert_verify_error(e: BaseException) -> bool:
    """True only for certificate *verification* failures (untrusted / wrong-host
    cert) — the one case a trust refresh can fix. Transport-level SSLErrors
    (SSLEOFError, connection reset mid-handshake) are NOT cert errors: refreshing
    trust can't fix them, and misclassifying them drove futile refetch churn."""
    return any(isinstance(c, ssl.SSLCertVerificationError) for c in _exc_chain(e))


def describe_exc(e: BaseException) -> str:
    """Full cause/context chain as 'Type(msg) <- Type(msg)'. str(e) alone is
    routinely empty for transport resets (ConnectionResetError, SSLEOFError),
    which left the real failure invisible in receiver logs and orchestrator acks."""
    return " <- ".join(f"{type(c).__name__}({c})" for c in _exc_chain(e))


@dataclass(frozen=True)
class PullOutcome:
    """The result of fetching one object. Drives a single ack call site.

    `pulled_bytes` is 0 on any failure so stats only count verified bytes.
    `sha` is empty on transport failure (no bytes to hash); for sha/size
    mismatch it's the digest we computed so the orchestrator can correlate.
    """

    success: bool
    sha: str
    pulled_bytes: int
    error: str | None
    log_kind: str  # "ok" | "mismatch" | "transport"

    @classmethod
    def ok(cls, sha: str, size: int) -> PullOutcome:
        return cls(success=True, sha=sha, pulled_bytes=size, error=None, log_kind="ok")

    @classmethod
    def mismatch(cls, item: PullItem, sha: str, size: int) -> PullOutcome:
        return cls(
            success=False,
            sha=sha,
            pulled_bytes=0,
            error=f"sha/size mismatch {sha}/{size} vs {item.sha256}/{item.size}",
            log_kind="mismatch",
        )

    @classmethod
    def transport_error(cls, e: BaseException) -> PullOutcome:
        return cls(success=False, sha="", pulled_bytes=0, error=describe_exc(e), log_kind="transport")


class Receiver:
    def __init__(self, s: Settings) -> None:
        self.s = s
        self.client = OrchestratorClient(s.orchestrator_url, s.token)
        self.stats = puller.PullStats()
        s.storage_dir.mkdir(parents=True, exist_ok=True)
        self._trust_lock = asyncio.Lock()
        self._last_trust_refresh = 0.0
        self._ssl_ctx = self._init_ssl_context()
        self._pull_client: httpx.AsyncClient = self._build_pull_client()
        self._health = HealthServer(s.health_port)
        self._acks = AckBuffer(self.client)
        self._draining = False
        self._inflight: set[int] = set()

    def _start_drain(self, reason: str) -> None:
        if self._draining:
            return
        self._draining = True
        log.warning("entering graceful drain (%s) — will exit after in-flight pulls complete", reason)

    def _install_signal_handlers(self) -> None:
        agent_lifecycle.install_signal_handlers(self._start_drain)

    async def _drain_watchdog_loop(self) -> None:
        await agent_lifecycle.drain_watchdog_loop(
            lambda: self._draining,
            self._inflight,
            log,
            timeout_sec=DRAIN_WATCHDOG_TIMEOUT_SEC,
            active_noun="pull",
            reclaim_message="orchestrator will re-offer un-acked objects",
        )

    def _init_ssl_context(self) -> ssl.SSLContext | None:
        """One mutable trust store backing the shared pull client. Worker CAs are
        *added* to it in place on refresh (load_verify_locations), so updating
        trust never rebuilds or closes the client out from under in-flight pulls.
        Built only when we both verify and source trust from the orchestrator;
        plain bool verify (True/False) is left to httpx."""
        if self.s.tls_verify and self.s.tls_trust_orch:
            return ssl.create_default_context()
        return None

    def _build_pull_client(self) -> httpx.AsyncClient:
        verify: bool | ssl.SSLContext = self._ssl_ctx if self._ssl_ctx is not None else self.s.tls_verify
        return httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, read=600.0),
            follow_redirects=True,
            verify=verify,
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
        """Add the orchestrator's worker-CA bundle to the live trust store in
        place. Concurrent cert errors coalesce: whoever wins the lock fetches
        once; tasks whose request predates that fetch find their trust already
        current and return. In-flight pulls on the shared client are never
        disturbed — new connections pick up the added CAs at handshake."""
        if self._ssl_ctx is None:
            return
        requested_at = time.monotonic()
        async with self._trust_lock:
            if self._last_trust_refresh > requested_at:
                return
            bundle_path = self.s.storage_dir / ".orch-ca-bundle.pem"
            # System CAs for this one fetch — we bootstrap against the
            # orchestrator's own endpoint, not a worker's self-signed cert.
            async with make_orch_client(self.s.orchestrator_url, self.s.token, timeout=15.0) as c:
                r = await c.get("/api/receivers/ca-bundle")
            self._last_trust_refresh = time.monotonic()
            if r.status_code == 204:
                log.warning("orchestrator has no worker CAs — using system CAs")
                return
            r.raise_for_status()
            bundle_path.parent.mkdir(parents=True, exist_ok=True)
            bundle_path.write_text(r.text, encoding="utf-8")
            self._ssl_ctx.load_verify_locations(cafile=str(bundle_path))
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

        def create_tasks(tg: asyncio.TaskGroup) -> None:
            tg.create_task(self._heartbeat_loop())
            tg.create_task(self._acks.loop())
            tg.create_task(self._pull_loop())
            tg.create_task(self._drain_watchdog_loop())
            tg.create_task(self._health.serve())

        await agent_lifecycle.run_agent(create_tasks, log=log)

    async def _heartbeat_loop(self) -> None:
        await run_periodic(
            self._heartbeat_once,
            interval=self.s.poll_interval,
            log=log,
            name="heartbeat",
        )

    async def _heartbeat_once(self) -> None:
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

    async def _pull_loop(self) -> None:
        queue: asyncio.Queue[PullItem] = asyncio.Queue(maxsize=self.s.concurrent_pulls * 2)
        async with asyncio.TaskGroup() as tg:
            tg.create_task(self._pull_producer(queue))
            for _ in range(self.s.concurrent_pulls):
                tg.create_task(self._pull_worker(queue))

    async def _pull_producer(self, queue: asyncio.Queue[PullItem]) -> None:
        while True:
            if self._draining:
                await asyncio.sleep(agent_lifecycle.DRAIN_POLL_INTERVAL_SEC)
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
            if not (is_cert_verify_error(e) and self.s.tls_trust_orch and self.s.tls_verify):
                raise
            log.warning(
                "pull cert-verify error (%s) — refreshing CA bundle and retrying once", describe_exc(e)
            )
            await self._refresh_trust()
            return await self._pull_object(url, dest, expected_size)

    async def _fetch_one_inner(self, item: PullItem) -> None:
        self.stats.begin()
        outcome = await self._pull_one(item)
        self._ack_outcome(item, outcome)  # non-blocking enqueue
        self._log_outcome(item, outcome)
        self.stats.end(outcome.pulled_bytes)

    async def _pull_one(self, item: PullItem) -> PullOutcome:
        dest = self.s.storage_dir / item.object_key
        try:
            sha, size = await self._pull_with_trust_retry(item.presigned_url, dest, item.size)
        except Exception as e:
            return PullOutcome.transport_error(e)
        if sha == item.sha256 and size == item.size:
            return PullOutcome.ok(sha, size)
        dest.unlink(missing_ok=True)
        return PullOutcome.mismatch(item, sha, size)

    def _ack_outcome(self, item: PullItem, outcome: PullOutcome) -> None:
        # Buffered (non-blocking): the AckBuffer coalesces per-object reports into
        # batched POSTs and retries on a flush blip. Ack stays best-effort — a
        # dropped ack just re-offers the object on the next pull, converging after
        # at most max_pull_failures rounds — so this never blocks the pull worker.
        self._acks.enqueue(
            AckReport(
                receiver_id=self.s.receiver_id,
                object_id=item.object_id,
                sha256=outcome.sha,
                success=outcome.success,
                error=outcome.error,
            )
        )

    @staticmethod
    def _log_outcome(item: PullItem, outcome: PullOutcome) -> None:
        if outcome.log_kind == "ok":
            log.info("pulled %s (%d bytes)", item.object_key, outcome.pulled_bytes)
        elif outcome.log_kind == "mismatch":
            log.error("verify failed %s", item.object_key)
        else:
            log.warning("pull %s failed: %s", item.object_key, outcome.error)
