"""Granule-id auto-prefixing in POST /api/batches and POST /api/batches/{id}/granules.

Keeps the global single-column PK on `granules.granule_id` while letting users
pick short IDs that only need to be unique inside their batch."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from sathop.orchestrator import db as orch_db
from sathop.orchestrator.config import settings
from sathop.orchestrator.db import Bundle, Granule, utcnow
from sathop.orchestrator.main import app

_MINIMAL_MANIFEST = (
    '{"name":"b","version":"1.0","execution":{"entrypoint":"true"},'
    '"outputs":{"watch_dir":"output"},'
    '"inputs":{"slots":[{"name":"primary","product":"any"}]}}'
)


async def _register_bundle(name: str = "b", version: str = "1.0") -> None:
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
    await orch_db.init_db()
    try:
        yield TestClient(app)
    finally:
        await orch_db.shutdown_db()


def _granule(gid: str) -> dict:
    return {
        "granule_id": gid,
        "inputs": [{"url": "http://x/f", "filename": "f", "product": "any"}],
    }


def _create_batch(client, batch_id: str, gids: list[str]):
    return client.post(
        "/api/batches",
        json={
            "batch_id": batch_id,
            "name": "t",
            "bundle_ref": "orch:b@1.0",
            "granules": [_granule(g) for g in gids],
        },
    )


# ─── prefix happens at insert ──────────────────────────────────────────────


async def test_short_user_id_stored_as_prefixed(client):
    await _register_bundle()
    r = _create_batch(client, "alpha", ["0240"])
    assert r.status_code == 200, r.text

    async with orch_db._session_maker() as s:
        ids = (await s.execute(select(Granule.granule_id))).scalars().all()
        assert ids == ["alpha:0240"]


async def test_same_short_id_in_two_batches_does_not_collide(client):
    """The original bug: short ID "0240" in batch "alpha" used to crash a
    later batch "beta" that also wanted "0240"."""
    await _register_bundle()
    assert _create_batch(client, "alpha", ["0240", "0245"]).status_code == 200
    r = _create_batch(client, "beta", ["0240", "0245"])
    assert r.status_code == 200, r.text

    async with orch_db._session_maker() as s:
        ids = sorted((await s.execute(select(Granule.granule_id))).scalars().all())
        assert ids == ["alpha:0240", "alpha:0245", "beta:0240", "beta:0245"]


async def test_duplicate_user_id_within_payload_returns_422(client):
    await _register_bundle()
    r = _create_batch(client, "alpha", ["0240", "0245", "0240"])
    assert r.status_code == 422
    assert "duplicate" in r.text.lower()
    # nothing inserted on validation failure
    async with orch_db._session_maker() as s:
        rows = (await s.execute(select(Granule.granule_id))).scalars().all()
        assert rows == []


# ─── /api/batches/{id}/granules also prefixes + dedupes ─────────────────────


async def test_add_granules_prefixes_and_skips_existing(client):
    await _register_bundle()
    assert _create_batch(client, "alpha", ["0240"]).status_code == 200

    # Re-add: "0240" already there (now stored as "alpha:0240"), "0250" is new.
    r = client.post(
        "/api/batches/alpha/granules",
        json={"granules": [_granule("0240"), _granule("0250")]},
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"added": 1, "skipped": 1}

    async with orch_db._session_maker() as s:
        ids = sorted((await s.execute(select(Granule.granule_id))).scalars().all())
        assert ids == ["alpha:0240", "alpha:0250"]


async def test_add_granules_same_short_id_other_batch_is_independent(client):
    """add_granules for batch B must not be blocked by an existing row in batch A
    that happens to share the user-supplied ID."""
    await _register_bundle()
    assert _create_batch(client, "alpha", ["0240"]).status_code == 200
    assert _create_batch(client, "beta", []).status_code == 200

    r = client.post(
        "/api/batches/beta/granules",
        json={"granules": [_granule("0240")]},
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"added": 1, "skipped": 0}
