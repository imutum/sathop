"""Runtime-mutable fleet reporting detail. Covers the DB-backed `worker_detail`
setting, the admin REST surface that flips it from the Web UI (overriding the
SATHOP_WORKER_DETAIL env default, persisting across restarts + shared across
multi-process workers), and the heartbeat reply that pushes the effective value
to the fleet on the next beat — no worker restart.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from sathop.orchestrator import db as orch_db
from sathop.orchestrator.db import (
    WORKER_DETAIL_KEY,
    Worker,
    get_setting,
    get_worker_detail,
    set_setting,
)
from sathop.orchestrator.main import app


@pytest.fixture
async def client(tmp_path, patch_settings):
    patch_settings(db_path=tmp_path / "test.db", token="")
    await orch_db.init_db()
    try:
        yield TestClient(app)
    finally:
        await orch_db.shutdown_db()


async def _seed_worker(worker_id: str = "w1") -> None:
    async with orch_db._session_maker() as s:
        s.add(Worker(worker_id=worker_id, version="t", capacity=10, public_url=None))
        await s.commit()


def _hb_detail(client: TestClient, worker_id: str = "w1") -> str:
    return client.post("/api/workers/heartbeat", json={"worker_id": worker_id}).json()["detail"]


# ─── default / env fallback ────────────────────────────────────────────────


async def test_default_is_verbose(client):
    """No override + default env → verbose, surfaced both on the info endpoint
    and pushed to the fleet via heartbeat."""
    assert client.get("/api/admin/settings/info").json()["worker_detail"] == "verbose"
    await _seed_worker()
    assert _hb_detail(client) == "verbose"


async def test_env_default_used_when_no_override(client, patch_settings):
    """With no DB row, the SATHOP_WORKER_DETAIL env default is the effective
    value — an operator who never touches the UI keeps the declared behavior."""
    patch_settings(worker_detail="fast")
    await _seed_worker()
    assert client.get("/api/admin/settings/info").json()["worker_detail"] == "fast"
    assert _hb_detail(client) == "fast"


# ─── runtime toggle via the admin API ──────────────────────────────────────


async def test_set_fast_flips_info_and_heartbeat(client):
    await _seed_worker()
    r = client.post("/api/admin/settings/worker-detail", json={"detail": "fast"})
    assert r.status_code == 200
    assert r.json() == {"detail": "fast"}
    assert client.get("/api/admin/settings/info").json()["worker_detail"] == "fast"
    assert _hb_detail(client) == "fast"
    # …and reversible
    client.post("/api/admin/settings/worker-detail", json={"detail": "verbose"})
    assert _hb_detail(client) == "verbose"


async def test_db_override_beats_env_default(client, patch_settings):
    """The operator's UI choice (DB row) wins over the env default — so flipping
    compose can't silently override what someone set in the UI."""
    patch_settings(worker_detail="fast")
    await _seed_worker()
    client.post("/api/admin/settings/worker-detail", json={"detail": "verbose"})
    assert _hb_detail(client) == "verbose"


async def test_invalid_detail_rejected(client):
    r = client.post("/api/admin/settings/worker-detail", json={"detail": "loud"})
    assert r.status_code == 422


# ─── unit: get_worker_detail fallback + kv upsert ──────────────────────────


async def test_get_worker_detail_fallback_and_override(client, patch_settings):
    patch_settings(worker_detail="verbose")
    async with orch_db._session_maker() as s:
        assert await get_worker_detail(s) == "verbose"  # no row → env default
        await set_setting(s, WORKER_DETAIL_KEY, "fast")
        await s.commit()
    async with orch_db._session_maker() as s:
        assert await get_worker_detail(s) == "fast"  # row wins
        await set_setting(s, WORKER_DETAIL_KEY, "bogus")  # corrupt value
        await s.commit()
    async with orch_db._session_maker() as s:
        assert await get_worker_detail(s) == "verbose"  # invalid → env default


async def test_set_setting_upserts(client):
    async with orch_db._session_maker() as s:
        await set_setting(s, "k", "v1")
        await s.commit()
    async with orch_db._session_maker() as s:
        assert await get_setting(s, "k") == "v1"
        await set_setting(s, "k", "v2")  # update, not duplicate-insert
        await s.commit()
    async with orch_db._session_maker() as s:
        assert await get_setting(s, "k") == "v2"
        assert await get_setting(s, "missing") is None
