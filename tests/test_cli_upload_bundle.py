"""CLI `sathop-upload-bundle`: zip a bundle directory and POST to orchestrator.

Tests fall into two layers:
  • pure: `_should_include` filter and `_build_zip` shape (manifest required,
    excluded suffixes/names, YAML parse errors).
  • integration: `main()` happy path + 409 dup + 4xx error paths via
    `httpx.Client` patched with a MockTransport.
"""

from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

import httpx
import pytest

from sathop.cli import upload_bundle

# ─── _should_include ────────────────────────────────────────────────────────


def _touch(p: Path, body: str = "x") -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return p


def test_should_include_keeps_regular_files(tmp_path: Path):
    root = tmp_path
    f = _touch(root / "main.py")
    assert upload_bundle._should_include(f, root) is True


def test_should_include_drops_dunder_pycache(tmp_path: Path):
    f = _touch(tmp_path / "pkg" / "__pycache__" / "foo.cpython-311.pyc")
    assert upload_bundle._should_include(f, tmp_path) is False


def test_should_include_drops_hidden_dirs(tmp_path: Path):
    assert upload_bundle._should_include(_touch(tmp_path / ".git" / "HEAD"), tmp_path) is False
    assert upload_bundle._should_include(_touch(tmp_path / ".mypy_cache" / "x.json"), tmp_path) is False


def test_should_include_keeps_env_example(tmp_path: Path):
    """`.env.example` is the only dotfile we deliberately ship."""
    f = _touch(tmp_path / ".env.example")
    assert upload_bundle._should_include(f, tmp_path) is True


def test_should_include_drops_compiled_python(tmp_path: Path):
    assert upload_bundle._should_include(_touch(tmp_path / "x.pyc"), tmp_path) is False
    assert upload_bundle._should_include(_touch(tmp_path / "x.pyo"), tmp_path) is False


# ─── _build_zip ─────────────────────────────────────────────────────────────


def _write_manifest(d: Path, name: str = "demo", version: str = "0.1") -> None:
    (d / "manifest.yaml").write_text(
        f"name: {name}\nversion: {version}\n"
        "inputs:\n  slots:\n    - name: p\n      product: any\n"
        "execution:\n  entrypoint: 'python run.py'\n"
        "outputs:\n  watch_dir: output\n",
        encoding="utf-8",
    )


def test_build_zip_contains_manifest_and_skips_excluded(tmp_path: Path):
    bdir = tmp_path / "bundle"
    bdir.mkdir()
    _write_manifest(bdir)
    _touch(bdir / "run.py", "print('hi')")
    # Should be skipped
    _touch(bdir / "__pycache__" / "run.cpython-311.pyc")
    _touch(bdir / ".git" / "HEAD")
    _touch(bdir / "compiled.pyc")

    blob = upload_bundle._build_zip(bdir)
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        names = set(zf.namelist())
    assert "manifest.yaml" in names
    assert "run.py" in names
    assert not any(".git/" in n or "__pycache__/" in n or n.endswith(".pyc") for n in names)


def test_build_zip_missing_manifest_exits(tmp_path: Path):
    bdir = tmp_path / "no-manifest"
    bdir.mkdir()
    with pytest.raises(SystemExit) as exc:
        upload_bundle._build_zip(bdir)
    assert "manifest.yaml not found" in str(exc.value)


def test_build_zip_bad_yaml_exits(tmp_path: Path):
    bdir = tmp_path / "broken"
    bdir.mkdir()
    (bdir / "manifest.yaml").write_text("name: x\n: : :\n", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        upload_bundle._build_zip(bdir)
    assert "parse failed" in str(exc.value)


def test_build_zip_manifest_without_required_fields_exits(tmp_path: Path):
    bdir = tmp_path / "incomplete"
    bdir.mkdir()
    (bdir / "manifest.yaml").write_text("description: oops\n", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        upload_bundle._build_zip(bdir)
    assert "name" in str(exc.value) and "version" in str(exc.value)


# ─── main() — wired via MockTransport ─────────────────────────────────────


def _install_orch(monkeypatch: pytest.MonkeyPatch, handler) -> list[httpx.Request]:
    captured: list[httpx.Request] = []

    def wrapped(req: httpx.Request) -> httpx.Response:
        captured.append(req)
        return handler(req)

    transport = httpx.MockTransport(wrapped)
    original = httpx.Client

    def patched(**kwargs: object) -> httpx.Client:
        kwargs["transport"] = transport
        return original(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(upload_bundle.httpx, "Client", patched)
    return captured


def _valid_bundle(tmp_path: Path) -> Path:
    bdir = tmp_path / "bundle"
    bdir.mkdir()
    _write_manifest(bdir)
    _touch(bdir / "run.py", "print('hi')")
    return bdir


def _ok_upload(req: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"name": "demo", "version": "0.1", "sha256": "0" * 64, "size": 1})


def test_upload_happy_path_exits_zero(tmp_path: Path, monkeypatch, capsys):
    bdir = _valid_bundle(tmp_path)

    def ok(req: httpx.Request) -> httpx.Response:
        assert req.method == "POST"
        assert req.url.path == "/api/bundles"
        return httpx.Response(200, json={"name": "demo", "version": "0.1", "sha256": "a" * 64, "size": 123})

    _install_orch(monkeypatch, ok)
    monkeypatch.setattr(
        sys,
        "argv",
        ["sathop-upload-bundle", str(bdir), "--orch-url", "http://x", "--token", "tok", "--skip-validate"],
    )
    assert upload_bundle.main() == 0
    out = capsys.readouterr().out
    assert "zipped bundle" in out
    assert "uploaded demo@0.1" in out


def test_upload_409_conflict_prompts_version_bump(tmp_path: Path, monkeypatch):
    bdir = _valid_bundle(tmp_path)

    def conflict(req: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json={"detail": "demo@0.1 already exists"})

    _install_orch(monkeypatch, conflict)
    monkeypatch.setattr(
        sys,
        "argv",
        ["sathop-upload-bundle", str(bdir), "--orch-url", "http://x", "--token", "tok", "--skip-validate"],
    )
    with pytest.raises(SystemExit) as exc:
        upload_bundle.main()
    msg = str(exc.value)
    assert "already exists" in msg
    assert "bump manifest.version" in msg


def test_upload_400_emits_status_and_body(tmp_path: Path, monkeypatch):
    bdir = _valid_bundle(tmp_path)

    def bad_request(req: httpx.Request) -> httpx.Response:
        return httpx.Response(422, text="schema invalid: missing inputs")

    _install_orch(monkeypatch, bad_request)
    monkeypatch.setattr(
        sys,
        "argv",
        ["sathop-upload-bundle", str(bdir), "--orch-url", "http://x", "--token", "tok", "--skip-validate"],
    )
    with pytest.raises(SystemExit) as exc:
        upload_bundle.main()
    assert "HTTP 422" in str(exc.value)


def test_upload_passes_description_as_query_param(tmp_path: Path, monkeypatch):
    bdir = _valid_bundle(tmp_path)
    captured = _install_orch(monkeypatch, _ok_upload)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "sathop-upload-bundle",
            str(bdir),
            "--orch-url",
            "http://x",
            "--token",
            "tok",
            "--skip-validate",
            "--description",
            "hello world",
        ],
    )
    assert upload_bundle.main() == 0
    assert captured and captured[0].url.params.get("description") == "hello world"


def test_upload_sends_bearer_header(tmp_path: Path, monkeypatch):
    bdir = _valid_bundle(tmp_path)
    captured = _install_orch(monkeypatch, _ok_upload)
    monkeypatch.setattr(
        sys,
        "argv",
        ["sathop-upload-bundle", str(bdir), "--orch-url", "http://x", "--token", "mytok", "--skip-validate"],
    )
    upload_bundle.main()
    assert captured[0].headers["Authorization"] == "Bearer mytok"


def test_upload_directory_must_exist(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        ["sathop-upload-bundle", str(tmp_path / "nope"), "--orch-url", "http://x", "--token", "t"],
    )
    with pytest.raises(SystemExit) as exc:
        upload_bundle.main()
    assert "is not a directory" in str(exc.value)
