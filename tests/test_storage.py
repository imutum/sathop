"""LocalStorage: put() moves file + computes sha/size + builds presigned URL;
delete() cleans file and recursively-removes-empty parents up to root.

Storage protocol is async (M-016) so MinIO calls don't block the event loop;
LocalStorage keeps the signature for symmetry even though its body is sync."""

from __future__ import annotations

import hashlib
from pathlib import Path

from sathop.worker.storage import LocalStorage, render_key


async def test_put_moves_file_and_reports_sha_and_size(tmp_path):
    src = tmp_path / "src.bin"
    data = b"hello world " * 100
    src.write_bytes(data)

    s = LocalStorage(root=tmp_path / "store", public_base_url="http://w1.example.com:9000")
    obj = await s.put(src, "batch-a/granule-1/out.bin")

    assert not src.exists()  # move, not copy
    dst = tmp_path / "store" / "batch-a" / "granule-1" / "out.bin"
    assert dst.read_bytes() == data
    assert obj.object_key == "batch-a/granule-1/out.bin"
    assert obj.size == len(data)
    assert obj.sha256 == hashlib.sha256(data).hexdigest()
    assert obj.presigned_url == "http://w1.example.com:9000/batch-a/granule-1/out.bin"


async def test_delete_removes_file_and_empty_parent_dirs(tmp_path):
    root = tmp_path / "store"
    s = LocalStorage(root=root, public_base_url="http://w1.example.com:9000")
    src = tmp_path / "x.bin"
    src.write_bytes(b"x")

    await s.put(src, "b1/g1/x.bin")
    assert (root / "b1" / "g1" / "x.bin").exists()

    await s.delete("b1/g1/x.bin")

    assert not (root / "b1" / "g1" / "x.bin").exists()
    # Empty parent dirs are swept up to the root...
    assert not (root / "b1" / "g1").exists()
    assert not (root / "b1").exists()
    # ...but the root itself stays.
    assert root.is_dir()


async def test_delete_stops_at_non_empty_sibling(tmp_path):
    """One granule under a batch gets deleted; a sibling still present → batch dir stays."""
    root = tmp_path / "store"
    s = LocalStorage(root=root, public_base_url="http://w1.example.com:9000")
    a = tmp_path / "a.bin"
    a.write_bytes(b"a")
    b = tmp_path / "b.bin"
    b.write_bytes(b"b")
    await s.put(a, "batch/g1/a.bin")
    await s.put(b, "batch/g2/b.bin")

    await s.delete("batch/g1/a.bin")

    assert not (root / "batch" / "g1").exists()
    assert (root / "batch" / "g2" / "b.bin").exists()
    assert (root / "batch").is_dir()


async def test_delete_missing_key_is_noop(tmp_path):
    root = tmp_path / "store"
    s = LocalStorage(root=root, public_base_url="http://w1.example.com:9000")
    # No exception; no side effect on root
    await s.delete("never-existed/file.bin")
    assert root.is_dir()


async def test_put_creates_nested_parents(tmp_path):
    src = tmp_path / "src.bin"
    src.write_bytes(b"deep")
    s = LocalStorage(root=tmp_path / "store", public_base_url="http://x")
    await s.put(src, "a/b/c/d/e/f.bin")
    assert (tmp_path / "store" / "a" / "b" / "c" / "d" / "e" / "f.bin").exists()


def test_needs_static_server_flag(tmp_path):
    s = LocalStorage(root=tmp_path / "store", public_base_url="http://x")
    assert s.needs_static_server is True


# ─── render_key ────────────────────────────────────────────────────────────


def test_render_key_basic_stem_ext_name():
    p = Path("/tmp/MOD09A1.A2024.tif")
    assert render_key("{stem}{ext}", p, {}) == "MOD09A1.A2024.tif"
    assert render_key("{name}", p, {}) == "MOD09A1.A2024.tif"
    assert render_key("{stem}", p, {}) == "MOD09A1.A2024"
    assert render_key("{ext}", p, {}) == ".tif"


def test_render_key_with_meta_fields():
    p = Path("/tmp/out.tif")
    assert render_key("y{year}/{stem}{ext}", p, {"year": 2024}) == "y2024/out.tif"


def test_render_key_meta_values_stringified():
    """Non-string meta values are str()-coerced (granule_id may be int internally)."""
    p = Path("/tmp/out.tif")
    assert render_key("{gid}/{stem}", p, {"gid": 42}) == "42/out"


def test_render_key_falls_back_to_name_on_missing_placeholder():
    """An unknown {placeholder} → fall back to bare filename rather than crash."""
    p = Path("/tmp/out.tif")
    assert render_key("{nope}/{stem}", p, {}) == "out.tif"


def test_render_key_user_meta_overrides_built_in():
    """If `meta` provides `stem`, it wins over the auto-derived one. Documents
    the actual behaviour — built-ins are seeded first and overwritten by **meta."""
    p = Path("/tmp/out.tif")
    assert render_key("{stem}{ext}", p, {"stem": "user"}) == "user.tif"
