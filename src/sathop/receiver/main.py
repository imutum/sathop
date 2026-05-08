"""Receiver agent: polls orchestrator, pulls from worker presigned URLs."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import secrets
import shutil
import ssl
import sys
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

import httpx

from sathop import __version__
from sathop.shared.config import resolve_orch
from sathop.shared.http import make_orch_client
from sathop.shared.protocol import (
    AckReport,
    PullRequest,
    PullResponse,
    ReceiverHeartbeat,
    ReceiverHeartbeatResponse,
    ReceiverRegister,
)


class OrchestratorClient:
    def __init__(self, base_url: str, token: str, timeout: float = 30.0) -> None:
        self._client = make_orch_client(base_url, token, timeout)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def register(self, req: ReceiverRegister) -> None:
        (await self._client.post("/api/receivers/register", json=req.model_dump())).raise_for_status()

    async def heartbeat(self, req: ReceiverHeartbeat) -> ReceiverHeartbeatResponse:
        r = await self._client.post("/api/receivers/heartbeat", json=req.model_dump())
        r.raise_for_status()
        # Older orchestrators returned `{"ok": true}` only — Pydantic ignores
        # unknown keys and uses defaults for missing ones, so this also handles
        # the back-compat path (restart_requested defaults to False).
        return ReceiverHeartbeatResponse.model_validate(r.json())

    async def pull(self, req: PullRequest) -> PullResponse:
        r = await self._client.post("/api/receivers/pull", json=req.model_dump())
        r.raise_for_status()
        return PullResponse.model_validate(r.json())

    async def ack(self, req: AckReport) -> None:
        (await self._client.post("/api/receivers/ack", json=req.model_dump())).raise_for_status()


log = logging.getLogger("sathop.receiver")

_CHUNK = 256 * 1024
_THROUGHPUT_WINDOW_SEC = 60.0


class _PullStats:
    """In-process counters surfaced via heartbeat. `in_flight` is incremented
    for the duration of each `_fetch_one`; bytes from successful pulls land
    in a (ts, bytes) deque and `recent_bps()` returns the current window
    rate so the operator can see pull throughput in the UI."""

    def __init__(self, window_sec: float = _THROUGHPUT_WINDOW_SEC) -> None:
        self.window = window_sec
        self.in_flight = 0
        self._events: deque[tuple[float, int]] = deque()

    def begin(self) -> None:
        self.in_flight += 1

    def end(self, bytes_pulled: int) -> None:
        self.in_flight -= 1
        if bytes_pulled > 0:
            self._events.append((time.monotonic(), bytes_pulled))

    def recent_bps(self) -> int:
        cutoff = time.monotonic() - self.window
        while self._events and self._events[0][0] < cutoff:
            self._events.popleft()
        if not self._events:
            return 0
        return int(sum(b for _, b in self._events) / self.window)


@dataclass(frozen=True)
class Settings:
    receiver_id: str
    orchestrator_url: str
    token: str
    storage_dir: Path
    poll_interval: int
    concurrent_pulls: int
    platform: Literal["linux", "windows"]
    # False ⇒ skip TLS cert verification entirely (insecure escape hatch).
    # True (default) ⇒ verify; if `tls_trust_orch` is also True, the receiver
    # fetches the orchestrator-aggregated worker CA bundle at startup and on
    # SSL cert errors, and uses it as httpx verify=. False — system CAs only,
    # which fails for self-signed worker certs.
    tls_verify: bool = True
    # Default True: the orchestrator-managed bundle is the only sane trust
    # source for self-signed worker certs (no domain → no Let's Encrypt path).
    # If every worker is fronted by a publicly-trusted cert, the bundle endpoint
    # returns 204 and the receiver transparently falls back to system CAs, so
    # there's no downside to defaulting on. Set false to force system CAs only.
    tls_trust_orch: bool = True
    # Parallel byte-range download knobs. A single TCP flow is bandwidth-capped
    # by `window/RTT` (BDP); on a 50ms cross-region link that's tens of MB/s
    # max. Splitting one object into N parallel range requests fans the
    # bandwidth across N flows, which is what bumps throughput on big files.
    # Set pull_segments=1 to force single-stream. Files smaller than the
    # threshold skip range entirely — handshake+coordination overhead dominates.
    pull_segments: int = 4
    pull_segment_min_bytes: int = 8 * 1024 * 1024  # 8 MB


def _parse_bool(s: str, default: bool) -> bool:
    return s.strip().lower() not in ("0", "false", "no", "off") if s else default


def _is_cert_error(e: BaseException) -> bool:
    """Detect 'system trust said no, refresh might fix it' down the chain.
    httpx wraps ssl.SSLCertVerificationError twice: top-level httpx.ConnectError
    via __context__ (implicit chaining inside its `except:` block), then
    httpcore.ConnectError → ssl.SSLCertVerificationError via __context__ again.
    We follow both __cause__ and __context__ — checking only one misses it
    (this was the v0.3.3 bug that left receivers permanently stuck on cert
    error). Cycle guard via id() in case some library raises pathologically."""
    cur: BaseException | None = e
    seen: set[int] = set()
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        if isinstance(cur, ssl.SSLError):
            return True
        cur = cur.__cause__ or cur.__context__
    return False


def load() -> Settings:
    orchestrator_url, token = resolve_orch()
    return Settings(
        receiver_id=os.environ["SATHOP_RECEIVER_ID"],
        orchestrator_url=orchestrator_url,
        token=token,
        storage_dir=Path(os.environ["SATHOP_STORAGE_DIR"]),
        poll_interval=int(os.getenv("SATHOP_POLL_INTERVAL", "10")),
        concurrent_pulls=int(os.getenv("SATHOP_CONCURRENT_PULLS", "4")),
        platform=cast(Literal["linux", "windows"], "windows" if sys.platform == "win32" else "linux"),
        tls_verify=_parse_bool(os.getenv("SATHOP_TLS_VERIFY", ""), True),
        tls_trust_orch=_parse_bool(os.getenv("SATHOP_TLS_TRUST_ORCH", ""), True),
        pull_segments=int(os.getenv("SATHOP_PULL_SEGMENTS", "4")),
        pull_segment_min_bytes=int(os.getenv("SATHOP_PULL_SEGMENT_MIN_BYTES", str(8 * 1024 * 1024))),
    )


def _tmp_for(dest: Path) -> Path:
    """Per-pull random tmp name: a fixed `<dest>.part` would race when two
    tasks write the same path simultaneously (concurrent same-key offers,
    multi-receiver shared volume, restart-overlap with orphan workers). The
    first rename wins, the second would FileNotFoundError on src. Token +
    atomic rename = idempotent, last-writer-wins on dest."""
    return dest.with_suffix(dest.suffix + f".part-{secrets.token_hex(4)}")


def _sha256_path(path: Path) -> str:
    """Sequential-read SHA256. Used by the segmented path because segments
    arrive at disjoint offsets and SHA256 is not homomorphic — you can't
    combine partial digests, you have to feed the bytes in order."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(_CHUNK), b""):
            h.update(block)
    return h.hexdigest()


def _byte_ranges(size: int, n: int) -> list[tuple[int, int]]:
    """Even split of [0, size-1] into n inclusive byte ranges. Last range
    absorbs the remainder so the union always covers the whole file. When
    n > size we clamp to size (no zero-length ranges that would 416)."""
    n = max(1, min(n, size))
    seg = size // n
    out: list[tuple[int, int]] = []
    for i in range(n):
        start = i * seg
        end = (i + 1) * seg - 1 if i < n - 1 else size - 1
        out.append((start, end))
    return out


class _SegmentNotSupportedError(RuntimeError):
    """Server returned 200 instead of 206 — Range was ignored. Caller should
    fall back to single-stream rather than retrying segmented (a server that
    didn't honor Range once won't honor it next time)."""


async def _fetch_segment(
    client: httpx.AsyncClient,
    url: str,
    start: int,
    end: int,
    f,
) -> None:
    """Stream one byte range into `f` at the segment's offset. `f` is shared
    by all segments — single-event-loop atomicity makes seek+write safe:
    asyncio coroutines don't preempt mid-sync-call, so no other coroutine can
    re-seek between our seek and write. Disjoint ranges = no byte collision."""
    pos = start
    async with client.stream("GET", url, headers={"Range": f"bytes={start}-{end}"}) as r:
        if r.status_code == 200:
            raise _SegmentNotSupportedError(f"server ignored Range {start}-{end}, returned 200")
        r.raise_for_status()
        async for chunk in r.aiter_bytes(_CHUNK):
            f.seek(pos)
            f.write(chunk)
            pos += len(chunk)
    if pos != end + 1:
        raise RuntimeError(f"segment {start}-{end} short read: got {pos - start}/{end - start + 1}")


async def _pull_segmented(
    client: httpx.AsyncClient,
    url: str,
    dest: Path,
    *,
    expected_size: int,
    segments: int,
) -> tuple[str, int]:
    """N-way parallel byte-range download. Pre-allocates tmp at full size,
    fans out N coroutines each fetching its slice and writing at its offset.
    SHA256 is computed by a final sequential read (segments can't compute
    incrementally — they don't see bytes in order)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = _tmp_for(dest)
    # Pre-allocate so segment writers can seek into any offset without
    # tripping over short-file-then-extend races.
    with tmp.open("wb") as alloc:
        alloc.truncate(expected_size)
    ranges = _byte_ranges(expected_size, segments)
    try:
        # buffering=0 → raw FileIO. seek+write becomes a single OS-level pair
        # with no Python-side buffer state mixing across coroutines.
        with tmp.open("r+b", buffering=0) as f:
            await asyncio.gather(*(_fetch_segment(client, url, s, e, f) for s, e in ranges))
        sha = await asyncio.to_thread(_sha256_path, tmp)
        size = tmp.stat().st_size
        tmp.replace(dest)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return sha, size


async def _pull_single(client: httpx.AsyncClient, url: str, dest: Path) -> tuple[str, int]:
    """Single-stream path — used for sub-threshold files and as the fallback
    when a server doesn't honor Range. Hashes incrementally on the fly."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = _tmp_for(dest)
    h = hashlib.sha256()
    size = 0
    try:
        async with client.stream("GET", url) as r:
            r.raise_for_status()
            with tmp.open("wb") as f:
                async for chunk in r.aiter_bytes(_CHUNK):
                    f.write(chunk)
                    h.update(chunk)
                    size += len(chunk)
        tmp.replace(dest)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return h.hexdigest(), size


class Receiver:
    def __init__(self, s: Settings) -> None:
        self.s = s
        self.client = OrchestratorClient(s.orchestrator_url, s.token)
        self.stats = _PullStats()
        s.storage_dir.mkdir(parents=True, exist_ok=True)
        # Resolved at run() start: bool (True/False) or path str pointing at an
        # orchestrator-aggregated CA bundle. Passed verbatim to httpx verify=.
        self._verify: bool | str = s.tls_verify
        # Shared httpx client across all pulls — without this, every object
        # paid one TCP+TLS handshake (the old per-pull `async with AsyncClient`
        # killed the connection pool every time). Kept-alive connections keep
        # TLS sessions warm and let the OS skip TCP slow-start on each new
        # range request, which is doubly important for segmented downloads.
        self._pull_client: httpx.AsyncClient = self._build_pull_client()

    def _build_pull_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, read=600.0),
            follow_redirects=True,
            verify=self._verify,
            # Plenty of headroom: 32 concurrent_pulls × 8 segments = 256
            # potential simultaneous connections; 200/50 keeps the pool from
            # serializing range requests through a single keep-alive socket.
            limits=httpx.Limits(max_connections=200, max_keepalive_connections=50),
        )

    async def aclose(self) -> None:
        await self._pull_client.aclose()

    async def _resolve_trust(self) -> None:
        """Initial trust setup at run() start. Operator opt-outs short-circuit
        before any orch call so a misconfigured/empty bundle never blocks boot."""
        if not self.s.tls_verify:
            log.warning("TLS verification disabled (SATHOP_TLS_VERIFY=false)")
            return
        if not self.s.tls_trust_orch:
            return
        await self._refresh_trust()

    async def _refresh_trust(self) -> None:
        """Refetch the orchestrator-aggregated worker-CA bundle and rewire
        self._verify. Called at startup and lazily on per-pull SSL cert errors
        (a worker that registered AFTER us isn't in the startup snapshot, so
        first pull from it would fail; one refresh + retry covers that case)."""
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
        # SSL context is bound at AsyncClient construction — to pick up the
        # newly-added CA we must rebuild the client. Existing kept-alive
        # connections to already-trusted workers are dropped, but they reopen
        # cheaply on the next pull.
        old = self._pull_client
        self._pull_client = self._build_pull_client()
        await old.aclose()
        log.info("trusting orchestrator-managed CA bundle at %s (%d bytes)", bundle_path, len(r.text))

    async def run(self) -> None:
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
                    # Operator clicked "重启" — exit hard so docker
                    # `restart: unless-stopped` brings us back fresh. In-flight
                    # pulls drop their `.part-<token>` tmp; re-offer happens
                    # naturally when the orch hasn't seen an ack yet.
                    log.warning("restart requested via orchestrator — exiting")
                    os._exit(0)
            except Exception as e:
                log.warning("heartbeat failed: %s", e)
            await asyncio.sleep(self.s.poll_interval)

    async def _pull_loop(self) -> None:
        sem = asyncio.Semaphore(self.s.concurrent_pulls)
        while True:
            try:
                resp = await self.client.pull(
                    PullRequest(
                        receiver_id=self.s.receiver_id,
                        limit=self.s.concurrent_pulls * 4,
                    )
                )
            except Exception as e:
                log.warning("pull list failed: %s", e)
                await asyncio.sleep(self.s.poll_interval)
                continue

            if not resp.items:
                await asyncio.sleep(self.s.poll_interval)
                continue

            await asyncio.gather(*(self._fetch_one(sem, it) for it in resp.items))

    async def _pull_object(self, url: str, dest: Path, expected_size: int) -> tuple[str, int]:
        """Dispatch: segmented for big files where the server supports Range,
        single-stream otherwise. The PullItem.size field already tells us the
        expected size, so we don't pay a HEAD round-trip just to plan ranges."""
        if self.s.pull_segments > 1 and expected_size >= self.s.pull_segment_min_bytes and expected_size > 0:
            try:
                return await _pull_segmented(
                    self._pull_client,
                    url,
                    dest,
                    expected_size=expected_size,
                    segments=self.s.pull_segments,
                )
            except _SegmentNotSupportedError as e:
                log.info("range not supported (%s) — falling back to single-stream", e)
        return await _pull_single(self._pull_client, url, dest)

    async def _pull_with_trust_retry(self, url: str, dest: Path, expected_size: int) -> tuple[str, int]:
        """Pull with one CA-bundle refresh on SSL cert error. Covers the case
        where a worker registered after our startup snapshot — first pull fails,
        refresh adds its CA, retry succeeds. No retry for non-cert errors (the
        normal pull-failures counter still escalates those)."""
        try:
            return await self._pull_object(url, dest, expected_size)
        except Exception as e:
            if not (_is_cert_error(e) and self.s.tls_trust_orch and self.s.tls_verify):
                raise
            log.warning("pull SSL cert error (%s) — refreshing CA bundle and retrying once", e)
            await self._refresh_trust()
            return await self._pull_object(url, dest, expected_size)

    async def _fetch_one(self, sem: asyncio.Semaphore, item) -> None:
        async with sem:
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
                            error=None
                            if ok
                            else f"sha/size mismatch {sha}/{size} vs {item.sha256}/{item.size}",
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


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    r = Receiver(load())
    try:
        await r.run()
    finally:
        await r.client.aclose()
        await r.aclose()


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
