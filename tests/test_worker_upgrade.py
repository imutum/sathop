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

    async def fake(channel="stable"):
        return {"tag": "v0.9.0", "html_url": "https://example/releases/tag/v0.9.0"}

    monkeypatch.setattr(admin, "_fetch_latest_release", fake)
    body = client.get("/api/admin/latest-version").json()
    assert body["tag"] == "v0.9.0"
    assert body["current"]  # the orchestrator's own version is injected
    assert body["channel"] == "stable"  # default channel
    assert "error" not in body


async def test_latest_version_error_is_surfaced_then_bucketed(client, monkeypatch):
    """A GitHub failure with no prior good surfaces tag=''+error, and is bucketed for
    the clock-hour so a page-reload storm can't re-hit GitHub (the 403 cause)."""
    from sathop.orchestrator.api import admin

    monkeypatch.setattr(admin, "_hour_bucket", lambda: 1000)
    calls = {"n": 0}

    async def boom(channel="stable"):
        calls["n"] += 1
        raise RuntimeError("API rate limit exceeded")

    monkeypatch.setattr(admin, "_fetch_latest_release", boom)
    body = client.get("/api/admin/latest-version").json()
    assert body["tag"] == ""
    assert "rate limit" in body["error"]
    # Bucketed: a second call this hour serves the cached error, no extra GitHub hit.
    again = client.get("/api/admin/latest-version").json()
    assert again["tag"] == "" and "rate limit" in again["error"]
    assert calls["n"] == 1


async def test_latest_version_serves_stale_on_error_next_hour(client, monkeypatch):
    """After a prior success, a fetch failure in a LATER clock-hour serves last-known-
    good (stale) instead of a failure, and bucketing stops a retry storm that hour."""
    from sathop.orchestrator.api import admin

    hour = {"b": 2000}
    monkeypatch.setattr(admin, "_hour_bucket", lambda: hour["b"])

    async def good(channel="stable"):
        return {"tag": "v1.2.3", "html_url": "https://example/v1.2.3"}

    monkeypatch.setattr(admin, "_fetch_latest_release", good)
    first = client.get("/api/admin/latest-version").json()
    assert first["tag"] == "v1.2.3" and "stale" not in first

    hour["b"] = 2001  # next clock-hour → cache miss
    calls = {"n": 0}

    async def boom(channel="stable"):
        calls["n"] += 1
        raise RuntimeError("403 rate limit exceeded")

    monkeypatch.setattr(admin, "_fetch_latest_release", boom)
    stale = client.get("/api/admin/latest-version").json()
    assert stale["tag"] == "v1.2.3"  # last-known-good, not ""
    assert stale.get("stale") is True
    assert "rate limit" in stale["error"]
    assert calls["n"] == 1

    again = client.get("/api/admin/latest-version").json()  # same hour → bucketed
    assert again["tag"] == "v1.2.3" and again.get("stale") is True
    assert calls["n"] == 1  # no extra GitHub hit within the hour


async def test_latest_version_force_bypasses_and_resets_cache(client, monkeypatch):
    """The manual button (?force=true) re-hits GitHub even within the same clock-hour
    and resets the cache; a normal call afterwards serves the freshly fetched value."""
    from sathop.orchestrator.api import admin

    monkeypatch.setattr(admin, "_hour_bucket", lambda: 5000)  # pin one hour bucket
    calls = {"n": 0}
    tag = {"v": "v1.0.0"}

    async def fetch(channel="stable"):
        calls["n"] += 1
        return {"tag": tag["v"], "html_url": "https://example"}

    monkeypatch.setattr(admin, "_fetch_latest_release", fetch)
    first = client.get("/api/admin/latest-version").json()
    assert first["tag"] == "v1.0.0" and calls["n"] == 1
    client.get("/api/admin/latest-version")  # same hour, no force → cached
    assert calls["n"] == 1
    tag["v"] = "v1.0.1"
    forced = client.get("/api/admin/latest-version?force=true").json()  # bypass the bucket
    assert forced["tag"] == "v1.0.1" and calls["n"] == 2
    after = client.get("/api/admin/latest-version").json()  # force reset cache → fresh, no fetch
    assert after["tag"] == "v1.0.1" and calls["n"] == 2


async def test_latest_version_edge_channel_is_resolved_and_cached_separately(client, monkeypatch):
    from sathop.orchestrator.api import admin

    seen: list[str] = []

    async def fake(channel="stable"):
        seen.append(channel)
        return {"tag": f"v9.9.9-{channel}", "html_url": f"https://example/{channel}"}

    monkeypatch.setattr(admin, "_fetch_latest_release", fake)
    edge = client.get("/api/admin/latest-version?channel=edge").json()
    assert edge["tag"] == "v9.9.9-edge"
    assert edge["channel"] == "edge"
    stable = client.get("/api/admin/latest-version?channel=stable").json()
    assert stable["tag"] == "v9.9.9-stable"
    assert seen == ["edge", "stable"]  # each channel resolved once, cached independently
    assert set(admin._latest_cache) == {"edge", "stable"}


async def test_latest_version_defaults_to_configured_channel(client, monkeypatch, patch_settings):
    from sathop.orchestrator.api import admin

    patch_settings(channel="edge")

    async def fake(channel="stable"):
        return {"tag": f"v1.0.0-{channel}", "html_url": "https://example"}

    monkeypatch.setattr(admin, "_fetch_latest_release", fake)
    body = client.get("/api/admin/latest-version").json()  # no ?channel → uses SATHOP_CHANNEL
    assert body["channel"] == "edge"
    assert body["tag"] == "v1.0.0-edge"
