"""Per-batch credentials: persisted on POST /api/batches and included in every
LeaseItem. Replaces the deleted central credential registry."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from sathop.orchestrator import db as orch_db
from sathop.orchestrator.config import settings
from sathop.orchestrator.db import Batch, Bundle, Granule, Worker, utcnow
from sathop.orchestrator.main import app
from sathop.shared.protocol import GranuleState

_MINIMAL_MANIFEST = (
    '{"name":"b","version":"1.0","execution":{"entrypoint":"true"},'
    '"outputs":{"watch_dir":"output"},'
    '"inputs":{"slots":[{"name":"primary","product":"any"}]}}'
)


async def _register_bundle(name: str, version: str) -> None:
    async with orch_db._session_maker() as s:
        s.add(
            Bundle(
                name=name,
                version=version,
                sha256="x" * 64,
                size=1,
                manifest_json=_MINIMAL_MANIFEST,
                uploaded_at=utcnow(),
            )
        )
        await s.commit()


@pytest.fixture
async def client(tmp_path):
    object.__setattr__(settings, "db_path", tmp_path / "test.db")
    object.__setattr__(settings, "token", "")
    object.__setattr__(settings, "max_inflight_per_worker", 0)
    await orch_db.init_db()
    try:
        yield TestClient(app)
    finally:
        await orch_db.shutdown_db()


async def test_batch_create_persists_credentials(client):
    await _register_bundle("b", "1.0")
    r = client.post(
        "/api/batches",
        json={
            "batch_id": "b1",
            "name": "t",
            "bundle_ref": "orch:b@1.0",
            "granules": [
                {"granule_id": "g1", "inputs": [{"url": "http://x/f", "filename": "f", "product": "any"}]}
            ],
            "credentials": {
                "nasa-edl": {"name": "nasa-edl", "scheme": "bearer", "token": "tok-123"},
            },
        },
    )
    assert r.status_code == 200, r.text

    async with orch_db._session_maker() as s:
        b = await s.get(Batch, "b1")
        assert b is not None
        assert '"nasa-edl"' in b.credentials_json
        assert '"tok-123"' in b.credentials_json


async def test_lease_includes_credentials_from_batch(client):
    async with orch_db._session_maker() as s:
        s.add(Worker(worker_id="w1", version="", capacity=10, public_url=None))
        s.add(
            Batch(
                batch_id="b1",
                name="t",
                bundle_ref="local:/x",
                credentials_json=(
                    '{"nasa-edl": {"name": "nasa-edl", "scheme": "bearer", "token": "t-1"},'
                    ' "esa-basic": {"name": "esa-basic", "scheme": "basic",'
                    ' "username": "u", "password": "p"}}'
                ),
            )
        )
        s.add(
            Granule(
                granule_id="g1",
                batch_id="b1",
                state=GranuleState.PENDING.value,
                inputs_json="[]",
            )
        )
        await s.commit()

    r = client.post("/api/workers/lease", json={"worker_id": "w1", "capacity": 1})
    assert r.status_code == 200
    item = r.json()["items"][0]
    creds = item["credentials"]
    assert set(creds.keys()) == {"nasa-edl", "esa-basic"}
    assert creds["nasa-edl"]["scheme"] == "bearer"
    assert creds["nasa-edl"]["token"] == "t-1"
    assert creds["esa-basic"]["scheme"] == "basic"
    assert creds["esa-basic"]["username"] == "u"
    assert creds["esa-basic"]["password"] == "p"


async def test_lease_empty_credentials_when_batch_has_none(client):
    async with orch_db._session_maker() as s:
        s.add(Worker(worker_id="w1", version="", capacity=10, public_url=None))
        s.add(Batch(batch_id="b1", name="t", bundle_ref="local:/x"))  # default "{}"
        s.add(
            Granule(
                granule_id="g1",
                batch_id="b1",
                state=GranuleState.PENDING.value,
                inputs_json="[]",
            )
        )
        await s.commit()

    r = client.post("/api/workers/lease", json={"worker_id": "w1", "capacity": 1})
    assert r.json()["items"][0]["credentials"] == {}


async def test_lease_handles_malformed_credentials_json(client):
    """Garbled credentials_json shouldn't break leasing — fall back to empty."""
    async with orch_db._session_maker() as s:
        s.add(Worker(worker_id="w1", version="", capacity=10, public_url=None))
        s.add(
            Batch(
                batch_id="b1",
                name="t",
                bundle_ref="local:/x",
                credentials_json="not-json",
            )
        )
        s.add(
            Granule(
                granule_id="g1",
                batch_id="b1",
                state=GranuleState.PENDING.value,
                inputs_json="[]",
            )
        )
        await s.commit()

    r = client.post("/api/workers/lease", json={"worker_id": "w1", "capacity": 1})
    assert r.status_code == 200
    assert r.json()["items"][0]["credentials"] == {}


async def test_worker_register_no_longer_returns_credentials(client):
    """Regression guard: /api/workers/register must NOT leak credentials —
    they're per-batch, not global."""
    r = client.post(
        "/api/workers/register",
        json={"worker_id": "w1", "version": "", "capacity": 1},
    )
    assert r.status_code == 200
    body = r.json()
    assert "credentials" not in body
    assert "credentials_hash" not in body


async def test_settings_info_no_longer_exposes_credentials_file(client):
    r = client.get("/api/admin/settings/info")
    assert r.status_code == 200
    body = r.json()
    assert "credentials_file" not in body
    assert "credentials_file_writable" not in body
