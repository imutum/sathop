"""Segmented (parallel byte-range) download.

A single TCP flow's throughput is bounded by `window/RTT`; on cross-region
links that's tens of MB/s max. Splitting an object into N parallel range
requests fans the bandwidth across N flows. These tests cover the math
(byte-range arithmetic), the assembly (parallel range GETs → one file),
the fall-back (server returns 200 → single-stream), and the dispatch
threshold (small files skip the range machinery)."""

from __future__ import annotations

import asyncio
import hashlib
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from sathop.receiver.main import (
    Receiver,
    Settings,
    _byte_ranges,
    _pull_segmented,
    _SegmentNotSupportedError,
)
from sathop.shared.protocol import AckReport, PullItem


def _serve_range(payload: bytes, *, support_range: bool = True) -> tuple[ThreadingHTTPServer, int]:
    """Threaded HTTP server that honors `Range: bytes=start-end` (inclusive)
    when `support_range`, otherwise returns 200 with the full body — used to
    exercise the fall-back path."""

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a, **kw) -> None:
            pass

        def do_GET(self) -> None:
            rng = self.headers.get("Range") if support_range else None
            if rng:
                spec = rng.removeprefix("bytes=")
                start, end = (int(x) for x in spec.split("-"))
                body = payload[start : end + 1]
                self.send_response(206)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Content-Range", f"bytes {start}-{end}/{len(payload)}")
                self.end_headers()
                self.wfile.write(body)
                return
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            if support_range:
                self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
            self.wfile.write(payload)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, port


def _make_receiver(
    tmp_path: Path, *, segments: int = 4, threshold: int = 0
) -> tuple[Receiver, list[AckReport]]:
    s = Settings(
        receiver_id="r1",
        orchestrator_url="http://orch.test",
        token="t",
        storage_dir=tmp_path / "archive",
        poll_interval=1,
        concurrent_pulls=2,
        platform="linux",
        pull_segments=segments,
        pull_segment_min_bytes=threshold,
    )
    r = Receiver(s)
    captured: list[AckReport] = []

    class StubClient:
        async def ack(self, req: AckReport) -> None:
            captured.append(req)

        async def aclose(self) -> None:
            pass

    r.client = StubClient()  # type: ignore[assignment]
    return r, captured


# ─── byte-range arithmetic ────────────────────────────────────────────────


def test_byte_ranges_even_split():
    """100 / 4 = 25 each → [0,24] [25,49] [50,74] [75,99]."""
    assert _byte_ranges(100, 4) == [(0, 24), (25, 49), (50, 74), (75, 99)]


def test_byte_ranges_uneven_remainder_goes_to_last():
    """The last range absorbs whatever's left so the union always covers
    [0, size-1]; off-by-one here would silently truncate the file."""
    assert _byte_ranges(101, 4) == [(0, 24), (25, 49), (50, 74), (75, 100)]


def test_byte_ranges_clamps_when_n_exceeds_size():
    """3 bytes asked to split into 10 → 3 segments of 1 byte each. Without
    the clamp, you'd produce zero-length ranges that 416 on the server."""
    rs = _byte_ranges(3, 10)
    assert rs == [(0, 0), (1, 1), (2, 2)]


# ─── _pull_segmented direct ───────────────────────────────────────────────


async def test_segmented_assembles_full_payload(tmp_path):
    payload = bytes(range(256)) * 1000  # 256 KB of varied bytes
    srv, port = _serve_range(payload)
    r, _ = _make_receiver(tmp_path)
    try:
        dest = tmp_path / "out.bin"
        sha, size = await _pull_segmented(
            r._pull_client,
            f"http://127.0.0.1:{port}/x.bin",
            dest,
            expected_size=len(payload),
            segments=4,
        )
        assert dest.read_bytes() == payload
        assert size == len(payload)
        assert sha == hashlib.sha256(payload).hexdigest()
    finally:
        srv.shutdown()
        await r.aclose()


async def test_segmented_raises_when_server_ignores_range(tmp_path):
    """Server returns 200 to a Range request — _pull_segmented must surface
    a sentinel so the caller can fall back to single-stream rather than
    quietly assembling garbage from a body that wasn't a range."""
    payload = b"no-range-server" * 100
    srv, port = _serve_range(payload, support_range=False)
    r, _ = _make_receiver(tmp_path)
    try:
        dest = tmp_path / "out.bin"
        with pytest.raises(_SegmentNotSupportedError):
            await _pull_segmented(
                r._pull_client,
                f"http://127.0.0.1:{port}/x.bin",
                dest,
                expected_size=len(payload),
                segments=4,
            )
        # tmp file cleaned up; nothing renamed to dest.
        assert not dest.exists()
        assert list(dest.parent.glob("*.part-*")) == []
    finally:
        srv.shutdown()
        await r.aclose()


# ─── dispatch through _fetch_one ──────────────────────────────────────────


async def test_fetch_one_uses_segmented_above_threshold(tmp_path):
    """Above threshold + Range supported → segmented assembles correctly,
    sha matches, ack is success."""
    payload = b"abcdefghij" * 5_000  # 50 KB
    srv, port = _serve_range(payload)
    r, acks = _make_receiver(tmp_path, segments=4, threshold=10_000)
    try:
        item = PullItem(
            granule_id="g1",
            batch_id="b1",
            object_id=1,
            object_key="b1/g1/big.bin",
            presigned_url=f"http://127.0.0.1:{port}/x.bin",
            sha256=hashlib.sha256(payload).hexdigest(),
            size=len(payload),
        )
        await r._fetch_one(asyncio.Semaphore(1), item)
        assert (tmp_path / "archive" / "b1" / "g1" / "big.bin").read_bytes() == payload
        assert len(acks) == 1
        assert acks[0].success is True
    finally:
        srv.shutdown()
        await r.aclose()


async def test_fetch_one_skips_segmented_below_threshold(tmp_path):
    """Sub-threshold → single-stream only. Server doesn't even need range
    support; small files succeed regardless."""
    payload = b"tiny"
    srv, port = _serve_range(payload, support_range=False)
    r, acks = _make_receiver(tmp_path, segments=4, threshold=1_000_000)
    try:
        item = PullItem(
            granule_id="g1",
            batch_id="b1",
            object_id=1,
            object_key="b1/g1/tiny.bin",
            presigned_url=f"http://127.0.0.1:{port}/x.bin",
            sha256=hashlib.sha256(payload).hexdigest(),
            size=len(payload),
        )
        await r._fetch_one(asyncio.Semaphore(1), item)
        assert acks[0].success is True
    finally:
        srv.shutdown()
        await r.aclose()


async def test_fetch_one_falls_back_when_server_lacks_range(tmp_path):
    """Above threshold but server returns 200 — caller pivots to single-stream
    and the pull still succeeds. End-to-end safety net for any worker storage
    backend that doesn't honor Range (shouldn't happen for StaticFiles or
    MinIO presigned URLs, but the receiver shouldn't break if it ever does)."""
    payload = b"x" * 50_000
    srv, port = _serve_range(payload, support_range=False)
    r, acks = _make_receiver(tmp_path, segments=4, threshold=10_000)
    try:
        item = PullItem(
            granule_id="g1",
            batch_id="b1",
            object_id=1,
            object_key="b1/g1/no-range.bin",
            presigned_url=f"http://127.0.0.1:{port}/x.bin",
            sha256=hashlib.sha256(payload).hexdigest(),
            size=len(payload),
        )
        await r._fetch_one(asyncio.Semaphore(1), item)
        assert acks[0].success is True
        assert (tmp_path / "archive" / "b1" / "g1" / "no-range.bin").read_bytes() == payload
    finally:
        srv.shutdown()
        await r.aclose()


async def test_fetch_one_segments_disabled_uses_single_stream(tmp_path):
    """SATHOP_PULL_SEGMENTS=1 → never tries Range, even on huge files. Lets
    operators turn the feature off without downgrading."""
    payload = b"y" * 100_000
    srv, port = _serve_range(payload, support_range=False)
    r, acks = _make_receiver(tmp_path, segments=1, threshold=1)
    try:
        item = PullItem(
            granule_id="g1",
            batch_id="b1",
            object_id=1,
            object_key="b1/g1/disabled.bin",
            presigned_url=f"http://127.0.0.1:{port}/x.bin",
            sha256=hashlib.sha256(payload).hexdigest(),
            size=len(payload),
        )
        await r._fetch_one(asyncio.Semaphore(1), item)
        assert acks[0].success is True
    finally:
        srv.shutdown()
        await r.aclose()
