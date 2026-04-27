"""Zip a bundle directory and upload to the orchestrator registry.

Usage:
    sathop-upload-bundle <bundle-dir> --url sathop://TOKEN@host:port
    sathop-upload-bundle <bundle-dir> --orch-url http://... --token ...   # legacy split form
"""

from __future__ import annotations

import argparse
import io
import os
import sys
import zipfile
from pathlib import Path

import httpx
import yaml

from sathop.cli.validate_bundle import validate as _validate
from sathop.shared.config import cli_resolve_orch
from sathop.shared.http import bearer_headers

EXCLUDE_NAMES = {"__pycache__", ".git", ".venv", ".mypy_cache", ".pytest_cache"}
EXCLUDE_SUFFIXES = {".pyc", ".pyo"}


def _should_include(path: Path, root: Path) -> bool:
    for part in path.relative_to(root).parts:
        if part in EXCLUDE_NAMES or part.startswith(".") and part not in (".env.example",):
            return False
    if path.suffix in EXCLUDE_SUFFIXES:
        return False
    return True


def _build_zip(bundle_dir: Path) -> bytes:
    manifest_path = bundle_dir / "manifest.yaml"
    if not manifest_path.is_file():
        sys.exit(f"error: {manifest_path} not found")
    try:
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        sys.exit(f"error: manifest.yaml parse failed: {e}")
    if not isinstance(manifest, dict) or "name" not in manifest or "version" not in manifest:
        sys.exit("error: manifest.yaml must be a mapping with 'name' and 'version'")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in sorted(bundle_dir.rglob("*")):
            if not path.is_file() or not _should_include(path, bundle_dir):
                continue
            arcname = path.relative_to(bundle_dir).as_posix()
            zf.write(path, arcname)
    return buf.getvalue()


def main() -> int:
    ap = argparse.ArgumentParser(description="Zip and upload a bundle to orchestrator")
    ap.add_argument("bundle_dir", type=Path, help="path to directory containing manifest.yaml")
    ap.add_argument(
        "--url",
        default=os.getenv("SATHOP_URL", ""),
        help="sathop://TOKEN@host:port — overrides --orch-url/--token (reads SATHOP_URL env)",
    )
    ap.add_argument("--orch-url", default=os.getenv("SATHOP_ORCH_URL", ""))
    ap.add_argument("--token", default=os.getenv("SATHOP_TOKEN", ""))
    ap.add_argument("--description", default=None)
    ap.add_argument("--skip-validate", action="store_true", help="skip pre-flight bundle validation")
    args = ap.parse_args()

    try:
        orch_url, token = cli_resolve_orch(args.url, args.orch_url, args.token)
    except ValueError as e:
        sys.exit(f"error: {e}")

    bundle_dir: Path = args.bundle_dir.resolve()
    if not bundle_dir.is_dir():
        sys.exit(f"error: {bundle_dir} is not a directory")

    if not args.skip_validate:
        report = _validate(bundle_dir)
        for w in report.warnings:
            print(f"  ⚠ {w}", file=sys.stderr)
        if not report.ok:
            for e in report.errors:
                print(f"  ✗ {e}", file=sys.stderr)
            sys.exit("error: bundle validation failed; pass --skip-validate to override")

    blob = _build_zip(bundle_dir)
    print(f">>> zipped {bundle_dir.name} ({len(blob)} bytes)")

    url = f"{orch_url}/api/bundles"
    params = {"description": args.description} if args.description else None
    with httpx.Client(timeout=60) as c:
        r = c.post(
            url,
            headers=bearer_headers(token),
            params=params,
            files={"file": ("bundle.zip", blob, "application/zip")},
        )
    if r.status_code == 409:
        sys.exit(f"error: {r.json().get('detail', r.text)}\n       bump manifest.version and retry")
    if r.status_code >= 400:
        sys.exit(f"error: HTTP {r.status_code} {r.text[:400]}")

    body = r.json()
    print(f">>> uploaded {body['name']}@{body['version']} (sha={body['sha256'][:12]}, size={body['size']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
