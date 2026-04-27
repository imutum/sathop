"""Batch-level env override: BatchCreate.execution_env flows to LeaseItem."""

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
    """Seed a minimal Bundle row so POST /api/batches with
    bundle_ref=orch:<name>@<version> passes existence check."""
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


async def test_batch_create_persists_execution_env(client):
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
            "execution_env": {"SATHOP_FACTOR": "4", "TILE_H": "600"},
        },
    )
    assert r.status_code == 200

    async with orch_db._session_maker() as s:
        b = await s.get(Batch, "b1")
        assert b is not None
        assert '"SATHOP_FACTOR"' in b.execution_env_json
        assert '"4"' in b.execution_env_json


async def test_lease_includes_execution_env_from_batch(client):
    async with orch_db._session_maker() as s:
        s.add(Worker(worker_id="w1", version="", capacity=10, public_url=None))
        s.add(
            Batch(
                batch_id="b1",
                name="t",
                bundle_ref="local:/x",
                execution_env_json='{"SATHOP_FACTOR": "4"}',
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
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["execution_env"] == {"SATHOP_FACTOR": "4"}


async def test_lease_empty_env_when_batch_has_no_override(client):
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
    assert r.json()["items"][0]["execution_env"] == {}


async def test_lease_handles_malformed_env_json(client):
    """Garbled execution_env_json shouldn't break leasing — fall back to empty."""
    async with orch_db._session_maker() as s:
        s.add(Worker(worker_id="w1", version="", capacity=10, public_url=None))
        s.add(
            Batch(
                batch_id="b1",
                name="t",
                bundle_ref="local:/x",
                execution_env_json="not-json",
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
    assert r.json()["items"][0]["execution_env"] == {}
