"""Bundle garbage-collector endpoint: POST /api/admin/gc/bundles.

Covers:
- dry-run lists candidates without touching DB / blobs
- actual delete drops rows + orphaned blob files
- in-use bundles (any batch references them) are never candidates
- young bundles (uploaded_at within age_days) are never candidates
- shared sha256 keeps the blob alive when only one of multiple rows is GC'd
"""

from __future__ import annotations

import hashlib
import io
import zipfile
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from sathop.orchestrator import db as orch_db
from sathop.orchestrator.config import settings
from sathop.orchestrator.db import Batch, Bundle, utcnow
from sathop.orchestrator.main import app


@pytest.fixture
async def client(tmp_path):
    object.__setattr__(settings, "db_path", tmp_path / "test.db")
    object.__setattr__(settings, "token", "")
    object.__setattr__(settings, "bundle_storage", tmp_path / "bundles")
    await orch_db.init_db()
    try:
        yield TestClient(app)
    finally:
        await orch_db.shutdown_db()


def _zip(name: str = "demo", version: str = "0.1.0") -> bytes:
    body = (
        f"name: {name}\nversion: {version}\n"
        "inputs:\n  slots:\n    - name: primary\n      product: any\n"
        "execution:\n  entrypoint: 'python run.py'\n"
        "outputs:\n  watch_dir: output\n"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("manifest.yaml", body)
    return buf.getvalue()


async def _age_bundle(name: str, version: str, *, days: int) -> None:
    """Backdate uploaded_at so age_days threshold can match in tests without
    sleeping. Operates on an existing row uploaded via the public endpoint."""
    async with orch_db._session_maker() as s:
        b = await s.get(Bundle, (name, version))
        assert b is not None
        b.uploaded_at = utcnow() - timedelta(days=days)
        await s.commit()


async def test_gc_dry_run_lists_orphans_without_deleting(client):
    blob = _zip("orphan", "0.1.0")
    client.post("/api/bundles", files={"file": ("b.zip", blob, "application/zip")})
    await _age_bundle("orphan", "0.1.0", days=45)

    r = client.post("/api/admin/gc/bundles", params={"dry_run": True, "age_days": 30})
    assert r.status_code == 200
    body = r.json()
    assert body["dry_run"] is True
    assert body["age_days"] == 30
    assert len(body["candidates"]) == 1
    cand = body["candidates"][0]
    assert cand["name"] == "orphan"
    assert cand["version"] == "0.1.0"
    assert cand["age_days"] >= 30
    assert body["freed_bytes_estimate"] == cand["size"]

    # DB row + blob still present after dry-run.
    async with orch_db._session_maker() as s:
        assert await s.get(Bundle, ("orphan", "0.1.0")) is not None
    sha = hashlib.sha256(blob).hexdigest()
    assert (settings.bundle_storage / f"{sha}.zip").is_file()


async def test_gc_actual_run_deletes_row_and_blob(client):
    blob = _zip("orphan", "0.1.0")
    client.post("/api/bundles", files={"file": ("b.zip", blob, "application/zip")})
    await _age_bundle("orphan", "0.1.0", days=45)

    r = client.post("/api/admin/gc/bundles", params={"dry_run": False, "age_days": 30})
    assert r.status_code == 200
    body = r.json()
    assert body["dry_run"] is False
    assert len(body["deleted"]) == 1
    assert body["unlinked_blobs"] == 1
    assert body["freed_bytes"] == len(blob)

    async with orch_db._session_maker() as s:
        assert await s.get(Bundle, ("orphan", "0.1.0")) is None
    sha = hashlib.sha256(blob).hexdigest()
    assert not (settings.bundle_storage / f"{sha}.zip").exists()


async def test_gc_skips_in_use_bundles(client):
    """A bundle referenced by even one batch must never be GC'd, regardless
    of age. Operator must clean up batches first."""
    blob = _zip("inuse", "0.1.0")
    client.post("/api/bundles", files={"file": ("b.zip", blob, "application/zip")})
    await _age_bundle("inuse", "0.1.0", days=365)
    # Attach a batch that references it.
    async with orch_db._session_maker() as s:
        s.add(Batch(batch_id="b1", name="t", bundle_ref="orch:inuse@0.1.0"))
        await s.commit()

    r = client.post("/api/admin/gc/bundles", params={"dry_run": False, "age_days": 30})
    assert r.status_code == 200
    assert r.json()["deleted"] == []

    async with orch_db._session_maker() as s:
        assert await s.get(Bundle, ("inuse", "0.1.0")) is not None


async def test_gc_skips_young_bundles(client):
    """Just-uploaded bundles must not be GC'd — operators may be in a batch-
    create flow that hasn't created the batch row yet (race protection)."""
    blob = _zip("fresh", "0.1.0")
    client.post("/api/bundles", files={"file": ("b.zip", blob, "application/zip")})
    # Don't backdate — uploaded_at is "now".

    r = client.post("/api/admin/gc/bundles", params={"dry_run": False, "age_days": 30})
    assert r.status_code == 200
    assert r.json()["deleted"] == []


async def test_gc_keeps_blob_when_other_row_shares_sha(client):
    """Bundle blobs are content-addressed: two (name, version) rows can point
    at the same sha if their zip bytes happen to match. GC'ing one must not
    unlink a blob still referenced by the other."""
    blob = _zip("shared", "0.1.0")
    client.post("/api/bundles", files={"file": ("b.zip", blob, "application/zip")})
    # Upload the same bytes under a different (name, version).
    blob2 = _zip("shared", "0.2.0")  # different content
    client.post("/api/bundles", files={"file": ("b.zip", blob2, "application/zip")})
    # Force two rows to share the same sha (manually rewriting the second
    # row's sha to match the first — this models the de-dup case in the wild).
    sha_first = hashlib.sha256(blob).hexdigest()
    async with orch_db._session_maker() as s:
        b2 = await s.get(Bundle, ("shared", "0.2.0"))
        b2.sha256 = sha_first
        await s.commit()
    await _age_bundle("shared", "0.1.0", days=45)
    # Leave 0.2.0 fresh so only 0.1.0 is a GC candidate.

    r = client.post("/api/admin/gc/bundles", params={"dry_run": False, "age_days": 30})
    assert r.status_code == 200
    body = r.json()
    assert len(body["deleted"]) == 1
    assert body["deleted"][0]["version"] == "0.1.0"
    # Blob still present because 0.2.0 still references the same sha.
    assert body["unlinked_blobs"] == 0
    assert (settings.bundle_storage / f"{sha_first}.zip").is_file()
