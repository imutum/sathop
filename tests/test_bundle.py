"""Worker bundle fetcher: orch:<name>@<version> parsing, orchestrator fetch
with mocked urllib, wrapper-dir flatten, ref-lock identity, manifest load.
Venv building is covered by the smoke tests (needs subprocess + ~5s)."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from sathop.worker import bundle


def _write_manifest(root: Path, name: str = "b", version: str = "0.1") -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "manifest.yaml").write_text(
        f"name: {name}\nversion: {version}\n"
        "execution:\n  entrypoint: 'true'\n"
        "outputs:\n  watch_dir: output\n",
        encoding="utf-8",
    )


def _make_zip(manifest_at: str = "manifest.yaml", extras: dict[str, str] | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            manifest_at,
            "name: z\nversion: 0.1\nexecution:\n  entrypoint: 'true'\noutputs:\n  watch_dir: output\n",
        )
        for k, v in (extras or {}).items():
            zf.writestr(k, v)
    return buf.getvalue()


# ─── ref parsing ──────────────────────────────────────────────────────────


def test_parse_ref_valid():
    assert bundle._parse_ref("orch:mod09a1-resample@0.1.0") == ("mod09a1-resample", "0.1.0")
    # multiple @ in name? last @ splits
    assert bundle._parse_ref("orch:name-with-at@1.0") == ("name-with-at", "1.0")


def test_parse_ref_wrong_scheme_raises():
    with pytest.raises(ValueError, match="must be 'orch:"):
        bundle._parse_ref("local:/tmp/x")
    with pytest.raises(ValueError):
        bundle._parse_ref("zip:https://example.com/b.zip")
    with pytest.raises(ValueError):
        bundle._parse_ref("git:https://github.com/u/r#main")


def test_parse_ref_missing_version_raises():
    with pytest.raises(ValueError, match="missing '@"):
        bundle._parse_ref("orch:no-version")


def test_parse_ref_empty_parts_raises():
    with pytest.raises(ValueError):
        bundle._parse_ref("orch:@1.0")
    with pytest.raises(ValueError):
        bundle._parse_ref("orch:name@")


# ─── per-ref lock identity ────────────────────────────────────────────────


def test_lock_for_returns_same_lock_per_ref():
    l1 = bundle._lock_for("orch:a@1.0")
    l2 = bundle._lock_for("orch:a@1.0")
    l3 = bundle._lock_for("orch:b@1.0")
    assert l1 is l2
    assert l1 is not l3


# ─── orchestrator fetch (urllib mocked) ──────────────────────────────────


class _FakeResp:
    def __init__(self, data: bytes, status: int = 200) -> None:
        self._data = data
        self.status = status

    def read(self) -> bytes:
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_fetch_from_orch_happy_path(tmp_path, monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout=120):
        captured["url"] = req.full_url
        captured["auth"] = req.headers.get("Authorization")
        return _FakeResp(_make_zip(), 200)

    monkeypatch.setattr(bundle.urllib.request, "urlopen", fake_urlopen)

    dest = tmp_path / "bundle"
    bundle._fetch_from_orch("http://orch:8000", "tok", "z", "0.1", dest)

    assert (dest / "manifest.yaml").is_file()
    assert captured["url"] == "http://orch:8000/api/bundles/z/0.1/download"
    assert captured["auth"] == "Bearer tok"


def test_fetch_from_orch_flattens_github_style_wrapper(tmp_path, monkeypatch):
    """Zips built from a parent dir (github zip-download style) have one wrapper
    dir at top. Fetcher must strip it so manifest.yaml ends up at `dest/`."""
    payload = _make_zip(manifest_at="wrap/manifest.yaml", extras={"wrap/process.py": "print('x')\n"})

    monkeypatch.setattr(
        bundle.urllib.request,
        "urlopen",
        lambda req, timeout=120: _FakeResp(payload, 200),
    )
    dest = tmp_path / "b"
    bundle._fetch_from_orch("http://orch:8000", "tok", "z", "0.1", dest)

    assert (dest / "manifest.yaml").is_file()
    assert (dest / "process.py").is_file()


def test_fetch_from_orch_http_error_raises_and_cleans(tmp_path, monkeypatch):
    monkeypatch.setattr(
        bundle.urllib.request,
        "urlopen",
        lambda req, timeout=120: _FakeResp(b"", 404),
    )
    dest = tmp_path / "bundle"
    with pytest.raises(RuntimeError, match="HTTP 404"):
        bundle._fetch_from_orch("http://orch:8000", "tok", "z", "0.1", dest)


def test_fetch_from_orch_missing_manifest_in_zip_raises(tmp_path, monkeypatch):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("randomfile.txt", "no manifest here\n")

    monkeypatch.setattr(
        bundle.urllib.request,
        "urlopen",
        lambda req, timeout=120: _FakeResp(buf.getvalue(), 200),
    )
    dest = tmp_path / "bundle"
    with pytest.raises(FileNotFoundError):
        bundle._fetch_from_orch("http://orch:8000", "tok", "z", "0.1", dest)
    assert not dest.exists()


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
        "inputs:\n  scheme: list\n"
        "execution:\n  entrypoint: 'python x.py'\n  timeout_sec: 60\n"
        "outputs:\n  watch_dir: out\n  extensions: ['.txt']\n"
        "requirements:\n  credentials: ['nasa']\n",
        encoding="utf-8",
    )
    m = bundle.BundleManifest.load(p)
    assert m.name == "demo"
    assert m.version == "1.2.3"
    assert m.execution["entrypoint"] == "python x.py"
    assert m.outputs["extensions"] == [".txt"]
    assert m.requirements["credentials"] == ["nasa"]
    assert m.shared_files == []


def test_bundle_manifest_load_shared_files(tmp_path):
    p = tmp_path / "manifest.yaml"
    p.write_text(
        "name: demo\nversion: 1\n"
        "execution:\n  entrypoint: 'true'\n"
        "outputs:\n  watch_dir: out\n"
        "shared_files:\n  - mask.tif\n  - dem.bin\n",
        encoding="utf-8",
    )
    m = bundle.BundleManifest.load(p)
    assert m.shared_files == ["mask.tif", "dem.bin"]


def test_bundle_manifest_rejects_malformed_shared_files(tmp_path):
    p = tmp_path / "manifest.yaml"
    p.write_text(
        "name: demo\nversion: 1\n"
        "execution:\n  entrypoint: 'true'\n"
        "outputs:\n  watch_dir: out\n"
        "shared_files:\n  - ''\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="non-empty strings"):
        bundle.BundleManifest.load(p)
