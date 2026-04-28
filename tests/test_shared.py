"""Orchestrator-side shared-file store: upload + list + meta + download + delete.
Validates name validation, sha256 computation on stream, replace semantics,
404s, and blob GC on delete."""

from __future__ import annotations

import hashlib
import io

import pytest
from fastapi.testclient import TestClient

from sathop.orchestrator import db as orch_db
from sathop.orchestrator.config import settings
from sathop.orchestrator.db import SharedFile
from sathop.orchestrator.main import app


@pytest.fixture
async def client(tmp_path):
    object.__setattr__(settings, "db_path", tmp_path / "test.db")
    object.__setattr__(settings, "token", "")
    object.__setattr__(settings, "shared_storage", tmp_path / "shared")
    await orch_db.init_db()
    try:
        yield TestClient(app)
    finally:
        await orch_db.shutdown_db()


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


# ─── upload ─────────────────────────────────────────────────────────────────


async def test_upload_happy_path_persists_blob_and_row(client):
    data = b"land-water mask v1"
    r = client.put(
        "/api/shared/mask.tif",
        files={"file": ("mask.tif", io.BytesIO(data), "application/octet-stream")},
        params={"description": "first"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "mask.tif"
    assert body["sha256"] == _sha(data)
    assert body["size"] == len(data)
    assert body["description"] == "first"

    blob = settings.shared_storage / "mask.tif"
    assert blob.is_file()
    assert blob.read_bytes() == data

    async with orch_db._session_maker() as s:
        row = await s.get(SharedFile, "mask.tif")
        assert row is not None
        assert row.sha256 == _sha(data)


async def test_upload_replace_overwrites_bytes_and_updates_sha(client):
    v1 = b"v1-content"
    v2 = b"v2-much-longer-content-replacing-v1"

    client.put("/api/shared/mask.tif", files={"file": ("m.tif", io.BytesIO(v1), "x")})
    r = client.put(
        "/api/shared/mask.tif",
        files={"file": ("m.tif", io.BytesIO(v2), "x")},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["sha256"] == _sha(v2)
    assert body["size"] == len(v2)
    assert (settings.shared_storage / "mask.tif").read_bytes() == v2

    async with orch_db._session_maker() as s:
        from sqlalchemy import select

        rows = (await s.execute(select(SharedFile))).scalars().all()
        assert len(rows) == 1


async def test_upload_rejects_empty_file(client):
    r = client.put(
        "/api/shared/empty.tif",
        files={"file": ("empty.tif", io.BytesIO(b""), "x")},
    )
    assert r.status_code == 400
    assert "empty" in r.json()["detail"].lower()
    async with orch_db._session_maker() as s:
        assert await s.get(SharedFile, "empty.tif") is None


@pytest.mark.parametrize(
    "bad",
    [
        "../etc/passwd",  # path traversal
        "sub/file.tif",  # path separator
        ".hidden",  # leading dot
        "",  # empty
        "a" * 256,  # over 255 char limit
        "has space.tif",  # whitespace not in charset
    ],
)
async def test_upload_rejects_invalid_names(client, bad):
    r = client.put(
        f"/api/shared/{bad}",
        files={"file": ("x", io.BytesIO(b"ok"), "x")},
    )
    # FastAPI routes `/shared/` without trailing name as a different endpoint,
    # but path-traversal names get caught by _validate_name or 404 from routing.
    assert r.status_code in (400, 404, 405), (bad, r.status_code, r.text)


# ─── list ───────────────────────────────────────────────────────────────────


async def test_list_sorts_by_name(client):
    for n in ("zeta.bin", "alpha.bin", "mid.bin"):
        client.put(f"/api/shared/{n}", files={"file": (n, io.BytesIO(b"x"), "x")})
    r = client.get("/api/shared")
    assert r.status_code == 200
    names = [row["name"] for row in r.json()]
    assert names == ["alpha.bin", "mid.bin", "zeta.bin"]


async def test_list_empty(client):
    r = client.get("/api/shared")
    assert r.status_code == 200
    assert r.json() == []


# ─── meta ───────────────────────────────────────────────────────────────────


async def test_meta_returns_sha_and_size_without_body(client):
    data = b"m" * 1000
    client.put("/api/shared/m.bin", files={"file": ("m.bin", io.BytesIO(data), "x")})
    r = client.get("/api/shared/m.bin")
    assert r.status_code == 200
    body = r.json()
    assert body == {"name": "m.bin", "sha256": _sha(data), "size": len(data)}


async def test_meta_404_for_missing(client):
    r = client.get("/api/shared/nope.bin")
    assert r.status_code == 404


# ─── download ───────────────────────────────────────────────────────────────


async def test_download_streams_bytes_with_sha_header(client):
    data = b"dem-bytes-\x00\x01\x02"
    client.put("/api/shared/dem.tif", files={"file": ("dem.tif", io.BytesIO(data), "x")})
    r = client.get("/api/shared/dem.tif/download")
    assert r.status_code == 200
    assert r.content == data
    assert r.headers["x-sha256"] == _sha(data)


async def test_download_404_for_missing(client):
    r = client.get("/api/shared/nope.bin/download")
    assert r.status_code == 404


async def test_download_accepts_query_token(client):
    """Browsers / curl without Authorization header still work via ?token=.
    This requires the orchestrator to actually enforce the token — flip it on."""
    object.__setattr__(settings, "token", "secret")
    try:
        r = client.put(
            "/api/shared/tok.bin",
            files={"file": ("tok.bin", io.BytesIO(b"data"), "x")},
            headers={"Authorization": "Bearer secret"},
        )
        assert r.status_code == 200

        r_no_auth = client.get("/api/shared/tok.bin/download")
        assert r_no_auth.status_code == 401

        r_q = client.get("/api/shared/tok.bin/download?token=secret")
        assert r_q.status_code == 200
        assert r_q.content == b"data"
    finally:
        object.__setattr__(settings, "token", "")


# ─── delete ─────────────────────────────────────────────────────────────────


async def test_delete_removes_row_and_blob(client):
    client.put("/api/shared/x.bin", files={"file": ("x.bin", io.BytesIO(b"byebye"), "x")})
    blob = settings.shared_storage / "x.bin"
    assert blob.is_file()

    r = client.delete("/api/shared/x.bin")
    assert r.status_code == 200

    assert not blob.exists()
    async with orch_db._session_maker() as s:
        assert await s.get(SharedFile, "x.bin") is None


async def test_delete_404_for_missing(client):
    r = client.delete("/api/shared/ghost.bin")
    assert r.status_code == 404


async def test_delete_refused_when_bundle_references_it(client):
    """A bundle in the registry declares shared_files: [mask.tif]; delete must 409."""
    import io as _io
    import zipfile as _zf

    client.put("/api/shared/mask.tif", files={"file": ("mask.tif", io.BytesIO(b"m"), "x")})
    buf = _io.BytesIO()
    with _zf.ZipFile(buf, "w") as zf:
        zf.writestr(
            "manifest.yaml",
            "name: demo\nversion: 0.1\n"
            "inputs:\n  slots:\n    - name: p\n      product: any\n"
            "execution:\n  entrypoint: 'python run.py'\n"
            "outputs:\n  watch_dir: output\n"
            "shared_files:\n  - mask.tif\n",
        )
    r = client.post("/api/bundles", files={"file": ("b.zip", buf.getvalue(), "application/zip")})
    assert r.status_code == 200, r.text

    r = client.delete("/api/shared/mask.tif")
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert "referenced by 1 bundle(s)" in detail
    assert "demo@0.1" in detail
    # Format must be operator-readable, not Python list repr
    assert "[" not in detail and "]" not in detail

    assert client.delete("/api/bundles/demo/0.1").status_code == 200
    assert client.delete("/api/shared/mask.tif").status_code == 200


async def test_delete_is_idempotent_only_via_re_upload(client):
    """Second delete of the same name is 404 (we don't pretend success).
    Re-upload works fine after delete."""
    client.put("/api/shared/m.bin", files={"file": ("m.bin", io.BytesIO(b"v1"), "x")})
    assert client.delete("/api/shared/m.bin").status_code == 200
    assert client.delete("/api/shared/m.bin").status_code == 404
    r = client.put("/api/shared/m.bin", files={"file": ("m.bin", io.BytesIO(b"v2"), "x")})
    assert r.status_code == 200
    assert r.json()["sha256"] == _sha(b"v2")


# ─── streaming sha256 on large-ish uploads ──────────────────────────────────


async def test_large_upload_streams_without_loading_into_memory(client):
    """Upload 8 MiB in one go; sha256 must match the whole content.
    Primarily a smoke test that the chunked read loop assembles correctly."""
    data = bytes(range(256)) * (8 << 20 // 256)  # ~8 MiB deterministic
    r = client.put(
        "/api/shared/big.bin",
        files={"file": ("big.bin", io.BytesIO(data), "application/octet-stream")},
    )
    assert r.status_code == 200
    assert r.json()["sha256"] == _sha(data)
    assert (settings.shared_storage / "big.bin").read_bytes() == data
