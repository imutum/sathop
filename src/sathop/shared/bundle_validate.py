"""Bundle pre-flight validation: "is this directory a valid bundle?".

The single library entry point that ties the bundle-domain parsers
(`bundle_manifest`, `bundle_python_deps`) into one accumulating report —
fail-fast inside each manifest section, but collect errors across sections so
the operator sees every problem in one pass. Lives in `shared/` (not `cli/`)
so the Worker, Orchestrator, and the `sathop-validate-bundle` CLI can all reach
it without importing CLI code; the CLI is just the argparse + print adapter.
"""

from __future__ import annotations

import re
import shlex
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from sathop.shared.bundle_manifest import (
    ExecutionConfig,
    InputsSchema,
    OutputsConfig,
    RequirementsConfig,
    parse_meta,
    parse_shared_files,
)
from sathop.shared.bundle_python_deps import python_deps_source


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    passed: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _check_manifest_shape(manifest: dict, r: Report) -> None:
    """Run each canonical section parser independently so the Report
    can surface every section's error in one pass — fail-fast inside a
    section, accumulate across sections."""
    try:
        name, version, _ = parse_meta(manifest)
        r.passed.append(f"name = {name!r}, version = {version!r}")
    except ValueError as e:
        r.errors.append(str(e))

    try:
        exe = ExecutionConfig.parse(manifest.get("execution"))
        r.passed.append(f"execution.entrypoint = {exe.entrypoint!r}, timeout_sec = {exe.timeout_sec}")
    except ValueError as e:
        r.errors.append(str(e))

    try:
        outs = OutputsConfig.parse(manifest.get("outputs", {}))
        r.passed.append(f"outputs.watch_dir = {outs.watch_dir!r}, extensions = {list(outs.extensions)}")
    except ValueError as e:
        r.errors.append(str(e))


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

    # `python -c "..."`, `python -m pkg`, or stdin (`-`) carry no script path —
    # nothing to resolve against the bundle, so don't flag a phantom missing file.
    if script.startswith("-"):
        r.passed.append(f"entrypoint {cmd!r} runs inline ({script!r}); no script path to verify")
        return

    script = script.removeprefix("./")
    target = bundle_dir / script
    if not target.exists():
        r.errors.append(f"entrypoint references {script!r} but {target} does not exist in bundle")
    elif not target.is_file():
        r.errors.append(f"entrypoint references {script!r} but {target} is not a file")
    else:
        r.passed.append(f"entrypoint script {script!r} resolves to {target.relative_to(bundle_dir)}")


def _check_requirements(manifest: dict, bundle_dir: Path, r: Report) -> RequirementsConfig | None:
    try:
        req = RequirementsConfig.parse(manifest.get("requirements"))
    except ValueError as e:
        r.errors.append(str(e))
        return None
    r.passed.append(
        f"requirements: python={req.python!r}, pip={len(req.pip)}, apt={len(req.apt)}, "
        f"credentials={len(req.credentials)}"
    )

    deps = python_deps_source(req, bundle_dir)
    if deps is None:
        r.passed.append("no Python requirements declared (bundle uses worker Python)")
    elif deps.kind == "requirements.txt":
        r.passed.append("requirements.txt found — worker will install from it")
        if req.pip:
            r.warnings.append(
                "both requirements.txt and manifest.requirements.pip declared — "
                "worker uses requirements.txt and ignores manifest.pip"
            )
    return req


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
            r.passed.append(f"shared_files: {list(names)}")


def _try_build_venv(req: RequirementsConfig, bundle_dir: Path, r: Report) -> None:
    deps = python_deps_source(req, bundle_dir)
    if deps is None:
        r.passed.append("(skipped venv build — no pip deps declared)")
        return
    try:
        subprocess.run(["uv", "--version"], capture_output=True, check=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        r.warnings.append("(skipped venv build — `uv` not found on PATH)")
        return

    py = req.python or ">=3.11"
    py_minor = re.search(r"3\.\d+", py)
    py_arg = ["--python", py_minor.group()] if py_minor else []

    with tempfile.TemporaryDirectory(prefix="sathop-validate-") as tmp:
        venv = Path(tmp) / "v"
        try:
            subprocess.run(["uv", "venv", *py_arg, str(venv)], capture_output=True, check=True, timeout=120)
            install_cmd = ["uv", "pip", "install", "--python", str(venv)]
            if deps.requirements_file is None:
                install_cmd.append("--")
            subprocess.run(
                [*install_cmd, *deps.pip_install_args()],
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
        r.passed.append(f"venv build succeeded ({len(deps.values)} pip deps installed)")


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
    req = _check_requirements(manifest, bundle_dir, r)
    if build_venv and req is not None:
        _try_build_venv(req, bundle_dir, r)
    return r
