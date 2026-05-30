"""0.8.1 upgrade plumbing:

1. `sathop.shared.release` — version normalization + .pending-version stamping
   (the one-shot the entrypoint consumes to install a release).
2. Coordinated worker upgrade — POST /api/workers/{id}/update {version} carries
   the target through the heartbeat reply (update_to_version), consumed once.
3. GET /api/admin/latest-version — server-side, cached GitHub proxy so the
   browser never hits the rate-limited api.github.com directly.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from sathop.orchestrator import db as orch_db
from sathop.orchestrator.db import Worker
from sathop.orchestrator.main import app
from sathop.shared.release import PENDING_VERSION_FILE, normalize_version, write_pending_version


@pytest.fixture
async def client(tmp_path, patch_settings):
    patch_settings(db_path=tmp_path / "test.db", token="")
    await orch_db.init_db()
    try:
        yield TestClient(app)
    finally:
        await orch_db.shutdown_db()


async def _seed_worker() -> None:
    async with orch_db._session_maker() as s:
        s.add(Worker(worker_id="w1", version="0.7.0", capacity=4))
        await s.commit()


def _heartbeat() -> dict:
    return {"worker_id": "w1", "version": "0.7.0"}


# ─── release helpers ────────────────────────────────────────────────────────


def test_normalize_version_strips_v_prefix():
    assert normalize_version("v0.8.1") == "0.8.1"
    assert normalize_version(" 1.2.3 ") == "1.2.3"
    assert normalize_version("0.8.1rc1") == "0.8.1rc1"


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "latest",
        "abc",
        "v",
        "x.y.z",
        # path-traversal / injection attempts that an unanchored regex would pass
        "0.8.1/../v0.7.0",
        "1.2/evil/path",
        "0.8.1\\x",
        "0.8.1 0.7.0",
        "../0.8.1",
    ],
)
def test_normalize_version_rejects_garbage_and_traversal(bad):
    with pytest.raises(ValueError):
        normalize_version(bad)


def test_write_pending_version_stamps_repo_root(tmp_path, monkeypatch):
    monkeypatch.setattr("sathop.shared.release.repo_root", lambda: tmp_path)
    path = write_pending_version("v0.8.1")
    assert path == tmp_path / PENDING_VERSION_FILE
    assert path.read_text() == "0.8.1"


# ─── coordinated worker upgrade signal ──────────────────────────────────────


async def test_worker_upgrade_carries_version_through_heartbeat(client):
    await _seed_worker()
    r = client.post("/api/workers/w1/update", json={"version": "v0.8.1"})
    assert r.status_code == 200
    assert r.json()["version"] == "0.8.1"  # 'v' stripped

    body = client.post("/api/workers/heartbeat", json=_heartbeat()).json()
    assert body["update_requested"] is True
    assert body["update_to_version"] == "0.8.1"

    async with orch_db._session_maker() as s:
        w = await s.get(Worker, "w1")
        assert w.update_to_version is None  # consumed alongside the one-shot

    body = client.post("/api/workers/heartbeat", json=_heartbeat()).json()
    assert body["update_requested"] is False
    assert body["update_to_version"] is None


async def test_worker_update_without_version_is_plain_restart(client):
    await _seed_worker()
    client.post("/api/workers/w1/update")  # no body
    body = client.post("/api/workers/heartbeat", json=_heartbeat()).json()
    assert body["update_requested"] is True
    assert body["update_to_version"] is None


async def test_worker_update_rejects_garbage_version(client):
    await _seed_worker()
    r = client.post("/api/workers/w1/update", json={"version": "nope"})
    assert r.status_code == 422


async def test_update_all_carries_version(client):
    await _seed_worker()
    r = client.post("/api/workers/update-all", json={"version": "0.8.1"})
    assert r.json() == {"ok": True, "count": 1, "version": "0.8.1"}
    body = client.post("/api/workers/heartbeat", json=_heartbeat()).json()
    assert body["update_to_version"] == "0.8.1"


# ─── server-side latest-version proxy ───────────────────────────────────────


async def test_latest_version_returns_tag_and_current(client, monkeypatch):
    from sathop.orchestrator.api import admin

    async def fake():
        return {"tag": "v0.9.0", "html_url": "https://example/releases/tag/v0.9.0"}

    monkeypatch.setattr(admin, "_fetch_latest_release", fake)
    body = client.get("/api/admin/latest-version").json()
    assert body["tag"] == "v0.9.0"
    assert body["current"]  # the orchestrator's own version is injected
    assert "error" not in body


async def test_latest_version_error_is_surfaced_not_cached(client, monkeypatch):
    from sathop.orchestrator.api import admin

    async def boom():
        raise RuntimeError("API rate limit exceeded")

    monkeypatch.setattr(admin, "_fetch_latest_release", boom)
    body = client.get("/api/admin/latest-version").json()
    assert body["tag"] == ""
    assert "rate limit" in body["error"]
    assert admin._latest_cache["data"] is None  # failures aren't cached
