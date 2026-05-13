"""Worker bundle fetcher: orch:<name>@<version> parsing, orchestrator fetch
with mocked urllib, wrapper-dir flatten, ref-lock identity, manifest load.
Venv building is covered by the smoke tests (needs subprocess + ~5s)."""

from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

import httpx
import pytest

from sathop.shared.bundle_manifest import BundleManifest
from sathop.shared.bundle_python_deps import python_deps_source
from sathop.shared.protocol import parse_bundle_ref
from sathop.worker import bundle

_MANIFEST_TEMPLATE = (
    "name: {name}\nversion: '{version}'\n"
    "execution:\n  entrypoint: 'true'\n"
    "outputs:\n  watch_dir: output\n"
    "inputs:\n  slots:\n    - name: primary\n      product: any\n"
)


def _write_manifest(root: Path, name: str = "b", version: str = "0.1") -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "manifest.yaml").write_text(
        _MANIFEST_TEMPLATE.format(name=name, version=version),
        encoding="utf-8",
    )


def _make_zip(manifest_at: str = "manifest.yaml", extras: dict[str, str] | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(manifest_at, _MANIFEST_TEMPLATE.format(name="z", version="0.1"))
        for k, v in (extras or {}).items():
            zf.writestr(k, v)
    return buf.getvalue()


# ─── ref parsing ──────────────────────────────────────────────────────────


def test_parse_ref_valid():
    assert parse_bundle_ref("orch:mod09a1-resample@0.1.0") == ("mod09a1-resample", "0.1.0")
    # multiple @ in name? last @ splits
    assert parse_bundle_ref("orch:name-with-at@1.0") == ("name-with-at", "1.0")


def test_parse_ref_wrong_scheme_raises():
    with pytest.raises(ValueError, match="must start with 'orch:'"):
        parse_bundle_ref("local:/tmp/x")
    with pytest.raises(ValueError):
        parse_bundle_ref("zip:https://example.com/b.zip")
    with pytest.raises(ValueError):
        parse_bundle_ref("git:https://github.com/u/r#main")


def test_parse_ref_missing_version_raises():
    with pytest.raises(ValueError, match="missing '@"):
        parse_bundle_ref("orch:no-version")


def test_parse_ref_empty_parts_raises():
    with pytest.raises(ValueError):
        parse_bundle_ref("orch:@1.0")
    with pytest.raises(ValueError):
        parse_bundle_ref("orch:name@")


# ─── per-ref lock identity ────────────────────────────────────────────────


def test_lock_for_returns_same_lock_per_ref():
    l1 = bundle._ref_locks.get("orch:a@1.0")
    l2 = bundle._ref_locks.get("orch:a@1.0")
    l3 = bundle._ref_locks.get("orch:b@1.0")
    assert l1 is l2
    assert l1 is not l3


# ─── orchestrator fetch (httpx MockTransport) ──────────────────────────────


def _patch_fetch_client(monkeypatch, body: bytes, status: int = 200, capture: dict | None = None):
    def fake(orch_url: str, token: str, timeout: float = 120.0) -> httpx.Client:
        def handler(req: httpx.Request) -> httpx.Response:
            if capture is not None:
                capture["url"] = str(req.url)
                capture["auth"] = req.headers.get("Authorization")
            return httpx.Response(status, content=body)

        return httpx.Client(
            base_url=orch_url,
            timeout=timeout,
            headers={"Authorization": f"Bearer {token}"},
            transport=httpx.MockTransport(handler),
        )

    monkeypatch.setattr(bundle, "make_sync_orch_client", fake)


def test_fetch_from_orch_happy_path(tmp_path, monkeypatch):
    captured: dict = {}
    _patch_fetch_client(monkeypatch, _make_zip(), capture=captured)

    dest = tmp_path / "bundle"
    bundle._fetch_from_orch("http://orch:8000", "tok", "z", "0.1", dest)

    assert (dest / "manifest.yaml").is_file()
    assert captured["url"] == "http://orch:8000/api/bundles/z/0.1/download"
    assert captured["auth"] == "Bearer tok"


def test_fetch_from_orch_flattens_github_style_wrapper(tmp_path, monkeypatch):
    """Zips built from a parent dir (github zip-download style) have one wrapper
    dir at top. Fetcher must strip it so manifest.yaml ends up at `dest/`."""
    payload = _make_zip(manifest_at="wrap/manifest.yaml", extras={"wrap/process.py": "print('x')\n"})
    _patch_fetch_client(monkeypatch, payload)

    dest = tmp_path / "b"
    bundle._fetch_from_orch("http://orch:8000", "tok", "z", "0.1", dest)

    assert (dest / "manifest.yaml").is_file()
    assert (dest / "process.py").is_file()


def test_fetch_from_orch_http_error_raises_and_cleans(tmp_path, monkeypatch):
    _patch_fetch_client(monkeypatch, b"", status=404)
    dest = tmp_path / "bundle"
    with pytest.raises(RuntimeError, match="HTTP 404"):
        bundle._fetch_from_orch("http://orch:8000", "tok", "z", "0.1", dest)


def test_fetch_from_orch_missing_manifest_in_zip_raises(tmp_path, monkeypatch):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("randomfile.txt", "no manifest here\n")
    _patch_fetch_client(monkeypatch, buf.getvalue())

    dest = tmp_path / "bundle"
    with pytest.raises(FileNotFoundError):
        bundle._fetch_from_orch("http://orch:8000", "tok", "z", "0.1", dest)
    assert not dest.exists()


def test_fetch_from_orch_rejects_archive_path_traversal(tmp_path, monkeypatch):
    payload = _make_zip(extras={"../evil.txt": "x"})
    _patch_fetch_client(monkeypatch, payload)

    dest = tmp_path / "bundle"
    with pytest.raises(ValueError, match="escapes target directory"):
        bundle._fetch_from_orch("http://orch:8000", "tok", "z", "0.1", dest)
    assert not dest.exists()
    assert not (tmp_path / "evil.txt").exists()


# ─── flatten wrapper ──────────────────────────────────────────────────────


def test_flatten_wrapper_dir_strips_single_wrapper(tmp_path):
    dest = tmp_path / "d"
    _write_manifest(dest / "myrepo-main", name="inside")

    bundle._flatten_wrapper_dir(dest)

    assert (dest / "manifest.yaml").is_file()
    assert not (dest / "myrepo-main").exists()


def test_flatten_wrapper_dir_noop_when_manifest_already_at_root(tmp_path):
    dest = tmp_path / "d"
    _write_manifest(dest)
    (dest / "extra-dir").mkdir()

    bundle._flatten_wrapper_dir(dest)

    assert (dest / "manifest.yaml").is_file()
    assert (dest / "extra-dir").is_dir()


def test_flatten_wrapper_dir_noop_when_multiple_top_entries(tmp_path):
    dest = tmp_path / "d"
    dest.mkdir()
    (dest / "a").mkdir()
    (dest / "b").mkdir()

    bundle._flatten_wrapper_dir(dest)

    assert (dest / "a").is_dir()
    assert (dest / "b").is_dir()


# ─── manifest loader ──────────────────────────────────────────────────────


def test_bundle_manifest_load(tmp_path):
    p = tmp_path / "manifest.yaml"
    p.write_text(
        "name: demo\nversion: 1.2.3\n"
        "inputs:\n  slots:\n    - name: primary\n      product: any\n"
        "execution:\n  entrypoint: 'python x.py'\n  timeout_sec: 60\n"
        "outputs:\n  watch_dir: out\n  extensions: ['.txt']\n"
        "requirements:\n  credentials: ['nasa']\n",
        encoding="utf-8",
    )
    m = BundleManifest.from_yaml(p)
    assert m.name == "demo"
    assert m.version == "1.2.3"
    assert m.execution.entrypoint == "python x.py"
    assert m.outputs.extensions == (".txt",)
    assert m.requirements.credentials == ("nasa",)
    assert m.shared_files == ()


def test_bundle_manifest_load_shared_files(tmp_path):
    p = tmp_path / "manifest.yaml"
    p.write_text(
        _MANIFEST_TEMPLATE.format(name="demo", version="1") + "shared_files:\n  - mask.tif\n  - dem.bin\n",
        encoding="utf-8",
    )
    m = BundleManifest.from_yaml(p)
    assert m.shared_files == ("mask.tif", "dem.bin")


def test_bundle_manifest_rejects_malformed_shared_files(tmp_path):
    p = tmp_path / "manifest.yaml"
    p.write_text(
        _MANIFEST_TEMPLATE.format(name="demo", version="1") + "shared_files:\n  - ''\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="non-empty string"):
        BundleManifest.from_yaml(p)


# ─── runtime selection ───────────────────────────────────────────────────


def test_ensure_reuses_worker_python_when_bundle_has_no_python_deps(tmp_path, monkeypatch):
    cache_root = tmp_path / "bundles"
    bundle_dir = cache_root / "z@0.1"
    _write_manifest(bundle_dir, name="z", version="0.1")

    def fail_run(*_args, **_kwargs):
        raise AssertionError("venv creation should not run for dependency-free bundles")

    monkeypatch.setattr(bundle.subprocess, "run", fail_run)

    handle = bundle.ensure(
        "orch:z@0.1", cache_root, tmp_path / "venvs", tmp_path / "shared", "http://orch", "tok"
    )

    assert handle.python == Path(sys.executable)
    assert (tmp_path / "venvs" / bundle._LAST_USED_DIR / "z@0.1").is_file()


def test_ensure_builds_cached_venv_when_python_deps_are_declared(tmp_path, monkeypatch):
    cache_root = tmp_path / "bundles"
    bundle_dir = cache_root / "z@0.1"
    _write_manifest(bundle_dir, name="z", version="0.1")
    (bundle_dir / "requirements.txt").write_text("numpy\n", encoding="utf-8")
    fake_python = (
        tmp_path / "venvs" / "z@0.1" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    )

    monkeypatch.setattr(bundle, "_ensure_venv", lambda *_args: fake_python)

    handle = bundle.ensure(
        "orch:z@0.1", cache_root, tmp_path / "venvs", tmp_path / "shared", "http://orch", "tok"
    )

    assert handle.python == fake_python
    assert (tmp_path / "venvs" / bundle._LAST_USED_DIR / "z@0.1").is_file()


def test_requirements_comments_only_do_not_force_venv(tmp_path):
    root = tmp_path / "b"
    _write_manifest(root)
    (root / "requirements.txt").write_text("\n# stdlib only\n", encoding="utf-8")
    manifest = BundleManifest.from_yaml(root / "manifest.yaml")

    assert python_deps_source(manifest.requirements, root) is None
