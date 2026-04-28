"""Receiver heartbeat now reports `queue_pulling` (in-flight pull count) and
`recent_pull_bps` (rolling-window throughput). Operators can finally tell idle
receivers from busy ones in the UI."""

from __future__ import annotations

import asyncio
import hashlib
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sathop.orchestrator import db as orch_db
from sathop.orchestrator.config import settings
from sathop.orchestrator.db import Receiver
from sathop.orchestrator.main import app
from sathop.receiver.main import Receiver as ReceiverAgent
from sathop.receiver.main import Settings as RecvSettings
from sathop.receiver.main import _PullStats
from sathop.shared.protocol import AckReport, PullItem

# ─── _PullStats unit tests ────────────────────────────────────────────────


def test_pullstats_starts_idle():
    s = _PullStats()
    assert s.in_flight == 0
    assert s.recent_bps() == 0


def test_pullstats_tracks_in_flight():
    s = _PullStats()
    s.begin()
    s.begin()
    assert s.in_flight == 2
    s.end(0)
    assert s.in_flight == 1


def test_pullstats_recent_bps_average_over_window():
    """recent_bps == total_bytes_in_window / window_sec — rate, not raw sum."""
    s = _PullStats(window_sec=10.0)
    s.begin()
    s.end(1000)
    s.begin()
    s.end(2000)
    # 3000 bytes / 10s window = 300 bps
    assert s.recent_bps() == 300


def test_pullstats_evicts_events_outside_window(monkeypatch):
    s = _PullStats(window_sec=5.0)

    fake_now = [1000.0]
    monkeypatch.setattr("sathop.receiver.main.time", type("T", (), {"monotonic": lambda: fake_now[0]}))

    s.begin()
    s.end(500)  # at t=1000
    fake_now[0] = 1010.0  # 10s later — outside 5s window
    s.begin()
    s.end(2500)  # at t=1010

    # Only the recent 2500 counts; 2500/5 = 500 bps
    assert s.recent_bps() == 500


def test_pullstats_zero_bytes_does_not_pollute_window():
    """Failed pulls call end(0) — they bump in_flight back down but mustn't
    show as 0-byte throughput entries (they'd accelerate eviction of real
    samples and skew the rate)."""
    s = _PullStats(window_sec=10.0)
    for _ in range(100):
        s.begin()
        s.end(0)
    assert s.recent_bps() == 0
    assert len(s._events) == 0


# ─── _fetch_one wiring: stats are credited correctly ──────────────────────


def _serve(payload: bytes) -> tuple[HTTPServer, int]:
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a, **kw):
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


def _make_recv(tmp_path: Path) -> ReceiverAgent:
    s = RecvSettings(
        receiver_id="r1",
        orchestrator_url="http://orch.test",
        token="t",
        storage_dir=tmp_path,
        poll_interval=1,
        concurrent_pulls=2,
        platform="linux",
    )
    r = ReceiverAgent(s)

    class Stub:
        async def ack(self, _: AckReport) -> None:
            pass

        async def aclose(self) -> None:
            pass

    r.client = Stub()  # type: ignore[assignment]
    return r


async def test_fetch_one_credits_bytes_on_success(tmp_path):
    payload = b"hello-world" * 100
    srv, port = _serve(payload)
    try:
        r = _make_recv(tmp_path)
        it = PullItem(
            granule_id="g1",
            batch_id="b1",
            object_id=1,
            object_key="g1/out.bin",
            presigned_url=f"http://127.0.0.1:{port}/",
            sha256=hashlib.sha256(payload).hexdigest(),
            size=len(payload),
        )
        await r._fetch_one(asyncio.Semaphore(1), it)

        assert r.stats.in_flight == 0
        # The bytes landed in the rolling window — count, not rate
        assert sum(b for _, b in r.stats._events) == len(payload)
    finally:
        srv.shutdown()


async def test_fetch_one_does_not_credit_bytes_on_sha_mismatch(tmp_path):
    """Failed verify still drops in_flight back to 0 but doesn't count toward
    throughput — the bytes existed but were thrown away."""
    payload = b"actual"
    srv, port = _serve(payload)
    try:
        r = _make_recv(tmp_path)
        it = PullItem(
            granule_id="g1",
            batch_id="b1",
            object_id=2,
            object_key="g1/bad.bin",
            presigned_url=f"http://127.0.0.1:{port}/",
            sha256="0" * 64,
            size=len(payload),
        )
        await r._fetch_one(asyncio.Semaphore(1), it)

        assert r.stats.in_flight == 0
        assert r.stats.recent_bps() == 0
    finally:
        srv.shutdown()


# ─── Orchestrator persists + exposes the new fields ───────────────────────


@pytest.fixture
async def client(tmp_path):
    object.__setattr__(settings, "db_path", tmp_path / "test.db")
    object.__setattr__(settings, "token", "")
    await orch_db.init_db()
    try:
        yield TestClient(app)
    finally:
        await orch_db.shutdown_db()


async def test_heartbeat_persists_queue_pulling_and_throughput(client):
    client.post("/api/receivers/register", json={"receiver_id": "r1", "version": "t", "platform": "linux"})
    r = client.post(
        "/api/receivers/heartbeat",
        json={
            "receiver_id": "r1",
            "disk_free_gb": 12.5,
            "queue_pulling": 3,
            "recent_pull_bps": 1_500_000,
        },
    )
    assert r.status_code == 200

    async with orch_db._session_maker() as s:
        row = await s.get(Receiver, "r1")
        assert row.queue_pulling == 3
        assert row.recent_pull_bps == 1_500_000


async def test_list_receivers_returns_new_fields(client):
    client.post("/api/receivers/register", json={"receiver_id": "r1", "version": "t", "platform": "linux"})
    client.post(
        "/api/receivers/heartbeat",
        json={
            "receiver_id": "r1",
            "disk_free_gb": 1.0,
            "queue_pulling": 2,
            "recent_pull_bps": 4096,
        },
    )
    rows = client.get("/api/receivers").json()
    assert len(rows) == 1
    assert rows[0]["queue_pulling"] == 2
    assert rows[0]["recent_pull_bps"] == 4096


async def test_legacy_receiver_without_new_fields_defaults_to_zero(client):
    """Old receiver builds send only disk_free_gb. Pydantic defaults the new
    fields to 0 — list endpoint must still return them as ints, not None."""
    client.post("/api/receivers/register", json={"receiver_id": "r1", "version": "t", "platform": "linux"})
    r = client.post("/api/receivers/heartbeat", json={"receiver_id": "r1", "disk_free_gb": 0.5})
    assert r.status_code == 200

    rows = client.get("/api/receivers").json()
    assert rows[0]["queue_pulling"] == 0
    assert rows[0]["recent_pull_bps"] == 0
