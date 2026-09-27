"""Receiver object download helpers."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import secrets
import time
from collections import deque
from collections.abc import AsyncIterator
from pathlib import Path

import httpx

from sathop.shared.hashing import sha256_file
from sathop.shared.http_range import parse_content_range

log = logging.getLogger("sathop.receiver")

CHUNK = 256 * 1024
THROUGHPUT_WINDOW_SEC = 60.0
SEGMENT_MAX_RETRIES = 3
SEGMENT_BACKOFF_BASE_SEC = 0.5


class PullStats:
    def __init__(self, window_sec: float = THROUGHPUT_WINDOW_SEC, clock=None) -> None:
        self.window = window_sec
        self.in_flight = 0
        self._clock = clock or time.monotonic
        self._events: deque[tuple[float, int]] = deque()

    def begin(self) -> None:
        self.in_flight += 1

    def end(self, bytes_pulled: int) -> None:
        self.in_flight -= 1
        if bytes_pulled > 0:
            self._events.append((self._clock(), bytes_pulled))

    def recent_bps(self) -> int:
        cutoff = self._clock() - self.window
        while self._events and self._events[0][0] < cutoff:
            self._events.popleft()
        if not self._events:
            return 0
        return int(sum(b for _, b in self._events) / self.window)


def tmp_for(dest: Path) -> Path:
    return dest.with_suffix(dest.suffix + f".part-{secrets.token_hex(4)}")


def byte_ranges(size: int, n: int) -> list[tuple[int, int]]:
    if size < 0:
        raise ValueError("size must be nonnegative")
    if size == 0:
        return []
    n = max(1, min(n, size))
    seg = size // n
    out: list[tuple[int, int]] = []
    for i in range(n):
        start = i * seg
        end = (i + 1) * seg - 1 if i < n - 1 else size - 1
        out.append((start, end))
    return out


class SegmentNotSupportedError(RuntimeError):
    pass


def is_transient_segment_error(e: BaseException) -> bool:
    if isinstance(e, SegmentNotSupportedError):
        return False
    if isinstance(e, httpx.RequestError):
        return True
    if isinstance(e, httpx.HTTPStatusError):
        return 500 <= e.response.status_code < 600
    if isinstance(e, RuntimeError):
        return True
    return False


async def stream_range(
    client: httpx.AsyncClient, url: str, pos: int, end: int, *, expected_size: int | None = None
) -> AsyncIterator[bytes]:
    headers = {"Range": f"bytes={pos}-{end}", "Accept-Encoding": "identity"}
    async with client.stream("GET", url, headers=headers) as r:
        r.raise_for_status()
        span = parse_content_range(r.headers.get("Content-Range", ""))
        if (
            r.status_code != 206
            or span is None
            or span.start != pos
            or span.end != end
            or (expected_size is not None and span.total != expected_size)
            or r.headers.get("Content-Encoding", "identity").lower() != "identity"
        ):
            raise SegmentNotSupportedError(f"invalid response for Range {pos}-{end}")
        async for chunk in r.aiter_bytes(CHUNK):
            if pos + len(chunk) > end + 1:
                raise SegmentNotSupportedError(f"response exceeds Range ending at {end}")
            yield chunk
            pos += len(chunk)


async def fetch_segment(
    client: httpx.AsyncClient, url: str, start: int, end: int, f, *, expected_size: int | None = None
) -> None:
    pos = start
    delay = SEGMENT_BACKOFF_BASE_SEC
    for attempt in range(SEGMENT_MAX_RETRIES + 1):
        try:
            async for chunk in stream_range(client, url, pos, end, expected_size=expected_size):
                # Keep the committed offset here, outside the response iterator:
                # a transport exception must not discard already-written progress.
                # No await between seek/write: siblings share this file handle.
                f.seek(pos)
                f.write(chunk)
                pos += len(chunk)
            if pos == end + 1:
                return
            raise RuntimeError(f"segment {start}-{end} stream ended at {pos}, short by {end + 1 - pos}")
        except SegmentNotSupportedError:
            raise
        except Exception as e:
            if attempt == SEGMENT_MAX_RETRIES or not is_transient_segment_error(e):
                raise
            log.warning(
                "segment %d-%d (got to %d) attempt %d/%d failed (%s) — retry in %.1fs",
                start,
                end,
                pos,
                attempt + 1,
                SEGMENT_MAX_RETRIES + 1,
                e,
                delay,
            )
            await asyncio.sleep(delay)
            delay *= 2


async def pull_segmented(
    client: httpx.AsyncClient,
    url: str,
    dest: Path,
    *,
    expected_size: int,
    segments: int,
) -> tuple[str, int]:
    ranges = byte_ranges(expected_size, segments)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = tmp_for(dest)
    try:
        with tmp.open("wb") as alloc:
            alloc.truncate(expected_size)
        with tmp.open("r+b", buffering=0) as f:
            tasks = [
                asyncio.create_task(fetch_segment(client, url, start, end, f, expected_size=expected_size))
                for start, end in ranges
            ]
            try:
                await asyncio.gather(*tasks)
            finally:
                # gather does not cancel siblings on failure. Drain them BEFORE
                # closing/removing the shared file, including on caller cancellation.
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
        hashing = asyncio.create_task(asyncio.to_thread(sha256_file, tmp))
        try:
            sha = await asyncio.shield(hashing)
        except asyncio.CancelledError:
            await hashing  # release the thread's file handle before Windows unlink
            raise
        size = tmp.stat().st_size
        tmp.replace(dest)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return sha, size


async def pull_single(client: httpx.AsyncClient, url: str, dest: Path) -> tuple[str, int]:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = tmp_for(dest)
    h = hashlib.sha256()
    size = 0
    try:
        async with client.stream("GET", url) as r:
            r.raise_for_status()
            with tmp.open("wb") as f:
                async for chunk in r.aiter_bytes(CHUNK):
                    f.write(chunk)
                    h.update(chunk)
                    size += len(chunk)
        tmp.replace(dest)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return h.hexdigest(), size
