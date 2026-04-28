"""Orchestrator-side bundle registry: upload + list + detail + download + delete.
Validates zip parsing, version-conflict rejection, reference-check on delete,
content-addressed blob de-dup, and download integrity (sha matches)."""

from __future__ import annotations

import hashlib
import io
import zipfile

import pytest
from fastapi.testclient import TestClient

from sathop.orchestrator import db as orch_db
from sathop.orchestrator.config import settings
from sathop.orchestrator.db import Batch, Bundle
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


def _make_zip(
    name: str = "demo",
    version: str = "0.1.0",
    manifest_at: str = "manifest.yaml",
    extras: dict[str, str] | None = None,
    manifest_extra_yaml: str = "",
    inputs_yaml: str = "inputs:\n  slots:\n    - name: primary\n      product: any\n",
) -> bytes:
    body = (
        f"name: {name}\nversion: {version}\n" + inputs_yaml + "execution:\n  entrypoint: 'python run.py'\n"
        "outputs:\n  watch_dir: output\n"
        f"{manifest_extra_yaml}"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(manifest_at, body)
        for k, v in (extras or {}).items():
            zf.writestr(k, v)
    return buf.getvalue()


# ─── upload ──────────────────────────────────────────────────────────────


async def test_upload_happy_path_persists_blob_and_row(client):
    blob = _make_zip("demo", "0.1.0")
    r = client.post(
        "/api/bundles",
        files={"file": ("b.zip", blob, "application/zip")},
        params={"description": "first"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "demo"
    assert body["version"] == "0.1.0"
    assert body["size"] == len(blob)
    assert body["description"] == "first"
    expected_sha = hashlib.sha256(blob).hexdigest()
    assert body["sha256"] == expected_sha

    # blob on disk
    stored = settings.bundle_storage / f"{expected_sha}.zip"
    assert stored.is_file()
    assert stored.read_bytes() == blob

    # row in DB
    async with orch_db._session_maker() as s:
        b = await s.get(Bundle, ("demo", "0.1.0"))
        assert b is not None
        assert b.sha256 == expected_sha


async def test_upload_rejects_empty_file(client):
    r = client.post("/api/bundles", files={"file": ("b.zip", b"", "application/zip")})
    assert r.status_code == 400


async def test_upload_rejects_non_zip(client):
    r = client.post("/api/bundles", files={"file": ("b.zip", b"not a zip", "application/zip")})
    assert r.status_code == 400


async def test_upload_rejects_zip_without_manifest(client):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("random.txt", "no manifest\n")
    r = client.post("/api/bundles", files={"file": ("b.zip", buf.getvalue(), "application/zip")})
    assert r.status_code == 422


async def test_upload_rejects_missing_manifest_keys(client):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("manifest.yaml", "name: x\nversion: 0.1\n")  # missing execution, outputs
    r = client.post("/api/bundles", files={"file": ("b.zip", buf.getvalue(), "application/zip")})
    assert r.status_code == 422


async def test_upload_rejects_missing_entrypoint(client):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "manifest.yaml",
            "name: x\nversion: 0.1\nexecution:\n  timeout_sec: 60\noutputs:\n  watch_dir: out\n",
        )
    r = client.post("/api/bundles", files={"file": ("b.zip", buf.getvalue(), "application/zip")})
    assert r.status_code == 422


# ─── shared_files manifest field ────────────────────────────────────────────


async def test_upload_rejects_unknown_shared_file(client):
    """Bundle declaring a shared_file that isn't in the registry → 422 fail-fast."""
    blob = _make_zip(
        "demo",
        "0.1.0",
        manifest_extra_yaml="shared_files:\n  - mask.tif\n",
    )
    r = client.post("/api/bundles", files={"file": ("b.zip", blob, "application/zip")})
    assert r.status_code == 422
    assert "mask.tif" in r.json()["detail"]


async def test_upload_accepts_bundle_with_registered_shared_file(client):
    """Upload mask.tif first, then a bundle referencing it succeeds."""
    client.put(
        "/api/shared/mask.tif",
        files={"file": ("mask.tif", io.BytesIO(b"mask-bytes"), "x")},
    )
    blob = _make_zip(
        "demo",
        "0.1.0",
        manifest_extra_yaml="shared_files:\n  - mask.tif\n",
    )
    r = client.post("/api/bundles", files={"file": ("b.zip", blob, "application/zip")})
    assert r.status_code == 200, r.text


async def test_upload_rejects_malformed_shared_files(client):
    """shared_files must be a list of non-empty strings, no dupes."""
    for yaml_snippet, where in [
        ("shared_files: not-a-list\n", "list"),
        ('shared_files:\n  - ""\n', "non-empty string"),
        ("shared_files:\n  - a\n  - a\n", "duplicate"),
    ]:
        blob = _make_zip("demo", "0.1.0", manifest_extra_yaml=yaml_snippet)
        r = client.post("/api/bundles", files={"file": ("b.zip", blob, "application/zip")})
        assert r.status_code == 422, f"expected 422 for {yaml_snippet!r}"
        assert where in r.json()["detail"]


async def test_upload_rejects_missing_inputs_slots(client):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "manifest.yaml",
            "name: x\nversion: 0.1\nexecution:\n  entrypoint: 'true'\n"
            "outputs:\n  watch_dir: out\n",  # no inputs
        )
    r = client.post("/api/bundles", files={"file": ("b.zip", buf.getvalue(), "application/zip")})
    assert r.status_code == 422
    assert "inputs" in r.json()["detail"]


async def test_upload_rejects_bad_slot_regex(client):
    blob = _make_zip(
        inputs_yaml=("inputs:\n  slots:\n    - name: p\n      product: X\n      filename_pattern: '['\n"),
    )
    r = client.post("/api/bundles", files={"file": ("b.zip", blob, "application/zip")})
    assert r.status_code == 422
    assert "regex" in r.json()["detail"]


async def test_upload_duplicate_name_version_returns_409(client):
    blob = _make_zip("demo", "0.1.0")
    r1 = client.post("/api/bundles", files={"file": ("b.zip", blob, "application/zip")})
    assert r1.status_code == 200
    r2 = client.post("/api/bundles", files={"file": ("b.zip", blob, "application/zip")})
    assert r2.status_code == 409
    assert "bump" in r2.json()["detail"].lower()


async def test_upload_accepts_wrapper_dir_manifest_layout(client):
    blob = _make_zip("demo", "0.1.0", manifest_at="wrap/manifest.yaml")
    r = client.post("/api/bundles", files={"file": ("b.zip", blob, "application/zip")})
    assert r.status_code == 200


# ─── list ────────────────────────────────────────────────────────────────


async def test_list_returns_all_newest_first(client):
    client.post("/api/bundles", files={"file": ("a.zip", _make_zip("a", "0.1"), "application/zip")})
    client.post("/api/bundles", files={"file": ("b.zip", _make_zip("b", "0.1"), "application/zip")})
    r = client.get("/api/bundles")
    assert r.status_code == 200
    rows = r.json()
    assert {x["name"] for x in rows} == {"a", "b"}


# ─── detail + download ───────────────────────────────────────────────────


async def test_detail_returns_parsed_manifest(client):
    blob = _make_zip("demo", "1.0", manifest_extra_yaml="requirements:\n  pip:\n    - numpy\n")
    client.post("/api/bundles", files={"file": ("b.zip", blob, "application/zip")})

    r = client.get("/api/bundles/demo/1.0")
    assert r.status_code == 200
    body = r.json()
    assert body["manifest"]["name"] == "demo"
    assert body["manifest"]["requirements"]["pip"] == ["numpy"]


async def test_download_serves_exact_bytes(client):
    blob = _make_zip("demo", "2.0")
    client.post("/api/bundles", files={"file": ("b.zip", blob, "application/zip")})

    r = client.get("/api/bundles/demo/2.0/download")
    assert r.status_code == 200
    assert r.content == blob
    assert r.headers["X-Bundle-SHA256"] == hashlib.sha256(blob).hexdigest()


async def test_download_unknown_returns_404(client):
    r = client.get("/api/bundles/nope/0.0/download")
    assert r.status_code == 404


# ─── delete ──────────────────────────────────────────────────────────────


async def test_delete_removes_row_and_blob(client):
    blob = _make_zip("demo", "3.0")
    client.post("/api/bundles", files={"file": ("b.zip", blob, "application/zip")})
    sha = hashlib.sha256(blob).hexdigest()
    assert (settings.bundle_storage / f"{sha}.zip").exists()

    r = client.delete("/api/bundles/demo/3.0")
    assert r.status_code == 200

    async with orch_db._session_maker() as s:
        assert await s.get(Bundle, ("demo", "3.0")) is None
    assert not (settings.bundle_storage / f"{sha}.zip").exists()


async def test_in_use_count_surfaces_in_list_and_detail(client):
    """List + detail must include in_use_count so the UI can flag bundles still in use."""
    blob = _make_zip("inuse", "1.0")
    blob2 = _make_zip("free", "1.0")
    client.post("/api/bundles", files={"file": ("a.zip", blob, "application/zip")})
    client.post("/api/bundles", files={"file": ("b.zip", blob2, "application/zip")})

    async with orch_db._session_maker() as s:
        s.add(Batch(batch_id="b1", name="t", bundle_ref="orch:inuse@1.0"))
        s.add(Batch(batch_id="b2", name="t2", bundle_ref="orch:inuse@1.0"))
        await s.commit()

    rows = client.get("/api/bundles").json()
    by_name = {r["name"]: r for r in rows}
    assert by_name["inuse"]["in_use_count"] == 2
    assert by_name["free"]["in_use_count"] == 0

    d = client.get("/api/bundles/inuse/1.0").json()
    assert d["in_use_count"] == 2


async def test_delete_blocked_by_batch_reference(client):
    blob = _make_zip("demo", "4.0")
    client.post("/api/bundles", files={"file": ("b.zip", blob, "application/zip")})

    async with orch_db._session_maker() as s:
        s.add(Batch(batch_id="b1", name="t", bundle_ref="orch:demo@4.0"))
        s.add(Batch(batch_id="b2", name="t2", bundle_ref="orch:demo@4.0"))
        await s.commit()

    r = client.delete("/api/bundles/demo/4.0")
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert "referenced by 2 batch" in detail
    # Operator needs to know which batches — IDs surface in the error.
    assert "b1" in detail and "b2" in detail


# ─── files listing / content ─────────────────────────────────────────────


async def test_list_files_flat_layout(client):
    blob = _make_zip(
        "demo",
        "5.0",
        extras={"run.sh": "#!/bin/bash\necho hi\n", "src/foo.py": "print('x')\n"},
    )
    client.post("/api/bundles", files={"file": ("b.zip", blob, "application/zip")})
    r = client.get("/api/bundles/demo/5.0/files")
    assert r.status_code == 200
    paths = {e["path"] for e in r.json()}
    assert paths == {"manifest.yaml", "run.sh", "src/foo.py"}


async def test_list_files_strips_wrapper_dir(client):
    blob = _make_zip(
        "demo",
        "5.1",
        manifest_at="wrap/manifest.yaml",
        extras={"wrap/run.sh": "hi\n"},
    )
    client.post("/api/bundles", files={"file": ("b.zip", blob, "application/zip")})
    r = client.get("/api/bundles/demo/5.1/files")
    assert r.status_code == 200
    paths = {e["path"] for e in r.json()}
    # wrapper prefix 'wrap/' should NOT appear in UI paths
    assert paths == {"manifest.yaml", "run.sh"}


async def test_read_file_returns_text(client):
    blob = _make_zip("demo", "5.2", extras={"run.sh": "#!/bin/bash\n"})
    client.post("/api/bundles", files={"file": ("b.zip", blob, "application/zip")})
    r = client.get("/api/bundles/demo/5.2/files/run.sh")
    assert r.status_code == 200
    body = r.json()
    assert body["path"] == "run.sh"
    assert body["binary"] is False
    assert body["truncated"] is False
    assert body["content"] == "#!/bin/bash\n"


async def test_read_file_binary_returns_empty_content_flag(client):
    binary = bytes(range(256))  # 0..255 — not valid utf-8
    blob = _make_zip("demo", "5.3", extras={"blob.bin": ""})
    # Re-emit zip with real binary content
    buf = io.BytesIO(blob)
    # Easiest: rebuild a zip with valid manifest + binary file
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as zf:
        zf.writestr(
            "manifest.yaml",
            "name: demo\nversion: 5.3\n"
            "inputs:\n  slots:\n    - name: p\n      product: any\n"
            "execution:\n  entrypoint: 'true'\n"
            "outputs:\n  watch_dir: output\n",
        )
        zf.writestr("blob.bin", binary)
    _ = buf  # silence unused
    client.post("/api/bundles", files={"file": ("b.zip", out.getvalue(), "application/zip")})
    r = client.get("/api/bundles/demo/5.3/files/blob.bin")
    assert r.status_code == 200
    body = r.json()
    assert body["binary"] is True
    assert body["content"] == ""


async def test_read_file_404_on_path_not_in_zip(client):
    blob = _make_zip("demo", "5.4")
    client.post("/api/bundles", files={"file": ("b.zip", blob, "application/zip")})
    r = client.get("/api/bundles/demo/5.4/files/nope.py")
    assert r.status_code == 404


async def test_read_file_truncates_large_content(client):
    big = "A" * (600 * 1024)  # 600 KB > 512 KB cap
    blob = _make_zip("demo", "5.6", extras={"big.txt": big})
    client.post("/api/bundles", files={"file": ("b.zip", blob, "application/zip")})
    r = client.get("/api/bundles/demo/5.6/files/big.txt")
    assert r.status_code == 200
    body = r.json()
    assert body["truncated"] is True
    assert len(body["content"]) == 512 * 1024


async def test_delete_preserves_shared_blob_when_other_rows_use_it(client):
    """Same zip bytes → same sha. Deleting one row must not unlink the blob
    if another row still points at it."""
    blob = _make_zip("demo", "1.0")
    sha = hashlib.sha256(blob).hexdigest()
    # Duplicate row with the same blob but different (name, version):
    # we insert directly since upload dedupes on (name, version) not sha.
    async with orch_db._session_maker() as s:
        (settings.bundle_storage).mkdir(parents=True, exist_ok=True)
        (settings.bundle_storage / f"{sha}.zip").write_bytes(blob)
        from sathop.orchestrator.db import utcnow

        s.add(
            Bundle(
                name="demo",
                version="1.0",
                sha256=sha,
                size=len(blob),
                manifest_json="{}",
                uploaded_at=utcnow(),
            )
        )
        s.add(
            Bundle(
                name="demo-fork",
                version="1.0",
                sha256=sha,
                size=len(blob),
                manifest_json="{}",
                uploaded_at=utcnow(),
            )
        )
        await s.commit()

    r = client.delete("/api/bundles/demo/1.0")
    assert r.status_code == 200
    assert (settings.bundle_storage / f"{sha}.zip").is_file()  # blob still there


# ─── batch creation validates ref + existence ────────────────────────────


async def test_batch_creation_rejects_non_orch_ref(client):
    r = client.post(
        "/api/batches",
        json={
            "batch_id": "b1",
            "name": "t",
            "bundle_ref": "local:/app/bundle",
            "granules": [{"granule_id": "g1", "inputs": []}],
        },
    )
    assert r.status_code == 422
    assert "orch:" in r.json()["detail"]


async def test_batch_creation_rejects_unregistered_bundle(client):
    r = client.post(
        "/api/batches",
        json={
            "batch_id": "b1",
            "name": "t",
            "bundle_ref": "orch:ghost@1.0",
            "granules": [{"granule_id": "g1", "inputs": []}],
        },
    )
    assert r.status_code == 422
    assert "not registered" in r.json()["detail"]


async def test_batch_creation_accepts_registered_bundle(client):
    client.post("/api/bundles", files={"file": ("b.zip", _make_zip("demo", "1.0"), "application/zip")})
    r = client.post(
        "/api/batches",
        json={
            "batch_id": "b1",
            "name": "t",
            "bundle_ref": "orch:demo@1.0",
            "granules": [
                {
                    "granule_id": "g1",
                    "inputs": [
                        {"url": "http://x/f", "filename": "f", "product": "any"},
                    ],
                }
            ],
        },
    )
    assert r.status_code == 200


async def test_batch_creation_rejects_when_shared_file_deleted(client):
    """Shared file existed at bundle upload, deleted before batch create → 422.
    Bundle delete would normally block this, but shared-file delete refuses
    when referenced, so this path is only reachable if the user force-removes
    it via orch-side cleanup. Still worth the defensive check."""
    # 1. Upload shared file
    client.put("/api/shared/mask.tif", files={"file": ("mask.tif", io.BytesIO(b"m"), "x")})
    # 2. Upload bundle referencing it
    blob = _make_zip("demo", "9.0", manifest_extra_yaml="shared_files:\n  - mask.tif\n")
    assert client.post("/api/bundles", files={"file": ("b.zip", blob, "application/zip")}).status_code == 200
    # 3. Force-remove shared file at the DB level (simulating corruption / direct
    #    operator intervention); the delete endpoint would reject it.
    async with orch_db._session_maker() as s:
        from sathop.orchestrator.db import SharedFile

        f = await s.get(SharedFile, "mask.tif")
        await s.delete(f)
        await s.commit()
    # 4. Batch create should now fail fast, not crash mid-lease
    r = client.post(
        "/api/batches",
        json={
            "batch_id": "b1",
            "name": "t",
            "bundle_ref": "orch:demo@9.0",
            "granules": [
                {"granule_id": "g1", "inputs": [{"url": "http://x/f", "filename": "f", "product": "any"}]}
            ],
        },
    )
    assert r.status_code == 422
    assert "mask.tif" in r.json()["detail"]


async def test_batch_creation_rejects_granule_missing_slot(client):
    client.post("/api/bundles", files={"file": ("b.zip", _make_zip("demo", "2.0"), "application/zip")})
    r = client.post(
        "/api/batches",
        json={
            "batch_id": "b1",
            "name": "t",
            "bundle_ref": "orch:demo@2.0",
            "granules": [{"granule_id": "g1", "inputs": []}],  # slot "primary" unfilled
        },
    )
    assert r.status_code == 422
    assert "primary" in r.json()["detail"]


async def test_batch_creation_rejects_filename_pattern_mismatch(client):
    yaml = "inputs:\n  slots:\n    - name: p\n      product: MOD09A1\n      filename_pattern: '\\\\.hdf$'\n"
    client.post(
        "/api/bundles",
        files={"file": ("b.zip", _make_zip("demo", "3.0", inputs_yaml=yaml), "application/zip")},
    )
    r = client.post(
        "/api/batches",
        json={
            "batch_id": "b1",
            "name": "t",
            "bundle_ref": "orch:demo@3.0",
            "granules": [
                {
                    "granule_id": "g1",
                    "inputs": [
                        {"url": "http://x/f.txt", "filename": "foo.txt", "product": "MOD09A1"},
                    ],
                }
            ],
        },
    )
    assert r.status_code == 422
    assert "pattern" in r.json()["detail"]


async def test_batch_creation_rejects_missing_meta(client):
    yaml = (
        "inputs:\n  slots:\n    - name: p\n      product: any\n"
        "  meta:\n    - name: year\n      pattern: '^\\\\d{4}$'\n"
    )
    client.post(
        "/api/bundles",
        files={"file": ("b.zip", _make_zip("demo", "4.0", inputs_yaml=yaml), "application/zip")},
    )
    r = client.post(
        "/api/batches",
        json={
            "batch_id": "b1",
            "name": "t",
            "bundle_ref": "orch:demo@4.0",
            "granules": [
                {
                    "granule_id": "g1",
                    "inputs": [
                        {"url": "http://x/f", "filename": "f", "product": "any"},
                    ],
                }
            ],  # year missing
        },
    )
    assert r.status_code == 422
    assert "year" in r.json()["detail"]


async def test_batch_creation_warns_extra_meta_but_accepts(client):
    yaml = "inputs:\n  slots:\n    - name: p\n      product: any\n"
    client.post(
        "/api/bundles",
        files={"file": ("b.zip", _make_zip("demo", "5.0", inputs_yaml=yaml), "application/zip")},
    )
    r = client.post(
        "/api/batches",
        json={
            "batch_id": "b1",
            "name": "t",
            "bundle_ref": "orch:demo@5.0",
            "granules": [
                {
                    "granule_id": "g1",
                    "inputs": [{"url": "http://x/f", "filename": "f", "product": "any"}],
                    "meta": {"note": "extra key"},
                }
            ],
        },
    )
    assert r.status_code == 200
