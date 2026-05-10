"""Script bundle fetch + runtime preparation.

Single ref format: `orch:<name>@<version>` — bundles live in the orchestrator's
central registry and are pulled via `GET /api/bundles/<name>/<version>/download`
with Bearer auth. Fetched zips are cached in the bundle cache dir under
`<name>@<version>/`. Bundles without Python deps run on the worker's existing
Python; bundles declaring deps get a cached per-version venv. First-time fetch
and runtime prep are serialized per ref."""

from __future__ import annotations

import io
import logging
import os
import shutil
import subprocess
import sys
import threading
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml

from sathop.shared.http import bearer_headers

from . import shared as shared_sync
from ._paths import dir_size_bytes

log = logging.getLogger("sathop.worker.bundle")

_LAST_USED_DIR = ".last_used"

_ref_locks: dict[str, threading.Lock] = {}
_ref_locks_guard = threading.Lock()


def _lock_for(ref: str) -> threading.Lock:
    with _ref_locks_guard:
        lock = _ref_locks.get(ref)
        if lock is None:
            lock = threading.Lock()
            _ref_locks[ref] = lock
        return lock


@dataclass(frozen=True)
class BundleManifest:
    name: str
    version: str
    inputs: dict
    execution: dict
    outputs: dict
    requirements: dict
    shared_files: list[str]

    @classmethod
    def load(cls, path: Path) -> BundleManifest:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        raw_shared = data.get("shared_files") or []
        if not isinstance(raw_shared, list) or not all(isinstance(x, str) and x for x in raw_shared):
            raise ValueError("manifest.shared_files must be a list of non-empty strings")
        return cls(
            name=data["name"],
            version=data["version"],
            inputs=data.get("inputs", {}),
            execution=data["execution"],
            outputs=data["outputs"],
            requirements=data.get("requirements", {}),
            shared_files=list(raw_shared),
        )


@dataclass(frozen=True)
class BundleHandle:
    manifest: BundleManifest
    root: Path
    python: Path
    shared_dir: Path


@dataclass(frozen=True)
class PythonDepsSource:
    kind: Literal["requirements.txt", "manifest.pip"]
    values: tuple[str, ...]
    requirements_file: Path | None = None

    def pip_install_args(self) -> list[str]:
        if self.requirements_file is not None:
            return ["-r", str(self.requirements_file)]
        return list(self.values)


def _parse_ref(ref: str) -> tuple[str, str]:
    if not ref.startswith("orch:"):
        raise ValueError(f"bundle ref must be 'orch:<name>@<version>', got {ref!r}")
    body = ref[len("orch:") :]
    if "@" not in body:
        raise ValueError(f"bundle ref missing '@<version>': {ref!r}")
    name, version = body.rsplit("@", 1)
    if not name or not version:
        raise ValueError(f"bundle ref name/version both required: {ref!r}")
    return name, version


def ensure(
    ref: str,
    cache_root: Path,
    venv_root: Path,
    shared_root: Path,
    orchestrator_url: str,
    token: str,
) -> BundleHandle:
    name, version = _parse_ref(ref)
    with _lock_for(ref):
        bundle_dir = cache_root / f"{name}@{version}"
        if not bundle_dir.exists():
            _fetch_from_orch(orchestrator_url, token, name, version, bundle_dir)

        _touch_last_used(venv_root, name, version)
        manifest = BundleManifest.load(bundle_dir / "manifest.yaml")
        python = _ensure_runtime(manifest, bundle_dir, venv_root)
        shared_sync.sync(manifest.shared_files, shared_root, orchestrator_url, token)
        return BundleHandle(manifest=manifest, root=bundle_dir, python=python, shared_dir=shared_root)


def _touch_last_used(venv_root: Path, name: str, version: str) -> None:
    sidecar_dir = venv_root / _LAST_USED_DIR
    sidecar_dir.mkdir(parents=True, exist_ok=True)
    sidecar = sidecar_dir / f"{name}@{version}"
    if sidecar.exists():
        os.utime(sidecar, None)
    else:
        sidecar.touch()


def prune_caches(venv_root: Path, cache_root: Path, limit_bytes: int) -> dict:
    if limit_bytes <= 0:
        return {"removed": 0, "freed_bytes": 0, "total_bytes": 0}
    sidecar_dir = venv_root / _LAST_USED_DIR
    if not sidecar_dir.is_dir():
        return {"removed": 0, "freed_bytes": 0, "total_bytes": 0}

    items: list[tuple[float, str, Path, Path, int]] = []
    for sidecar in sidecar_dir.iterdir():
        if not sidecar.is_file():
            continue
        ref_dirname = sidecar.name
        venv_dir = venv_root / ref_dirname
        bundle_dir = cache_root / ref_dirname
        if not venv_dir.is_dir() and not bundle_dir.is_dir():
            sidecar.unlink(missing_ok=True)
            continue
        try:
            mtime = sidecar.stat().st_mtime
        except OSError:
            continue
        size = (dir_size_bytes(venv_dir) if venv_dir.is_dir() else 0) + (
            dir_size_bytes(bundle_dir) if bundle_dir.is_dir() else 0
        )
        items.append((mtime, ref_dirname, venv_dir, bundle_dir, size))

    total = sum(it[4] for it in items)
    if total <= limit_bytes:
        return {"removed": 0, "freed_bytes": 0, "total_bytes": total}

    items.sort(key=lambda it: it[0])

    removed = 0
    freed = 0
    for _mtime, ref_dirname, venv_dir, bundle_dir, size in items:
        if total - freed <= limit_bytes:
            break
        lock = _lock_for(f"orch:{ref_dirname}")
        if not lock.acquire(blocking=False):
            log.debug("skipping %s — in use by ensure()", ref_dirname)
            continue
        try:
            shutil.rmtree(venv_dir, ignore_errors=True)
            shutil.rmtree(bundle_dir, ignore_errors=True)
            (sidecar_dir / ref_dirname).unlink(missing_ok=True)
        finally:
            lock.release()
        removed += 1
        freed += size
        log.info("evicted %s (%d bytes)", ref_dirname, size)

    return {"removed": removed, "freed_bytes": freed, "total_bytes": total - freed}


def _fetch_from_orch(orchestrator_url: str, token: str, name: str, version: str, dest: Path) -> None:
    url = f"{orchestrator_url.rstrip('/')}/api/bundles/{name}/{version}/download"
    req = urllib.request.Request(url, headers=bearer_headers(token))
    with urllib.request.urlopen(req, timeout=120) as resp:
        if resp.status != 200:
            raise RuntimeError(f"bundle {name}@{version} fetch failed: HTTP {resp.status}")
        payload = resp.read()

    dest.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as zf:
            _extract_bundle_zip(zf, dest)
        _flatten_wrapper_dir(dest)
        if not (dest / "manifest.yaml").is_file():
            raise FileNotFoundError(f"manifest.yaml not found in fetched bundle {name}@{version}")
    except Exception:
        shutil.rmtree(dest, ignore_errors=True)
        raise


def _extract_bundle_zip(zf: zipfile.ZipFile, dest: Path) -> None:
    root = dest.resolve()
    for member in zf.infolist():
        target = (dest / member.filename).resolve()
        if target != root and root not in target.parents:
            raise ValueError(f"bundle archive member escapes target directory: {member.filename!r}")
        zf.extract(member, dest)


def _flatten_wrapper_dir(dest: Path) -> None:
    """If the extracted archive has a single top-level directory wrapping
    everything, promote its contents so manifest.yaml sits directly in `dest`.
    Accommodates zips built from a parent directory (e.g. github-style)."""
    if (dest / "manifest.yaml").is_file():
        return
    entries = [p for p in dest.iterdir() if not p.name.startswith(".")]
    if len(entries) != 1 or not entries[0].is_dir():
        return
    wrapper = entries[0]
    for child in wrapper.iterdir():
        target = dest / child.name
        if target.exists():
            continue
        child.rename(target)
    shutil.rmtree(wrapper, ignore_errors=True)


def _ensure_runtime(manifest: BundleManifest, bundle_dir: Path, venv_root: Path) -> Path:
    if python_deps_source(manifest.requirements, bundle_dir) is None:
        return Path(sys.executable)
    return _ensure_venv(manifest, bundle_dir, venv_root)


def python_deps_source(requirements: dict, bundle_dir: Path) -> PythonDepsSource | None:
    req_file = bundle_dir / "requirements.txt"
    if req_file.exists():
        lines = req_file.read_text(encoding="utf-8").splitlines()
        values = tuple(line.strip() for line in lines if _meaningful_requirement(line))
        return PythonDepsSource("requirements.txt", values, req_file) if values else None
    pip_deps = tuple(requirements.get("pip", []) or [])
    return PythonDepsSource("manifest.pip", pip_deps) if pip_deps else None


_PIP_OPTION_PREFIXES = (
    "--extra-index-url",
    "--find-links",
    "--index-url",
    "--no-index",
    "--require-hashes",
    "--trusted-host",
    "-f",
    "-i",
)


def _meaningful_requirement(line: str) -> bool:
    stripped = line.strip()
    return bool(stripped and not stripped.startswith("#") and not stripped.startswith(_PIP_OPTION_PREFIXES))


def _ensure_venv(manifest: BundleManifest, bundle_dir: Path, venv_root: Path) -> Path:
    """Build the venv in a sibling tmp dir then atomic-rename, so a half-built
    venv from a crashed previous run doesn't poison the cache."""
    venv_dir = venv_root / f"{manifest.name}@{manifest.version}"
    is_win = sys.platform == "win32"
    rel_python = "Scripts/python.exe" if is_win else "bin/python"
    python_bin = venv_dir / rel_python

    if python_bin.exists():
        return python_bin

    venv_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(venv_dir, ignore_errors=True)  # clean any aborted previous attempt

    tmp_dir = venv_dir.with_name(venv_dir.name + f".building.{threading.get_ident()}")
    shutil.rmtree(tmp_dir, ignore_errors=True)

    try:
        subprocess.run([sys.executable, "-m", "venv", str(tmp_dir)], check=True)

        tmp_python = tmp_dir / rel_python
        deps = python_deps_source(manifest.requirements, bundle_dir)
        if deps is not None:
            subprocess.run(
                [str(tmp_python), "-m", "pip", "install", "-q", *deps.pip_install_args()], check=True
            )

        tmp_dir.rename(venv_dir)
    except Exception:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise

    return python_bin
