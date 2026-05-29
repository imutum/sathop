"""Download backends.

Two implementations:
  - HttpDownloader:   httpx-based, resumable, MVP default.
  - Aria2Downloader:  aria2c RPC — multi-connection, bigger files, proper resume.

Selection is env-driven: `SATHOP_ARIA2_RPC` non-empty → aria2c; else httpx.
Both accept the same `(url, dest, auth, progress_cb)` signature; auth carries a
`Credential` which each backend translates to its native form (BasicAuth vs.
bearer header). `progress_cb`, if provided, is awaited each time bytes arrive
with `(downloaded_so_far, total_or_None)`; throttling is the caller's job.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse

import httpx

from sathop.shared.hashing import sha256_file
from sathop.shared.protocol import Credential

log = logging.getLogger("sathop.worker.downloader")

_CHUNK = 256 * 1024

ProgressCb = Callable[[int, int | None], Awaitable[None]]


def progress_detail(downloaded: int, total: int | None) -> str:
    """Human-readable byte-progress label for the orchestrator progress feed:
    `"5.0/10.0 MB"` when the server reported Content-Length, `"5.0 MB"` when
    not. Decimal MB (not MiB) because end-users expect download UIs to round
    that way."""
    downloaded_mb = downloaded / 1_000_000
    if total:
        return f"{downloaded_mb:.1f}/{total / 1_000_000:.1f} MB"
    return f"{downloaded_mb:.1f} MB"


class ChecksumMismatch(RuntimeError):
    """A downloaded input's sha256 didn't match `InputSpec.checksum`."""


def _warn_incomplete_credential(auth: Credential) -> None:
    """Operators sometimes mis-key a Credential (scheme=basic but no
    password, scheme=bearer but no token). Without this warning the
    download proceeds unauthenticated and the server's 401/403 is hard
    to trace back to the bad credential entry."""
    log.warning(
        "credential %r has scheme=%s but required field(s) missing — request will be unauthenticated",
        auth.name,
        auth.scheme,
    )


async def verify_sha256(path: Path, expected: str) -> None:
    """Hash `path` off the event loop; raise ChecksumMismatch on disagreement.
    Comparison is case-insensitive — operators sometimes copy upper-case digests
    out of vendor metadata."""
    actual = await asyncio.to_thread(sha256_file, path)
    if actual.lower() != expected.lower():
        raise ChecksumMismatch(
            f"sha256 mismatch on {path.name}: expected {expected.lower()[:16]}…, got {actual[:16]}…"
        )


class Downloader(Protocol):
    """Pluggable download backend. `set_global_bandwidth_bps(0)` means unlimited.
    Backends without bandwidth support (httpx) implement it as a no-op."""

    async def fetch(
        self,
        url: str,
        dest: Path,
        auth: Credential | None = None,
        progress_cb: ProgressCb | None = None,
    ) -> int: ...
    async def set_global_bandwidth_bps(self, bps: int) -> None: ...
    async def aclose(self) -> None: ...


def _safe_int(s: str | None) -> int | None:
    if s is None:
        return None
    try:
        return int(s)
    except ValueError:
        return None


def _httpx_auth_and_headers(
    auth: Credential | None,
) -> tuple[httpx.Auth | None, dict[str, str]]:
    if auth is None:
        return None, {}
    if auth.scheme == "basic" and auth.username and auth.password:
        return httpx.BasicAuth(auth.username, auth.password), {}
    if auth.scheme == "bearer" and auth.token:
        return None, {"Authorization": f"Bearer {auth.token}"}
    _warn_incomplete_credential(auth)
    return None, {}


def _aria2_auth_options(auth: Credential | None) -> dict[str, object]:
    """aria2 sibling of `_httpx_auth_and_headers`. Adding a new scheme means
    editing both translators in lockstep — keep the branch order identical."""
    if auth is None:
        return {}
    if auth.scheme == "basic" and auth.username and auth.password:
        return {"http-user": auth.username, "http-passwd": auth.password}
    if auth.scheme == "bearer" and auth.token:
        return {"header": [f"Authorization: Bearer {auth.token}"]}
    _warn_incomplete_credential(auth)
    return {}


class HttpDownloader:
    """One long-lived AsyncClient reused across every fetch. Remote-sensing
    archives are small (~3 MB) and latency-bound: a fresh client per file
    re-pays the TLS handshake (and any auth redirect) each time, which dwarfs
    the ~0.1s of actual transfer. A pooled, keep-alive client lets repeat
    fetches from the same host skip the handshake and approach the link rate.
    Per-file credentials ride on each request (`auth=`), so one client serves
    granules carrying different credentials."""

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        # Lazy + race-free: construction is fully synchronous, so two
        # concurrent first-fetches on the single event loop can't interleave
        # between the None check and the assignment. The pool is unbounded
        # because the worker's download semaphore is the real concurrency cap;
        # a 60s keepalive expiry keeps host connections warm across the
        # lease-poll gap so consecutive granules reuse them.
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0, read=30.0),
                follow_redirects=True,
                limits=httpx.Limits(
                    max_connections=None,
                    max_keepalive_connections=None,
                    keepalive_expiry=60.0,
                ),
            )
        return self._client

    async def fetch(
        self,
        url: str,
        dest: Path,
        auth: Credential | None = None,
        progress_cb: ProgressCb | None = None,
    ) -> int:
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".part")
        existing = tmp.stat().st_size if tmp.exists() else 0

        x_auth, extra_headers = _httpx_auth_and_headers(auth)
        headers = dict(extra_headers)
        if existing:
            headers["Range"] = f"bytes={existing}-"

        # read=30s is per-chunk inter-byte timeout, not total download cap —
        # as long as the server keeps delivering bytes the timer resets each
        # chunk, so big files still finish. 30s without any byte ⇒ fail fast,
        # orchestrator re-leases instead of holding the download semaphore.
        # `auth` rides on the request (not the shared client) so per-file
        # credentials don't leak across granules; None ⇒ no auth.
        async with self._get_client().stream("GET", url, headers=headers, auth=x_auth) as r:
            if r.status_code == 416:
                tmp.replace(dest)
                final_size = dest.stat().st_size
                if progress_cb:
                    await progress_cb(final_size, final_size)
                return final_size
            r.raise_for_status()
            resumed = r.status_code == 206
            body_len = _safe_int(r.headers.get("Content-Length"))
            total = (existing + body_len) if (resumed and body_len is not None) else body_len
            downloaded = existing
            mode = "ab" if resumed else "wb"
            with tmp.open(mode) as f:
                async for chunk in r.aiter_bytes(_CHUNK):
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_cb:
                        await progress_cb(downloaded, total)
        tmp.replace(dest)
        final_size = dest.stat().st_size
        if progress_cb:
            await progress_cb(final_size, total or final_size)
        return final_size

    async def set_global_bandwidth_bps(self, bps: int) -> None:
        return None  # httpx has no built-in rate limit

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


class Aria2Downloader:
    def __init__(self, rpc_url: str, secret: str) -> None:
        import aria2p

        p = urlparse(rpc_url)
        self._api = aria2p.API(
            aria2p.Client(
                host=f"{p.scheme}://{p.hostname}",
                port=p.port or 6800,
                secret=secret,
            )
        )

    async def fetch(
        self,
        url: str,
        dest: Path,
        auth: Credential | None = None,
        progress_cb: ProgressCb | None = None,
    ) -> int:
        dest.parent.mkdir(parents=True, exist_ok=True)
        options: dict[str, object] = {
            "dir": str(dest.parent),
            "out": dest.name,
            "continue": "true",
            "allow-overwrite": "true",
            "auto-file-renaming": "false",
            "max-connection-per-server": "4",
            "split": "4",
            "retry-wait": "5",
            "max-tries": "3",
            **_aria2_auth_options(auth),
        }

        dl = await asyncio.to_thread(self._api.add_uris, [url], options=options)
        try:
            # Ramp 0.25→0.5→1→2s so small files don't pay the full 2s poll
            # latency while large files still settle into the cheap cadence.
            poll = 0.25
            while True:
                await asyncio.to_thread(dl.update)
                if progress_cb:
                    total = dl.total_length if dl.total_length else None
                    await progress_cb(dl.completed_length, total)
                if dl.is_complete:
                    return dl.completed_length
                if dl.status in ("error", "removed"):
                    msg = dl.error_message or dl.status
                    raise RuntimeError(f"aria2 download failed: {msg}")
                await asyncio.sleep(poll)
                poll = min(poll * 2, 2.0)
        finally:
            try:
                await asyncio.to_thread(dl.purge)
            except Exception:
                pass

    async def set_global_bandwidth_bps(self, bps: int) -> None:
        await asyncio.to_thread(
            self._api.client.call,
            "aria2.changeGlobalOption",
            [{"max-overall-download-limit": str(max(0, bps))}],
        )

    async def aclose(self) -> None:
        return None  # aria2p talks over its own RPC socket; nothing to close here


def load(aria2_rpc: str, aria2_secret: str) -> Downloader:
    if aria2_rpc:
        return Aria2Downloader(aria2_rpc, aria2_secret)
    return HttpDownloader()
