"""Segmented (parallel byte-range) download.

A single TCP flow's throughput is bounded by `window/RTT`; on cross-region
links that's tens of MB/s max. Splitting an object into N parallel range
requests fans the bandwidth across N flows. These tests cover the math
(byte-range arithmetic), the assembly (parallel range GETs → one file),
the fall-back (server returns 200 → single-stream), and the dispatch
threshold (small files skip the range machinery). Plus per-segment
retry-with-resume: a transient blip mid-segment refetches only the
missing tail, not the whole segment."""

from __future__ import annotations

import hashlib
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from sathop.receiver import puller as recv_mod
from sathop.receiver.config import Settings
from sathop.receiver.puller import (
    SegmentNotSupportedError as _SegmentNotSupportedError,
)
from sathop.receiver.puller import (
    byte_ranges as _byte_ranges,
)
from sathop.receiver.puller import (
    pull_segmented as _pull_segmented,
)
from sathop.receiver.runtime import Receiver
from sathop.shared.protocol import AckReport, PullItem


@pytest.fixture(autouse=True)
def _no_retry_backoff(monkeypatch):
    """Squash retry sleeps so retry-loop tests don't take seconds. The
    backoff schedule (0.5/1/2s) is correct in production but irrelevant
    to test correctness."""
    monkeypatch.setattr(recv_mod, "SEGMENT_BACKOFF_BASE_SEC", 0.0)


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
    # Single-fetch tests with no flusher running: the ack report sits in the
    # buffer queue — assert on it directly (see test_receiver_main).
    return r, r._acks._q


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


# ─── dispatch through _fetch_one_inner ───────────────────────────────────


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
        await r._fetch_one_inner(item)
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
        await r._fetch_one_inner(item)
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
        await r._fetch_one_inner(item)
        assert acks[0].success is True
        assert (tmp_path / "archive" / "b1" / "g1" / "no-range.bin").read_bytes() == payload
    finally:
        srv.shutdown()
        await r.aclose()


# ─── per-segment retry with bytes-aware resume ───────────────────────────


def _serve_with_failure_injection(
    payload: bytes,
    *,
    fail_first_request_for_start: int | None = None,
    fail_after_bytes: int = 0,
    fail_persistently_for_start: int | None = None,
    fail_with_status: int | None = None,
):
    """Stateful range server. Knobs let one test inject:

    - `fail_first_request_for_start`: the first GET whose Range starts at
      this offset hangs up after `fail_after_bytes` bytes; subsequent
      requests for the same offset succeed.
    - `fail_persistently_for_start`: every GET to this start offset hangs
      up after `fail_after_bytes` bytes. Used to verify retries eventually
      give up.
    - `fail_with_status`: every GET to `fail_persistently_for_start`
      returns this status code instead. Used to verify 4xx aborts immediately.

    All other requests honor Range normally."""
    state = {"first_failed": False, "request_counts": {}}
    lock = threading.Lock()

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a, **kw) -> None:
            pass

        def do_GET(self) -> None:
            rng = self.headers.get("Range") or ""
            spec = rng.removeprefix("bytes=")
            try:
                start, end = (int(x) for x in spec.split("-"))
            except ValueError:
                self.send_response(400)
                self.end_headers()
                return
            with lock:
                state["request_counts"][start] = state["request_counts"].get(start, 0) + 1
                attempt_for_start = state["request_counts"][start]

            should_fail_now = False
            fail_status_code: int | None = None

            if start == fail_persistently_for_start:
                if fail_with_status is not None:
                    fail_status_code = fail_with_status
                else:
                    should_fail_now = True

            if start == fail_first_request_for_start and attempt_for_start == 1:
                should_fail_now = True

            if fail_status_code is not None:
                self.send_response(fail_status_code)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return

            body = payload[start : end + 1]
            self.send_response(206)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Range", f"bytes {start}-{end}/{len(payload)}")
            self.end_headers()
            if should_fail_now:
                # Send a partial prefix, then forcibly close the connection so
                # the client raises a transport error mid-stream.
                self.wfile.write(body[:fail_after_bytes])
                self.wfile.flush()
                self.connection.close()
                return
            self.wfile.write(body)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, port, state


async def test_segmented_retries_only_missing_bytes_after_transient_failure(tmp_path):
    """Segment 0's first request hangs up after 100 bytes, second succeeds.
    The retry must Range-request only the bytes we didn't get yet (not
    re-download the 100 we already have), AND the final file must be
    byte-perfect — proving the resumed write hit the right offset."""
    payload = bytes(range(256)) * 4  # 1024 bytes of varied content
    # 4 segments → starts at 0, 256, 512, 768. Fail on segment-0's first req,
    # after the first 100 of its 256 bytes.
    srv, port, state = _serve_with_failure_injection(
        payload, fail_first_request_for_start=0, fail_after_bytes=100
    )
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
        # File correctness: bytes-aware resume must land the second-attempt
        # bytes at offset 100, not offset 0 (which would clobber what we
        # already wrote and shift the rest).
        assert dest.read_bytes() == payload
        assert size == len(payload)
        assert sha == hashlib.sha256(payload).hexdigest()
        # Retry actually happened — segment-0's start saw 2 requests total.
        assert state["request_counts"][0] == 2
        # Other segments untouched by retry — exactly 1 request each.
        assert state["request_counts"][256] == 1
        assert state["request_counts"][512] == 1
        assert state["request_counts"][768] == 1
    finally:
        srv.shutdown()
        await r.aclose()


async def test_segmented_gives_up_after_max_retries(tmp_path):
    """Segment 0 fails persistently — all 4 attempts (1 + 3 retries) hang up
    mid-stream. The whole pull raises and tmp file is cleaned up."""
    payload = bytes(range(256)) * 4
    srv, port, state = _serve_with_failure_injection(
        payload, fail_persistently_for_start=0, fail_after_bytes=10
    )
    r, _ = _make_receiver(tmp_path)
    try:
        dest = tmp_path / "out.bin"
        with pytest.raises(Exception):  # any non-_SegmentNotSupportedError
            await _pull_segmented(
                r._pull_client,
                f"http://127.0.0.1:{port}/x.bin",
                dest,
                expected_size=len(payload),
                segments=4,
            )
        assert state["request_counts"][0] == recv_mod.SEGMENT_MAX_RETRIES + 1
        # Tmp cleaned up; no leftover .part-* files.
        assert not dest.exists()
        assert list(dest.parent.glob("*.part-*")) == []
    finally:
        srv.shutdown()
        await r.aclose()


async def test_segmented_does_not_retry_on_4xx(tmp_path):
    """403 (or any 4xx that's not 416-special) is permanent — auth issue, file
    deleted, etc. Retrying just wastes budget. We verify exactly 1 request
    was made for the failing segment."""
    payload = bytes(range(256)) * 4
    srv, port, state = _serve_with_failure_injection(
        payload, fail_persistently_for_start=512, fail_with_status=403
    )
    r, _ = _make_receiver(tmp_path)
    try:
        dest = tmp_path / "out.bin"
        with pytest.raises(Exception):
            await _pull_segmented(
                r._pull_client,
                f"http://127.0.0.1:{port}/x.bin",
                dest,
                expected_size=len(payload),
                segments=4,
            )
        # Failed segment hit exactly once — no retry on 403.
        assert state["request_counts"][512] == 1
    finally:
        srv.shutdown()
        await r.aclose()


# ─── original tests continue ──────────────────────────────────────────────


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
        await r._fetch_one_inner(item)
        assert acks[0].success is True
    finally:
        srv.shutdown()
        await r.aclose()
