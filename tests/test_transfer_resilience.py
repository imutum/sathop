"""Failures must never publish incomplete files or leave sibling writes running."""

from __future__ import annotations

import asyncio
import io

import httpx
import pytest

from sathop.receiver import puller
from sathop.worker.downloader import HttpDownloader


async def test_range_failure_drains_siblings_before_closing_file(tmp_path, monkeypatch):
    sibling_started = asyncio.Event()
    sibling_stopped = asyncio.Event()
    closed_during_cleanup = []

    async def segment(client, url, start, end, f, **kwargs):
        if start == 0:
            await sibling_started.wait()
            raise puller.SegmentNotSupportedError("no range support")
        sibling_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            closed_during_cleanup.append(f.closed)
            sibling_stopped.set()

    monkeypatch.setattr(puller, "fetch_segment", segment)
    async with httpx.AsyncClient() as client:
        with pytest.raises(puller.SegmentNotSupportedError):
            await puller.pull_segmented(
                client, "https://test/file", tmp_path / "out", expected_size=8, segments=2
            )
    assert sibling_stopped.is_set()
    assert closed_during_cleanup == [False]
    assert not list(tmp_path.glob("*.part-*"))


async def test_segment_resumes_from_last_written_chunk(monkeypatch):
    monkeypatch.setattr(puller, "SEGMENT_BACKOFF_BASE_SEC", 0)
    monkeypatch.setattr(puller, "CHUNK", 4)
    ranges = []

    class InterruptedStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"abcd"
            raise httpx.ReadError("connection lost")

    def handler(request):
        ranges.append(request.headers["Range"])
        if len(ranges) == 1:
            return httpx.Response(206, headers={"Content-Range": "bytes 0-7/8"}, stream=InterruptedStream())
        return httpx.Response(206, headers={"Content-Range": "bytes 4-7/8"}, content=b"efgh")

    f = io.BytesIO()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await puller.fetch_segment(client, "https://test/file", 0, 7, f)
    assert ranges == ["bytes=0-7", "bytes=4-7"]
    assert f.getvalue() == b"abcdefgh"


@pytest.mark.parametrize("content_range", [None, "bytes 1-4/8", "bytes 0-3/3", "garbage"])
async def test_segment_rejects_invalid_range_before_writing(content_range):
    headers = {"Content-Range": content_range} if content_range else {}
    f = io.BytesIO(b"original")
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(206, headers=headers, content=b"xxxx"))
    ) as client:
        with pytest.raises(puller.SegmentNotSupportedError):
            await puller.fetch_segment(client, "https://test/file", 0, 3, f)
    assert f.getvalue() == b"original"


async def test_segment_never_overwrites_neighboring_range():
    f = io.BytesIO(b"original")
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(206, headers={"Content-Range": "bytes 0-3/8"}, content=b"too-long")
        )
    ) as client:
        with pytest.raises(puller.SegmentNotSupportedError):
            await puller.fetch_segment(client, "https://test/file", 0, 3, f)
    assert f.getvalue()[4:] == b"inal"


@pytest.mark.parametrize("restart_status", [200, 206])
async def test_worker_restarts_stale_partial_after_416(tmp_path, restart_status):
    dest = tmp_path / "out"
    dest.with_suffix(".part").write_bytes(b"stale-too-long")
    ranges = []

    def handler(request):
        ranges.append(request.headers.get("Range"))
        if len(ranges) == 1:
            return httpx.Response(416, headers={"Content-Range": "bytes */3"})
        return httpx.Response(restart_status, headers={"Content-Range": "bytes 0-2/3"}, content=b"new")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        downloader = HttpDownloader()
        downloader._client = client
        assert await downloader.fetch("https://test/file", dest) == 3
    assert dest.read_bytes() == b"new"
    assert ranges == ["bytes=14-", None]


async def test_worker_range_ignored_resets_progress(tmp_path):
    dest = tmp_path / "out"
    dest.with_suffix(".part").write_bytes(b"old")
    progress = []

    async def cb(done, total):
        progress.append((done, total))

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"new-data"))
    ) as client:
        downloader = HttpDownloader()
        downloader._client = client
        await downloader.fetch("https://test/file", dest, progress_cb=cb)
    assert progress and all(done <= total for done, total in progress)
    assert dest.read_bytes() == b"new-data"


async def test_worker_rejects_misaligned_resume(tmp_path):
    dest = tmp_path / "out"
    dest.with_suffix(".part").write_bytes(b"abc")
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(206, headers={"Content-Range": "bytes 1-3/4"}, content=b"bcd")
        )
    ) as client:
        downloader = HttpDownloader()
        downloader._client = client
        with pytest.raises(httpx.HTTPError):
            await downloader.fetch("https://test/file", dest)
    assert not dest.exists()
    assert dest.with_suffix(".part").read_bytes() == b"abc"


async def test_worker_valid_resume_uses_whole_object_total(tmp_path):
    dest = tmp_path / "out"
    dest.with_suffix(".part").write_bytes(b"abc")

    def handler(request):
        assert request.headers["Range"] == "bytes=3-"
        assert request.headers["Accept-Encoding"] == "identity"
        return httpx.Response(206, headers={"Content-Range": "bytes 3-7/8"}, content=b"defgh")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        downloader = HttpDownloader()
        downloader._client = client
        assert await downloader.fetch("https://test/file", dest) == 8
    assert dest.read_bytes() == b"abcdefgh"


async def test_worker_complete_partial_416_requires_matching_total(tmp_path):
    dest = tmp_path / "out"
    dest.with_suffix(".part").write_bytes(b"abc")
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(416, headers={"Content-Range": "bytes */3"}))
    ) as client:
        downloader = HttpDownloader()
        downloader._client = client
        assert await downloader.fetch("https://test/file", dest) == 3
    assert dest.read_bytes() == b"abc"


async def test_worker_416_without_partial_does_not_create_output(tmp_path):
    dest = tmp_path / "out"
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(416, headers={"Content-Range": "bytes */3"}))
    ) as client:
        downloader = HttpDownloader()
        downloader._client = client
        with pytest.raises(httpx.HTTPStatusError):
            await downloader.fetch("https://test/file", dest)
    assert not dest.exists()


async def test_worker_short_resume_keeps_partial_for_next_attempt(tmp_path):
    dest = tmp_path / "out"
    dest.with_suffix(".part").write_bytes(b"abc")
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(206, headers={"Content-Range": "bytes 3-7/8"}, content=b"de")
        )
    ) as client:
        downloader = HttpDownloader()
        downloader._client = client
        with pytest.raises(httpx.RemoteProtocolError):
            await downloader.fetch("https://test/file", dest)
    assert not dest.exists()
    assert dest.with_suffix(".part").read_bytes() == b"abcde"


async def test_segmented_cancellation_drains_all_writers(tmp_path, monkeypatch):
    started = asyncio.Event()
    active = 0
    stopped = 0

    async def segment(client, url, start, end, f, **kwargs):
        nonlocal active, stopped
        active += 1
        if active == 3:
            started.set()
        try:
            await asyncio.Event().wait()
        finally:
            assert not f.closed
            stopped += 1

    monkeypatch.setattr(puller, "fetch_segment", segment)
    async with httpx.AsyncClient() as client:
        task = asyncio.create_task(
            puller.pull_segmented(client, "https://test/file", tmp_path / "out", expected_size=9, segments=3)
        )
        await asyncio.wait_for(started.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert stopped == 3
    assert list(tmp_path.iterdir()) == []


async def test_segmented_rejects_object_size_drift(tmp_path):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(206, headers={"Content-Range": "bytes 0-3/9"}, content=b"abcd")
        )
    ) as client:
        with pytest.raises(puller.SegmentNotSupportedError):
            await puller.pull_segmented(
                client, "https://test/file", tmp_path / "out", expected_size=4, segments=1
            )
    assert list(tmp_path.iterdir()) == []
