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
import hashlib
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse

import httpx

from sathop.shared.protocol import Credential

_CHUNK = 256 * 1024

ProgressCb = Callable[[int, int | None], Awaitable[None]]


class ChecksumMismatch(RuntimeError):
    """A downloaded input's sha256 didn't match `InputSpec.checksum`."""


def _sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


async def verify_sha256(path: Path, expected: str) -> None:
    """Hash `path` off the event loop; raise ChecksumMismatch on disagreement.
    Comparison is case-insensitive — operators sometimes copy upper-case digests
    out of vendor metadata."""
    actual = await asyncio.to_thread(_sha256_of, path)
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
    return None, {}


class HttpDownloader:
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

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, read=600.0),
            follow_redirects=True,
            auth=x_auth,
        ) as c:
            async with c.stream("GET", url, headers=headers) as r:
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
        }
        if auth is not None:
            if auth.scheme == "basic" and auth.username and auth.password:
                options["http-user"] = auth.username
                options["http-passwd"] = auth.password
            elif auth.scheme == "bearer" and auth.token:
                options["header"] = [f"Authorization: Bearer {auth.token}"]

        dl = await asyncio.to_thread(self._api.add_uris, [url], options=options)
        try:
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
                await asyncio.sleep(2)
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


def load(aria2_rpc: str, aria2_secret: str) -> Downloader:
    if aria2_rpc:
        return Aria2Downloader(aria2_rpc, aria2_secret)
    return HttpDownloader()
