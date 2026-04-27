"""Pre-flight bundle validation.

Usage:
    sathop-validate-bundle <bundle-dir> [--build-venv] [--quiet]
"""

from __future__ import annotations

import argparse
import re
import shlex
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from sathop.orchestrator.bundle_schema import InputsSchema, parse_shared_files

REQUIRED_KEYS = {"name", "version", "execution", "outputs", "inputs"}
RE_NAME = re.compile(r"^[A-Za-z0-9._-]+$")
RE_VERSION = re.compile(r"^[A-Za-z0-9._+-]+$")


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    passed: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _check_manifest_shape(manifest: dict, r: Report) -> None:
    missing = REQUIRED_KEYS - manifest.keys()
    if missing:
        r.errors.append(f"manifest missing required keys: {sorted(missing)}")
        return

    name = manifest.get("name")
    version = manifest.get("version")
    if not isinstance(name, str) or not RE_NAME.fullmatch(name):
        r.errors.append(f"manifest.name must match {RE_NAME.pattern}, got {name!r}")
    if not isinstance(version, str) or not RE_VERSION.fullmatch(version):
        r.errors.append(f"manifest.version must match {RE_VERSION.pattern}, got {version!r}")

    exe = manifest.get("execution")
    if not isinstance(exe, dict) or not exe.get("entrypoint"):
        r.errors.append("manifest.execution.entrypoint is required")
    else:
        timeout = exe.get("timeout_sec")
        if timeout is not None and not (isinstance(timeout, int) and timeout > 0):
            r.errors.append(f"manifest.execution.timeout_sec must be a positive int, got {timeout!r}")
        r.passed.append(f"execution.entrypoint = {exe.get('entrypoint')!r}")

    outs = manifest.get("outputs")
    if not isinstance(outs, dict):
        r.errors.append("manifest.outputs must be a mapping")
    else:
        wd = outs.get("watch_dir")
        if not isinstance(wd, str) or not wd:
            r.errors.append("manifest.outputs.watch_dir must be a non-empty string")
        exts = outs.get("extensions")
        if exts is not None:
            if not isinstance(exts, list) or not all(isinstance(e, str) and e.startswith(".") for e in exts):
                r.errors.append("manifest.outputs.extensions must be a list of dot-prefixed strings")
        if not r.errors:
            r.passed.append(f"outputs.watch_dir = {wd!r}, extensions = {exts}")


def _check_entrypoint_resolves(manifest: dict, bundle_dir: Path, r: Report) -> None:
    exe = manifest.get("execution") or {}
    cmd = exe.get("entrypoint")
    if not isinstance(cmd, str):
        return
    parts = shlex.split(cmd)
    if not parts:
        return

    interp = parts[0]
    if interp in ("bash", "sh", "zsh") or interp.startswith("python"):
        if len(parts) < 2:
            r.warnings.append(f"entrypoint {cmd!r} has interpreter but no script; nothing to verify")
            return
        script = parts[1]
    else:
        script = parts[0]

    script = script.removeprefix("./")
    target = bundle_dir / script
    if not target.exists():
        r.errors.append(f"entrypoint references {script!r} but {target} does not exist in bundle")
    elif not target.is_file():
        r.errors.append(f"entrypoint references {script!r} but {target} is not a file")
    else:
        r.passed.append(f"entrypoint script {script!r} resolves to {target.relative_to(bundle_dir)}")


def _check_requirements(manifest: dict, bundle_dir: Path, r: Report) -> None:
    has_req_txt = (bundle_dir / "requirements.txt").is_file()
    req = manifest.get("requirements")
    if req is None:
        if has_req_txt:
            r.passed.append("requirements.txt found — worker will install from it")
        else:
            r.passed.append("no requirements declared (bundle uses worker base image only)")
        return
    if not isinstance(req, dict):
        r.errors.append("manifest.requirements must be a mapping")
        return
    for key in ("pip", "apt", "credentials"):
        v = req.get(key)
        if v is not None and not (isinstance(v, list) and all(isinstance(x, str) for x in v)):
            r.errors.append(f"manifest.requirements.{key} must be a list of strings")
    py = req.get("python")
    if py is not None and not isinstance(py, str):
        r.errors.append("manifest.requirements.python must be a string (PEP 440 specifier)")
    n_pip = len(req.get("pip") or [])
    n_apt = len(req.get("apt") or [])
    n_creds = len(req.get("credentials") or [])
    r.passed.append(f"requirements: python={py!r}, pip={n_pip}, apt={n_apt}, credentials={n_creds}")
    if has_req_txt and n_pip > 0:
        r.warnings.append(
            "both requirements.txt and manifest.requirements.pip declared — "
            "worker uses requirements.txt and ignores manifest.pip"
        )
    elif has_req_txt:
        r.passed.append("requirements.txt found — worker will install from it")


def _check_inputs_and_shared(manifest: dict, r: Report) -> None:
    try:
        schema = InputsSchema.parse(manifest)
    except ValueError as e:
        r.errors.append(f"manifest.inputs invalid: {e}")
    else:
        r.passed.append(f"inputs.slots: {[s.name for s in schema.slots]}")
        if schema.meta:
            r.passed.append(f"inputs.meta: {[m.name for m in schema.meta]}")
    try:
        names = parse_shared_files(manifest)
    except ValueError as e:
        r.errors.append(f"manifest.shared_files invalid: {e}")
    else:
        if names:
            r.passed.append(f"shared_files: {names}")


def _try_build_venv(manifest: dict, r: Report) -> None:
    pip_deps = (manifest.get("requirements") or {}).get("pip") or []
    if not pip_deps:
        r.passed.append("(skipped venv build — no pip deps declared)")
        return
    try:
        subprocess.run(["uv", "--version"], capture_output=True, check=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        r.warnings.append("(skipped venv build — `uv` not found on PATH)")
        return

    py = (manifest.get("requirements") or {}).get("python") or ">=3.11"
    py_minor = re.search(r"3\.\d+", py)
    py_arg = ["--python", py_minor.group()] if py_minor else []

    with tempfile.TemporaryDirectory(prefix="sathop-validate-") as tmp:
        venv = Path(tmp) / "v"
        try:
            subprocess.run(["uv", "venv", *py_arg, str(venv)], capture_output=True, check=True, timeout=120)
            subprocess.run(
                ["uv", "pip", "install", "--python", str(venv), "--", *pip_deps],
                capture_output=True,
                check=True,
                timeout=600,
            )
        except subprocess.CalledProcessError as e:
            stderr = (e.stderr or b"").decode("utf-8", "replace")[-1500:]
            r.errors.append(f"venv build failed:\n{stderr}")
            return
        except subprocess.TimeoutExpired:
            r.errors.append("venv build timed out (>10 min)")
            return
        r.passed.append(f"venv build succeeded ({len(pip_deps)} pip deps installed)")


def validate(bundle_dir: Path, build_venv: bool = False) -> Report:
    r = Report()
    if not bundle_dir.is_dir():
        r.errors.append(f"{bundle_dir} is not a directory")
        return r
    manifest_path = bundle_dir / "manifest.yaml"
    if not manifest_path.is_file():
        r.errors.append(f"{manifest_path} not found")
        return r
    try:
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        r.errors.append(f"manifest.yaml is not valid YAML: {e}")
        return r
    if not isinstance(manifest, dict):
        r.errors.append("manifest.yaml top level must be a mapping")
        return r

    _check_manifest_shape(manifest, r)
    _check_inputs_and_shared(manifest, r)
    _check_entrypoint_resolves(manifest, bundle_dir, r)
    _check_requirements(manifest, bundle_dir, r)
    if build_venv:
        _try_build_venv(manifest, r)
    return r


def _print(r: Report, quiet: bool) -> None:
    for line in r.passed:
        if not quiet:
            print(f"  ✓ {line}")
    for w in r.warnings:
        print(f"  ⚠ {w}", file=sys.stderr)
    for e in r.errors:
        print(f"  ✗ {e}", file=sys.stderr)
    if r.ok:
        print(f"\nOK ({len(r.passed)} checks passed, {len(r.warnings)} warning(s))")
    else:
        print(f"\nFAILED ({len(r.errors)} error(s), {len(r.warnings)} warning(s))", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate a bundle directory before upload")
    ap.add_argument("bundle_dir", type=Path)
    ap.add_argument("--build-venv", action="store_true", help="actually pip-install requirements (slow)")
    ap.add_argument("--quiet", action="store_true", help="only print warnings + errors")
    args = ap.parse_args()
    r = validate(args.bundle_dir.resolve(), build_venv=args.build_venv)
    _print(r, args.quiet)
    return 0 if r.ok else 1


if __name__ == "__main__":
    sys.exit(main())
