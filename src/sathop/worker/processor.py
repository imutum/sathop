"""Plugin runner: execute a bundle for one granule, collect outputs.

The worker stays ignorant of what user scripts do. It only:
  1. stages inputs into <work_dir>/input/
  2. runs `manifest.execution.entrypoint` with env vars set
  3. on exit-code 0, collects files from <work_dir>/output/ by extension
  4. cleans up the work dir
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .bundle import BundleHandle


@dataclass(frozen=True)
class ProcessResult:
    ok: bool
    outputs: list[Path]
    stdout: str
    stderr: str
    exit_code: int


def run_bundle(
    bundle: BundleHandle,
    granule_id: str,
    batch_id: str,
    inputs: list[Path],
    meta: dict,
    work_root: Path,
    execution_env: dict[str, str] | None = None,
    progress_url: str | None = None,
) -> ProcessResult:
    work_dir = Path(tempfile.mkdtemp(prefix=f"g-{granule_id}-", dir=work_root))
    input_dir = work_dir / "input"
    output_dir = work_dir / bundle.manifest.outputs.get("watch_dir", "output")
    input_dir.mkdir(parents=True)
    output_dir.mkdir(parents=True)

    try:
        for src in inputs:
            shutil.copy2(src, input_dir / src.name)

        # Prepend the bundle's venv bin dir to PATH so the entrypoint can just
        # invoke `python ...` cross-platform (cmd.exe doesn't expand $VAR).
        # Env precedence (later wins): os > bundle manifest > batch override >
        # internal SATHOP_* (those are system-owned, not operator-tunable).
        venv_bin = str(bundle.venv_python.parent)
        env = dict(os.environ)
        env.update(bundle.manifest.execution.get("env", {}))
        if execution_env:
            env.update(execution_env)
        internal = {
            "PATH": venv_bin + os.pathsep + os.environ.get("PATH", ""),
            "SATHOP_INPUT_DIR": str(input_dir),
            "SATHOP_OUTPUT_DIR": str(output_dir),
            "SATHOP_WORK_DIR": str(work_dir),
            "SATHOP_SHARED_DIR": str(bundle.shared_dir),
            "SATHOP_GRANULE_ID": granule_id,
            "SATHOP_BATCH_ID": batch_id,
            "SATHOP_META_JSON": json.dumps(meta, ensure_ascii=False),
            "SATHOP_VENV_PYTHON": str(bundle.venv_python),
        }
        if progress_url:
            internal["SATHOP_PROGRESS_URL"] = progress_url
        env.update(internal)

        cmd = bundle.manifest.execution["entrypoint"]
        timeout = int(bundle.manifest.execution.get("timeout_sec", 900))

        proc = subprocess.run(
            cmd,
            shell=True,
            cwd=bundle.root,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        if proc.returncode != 0:
            return ProcessResult(False, [], proc.stdout, proc.stderr, proc.returncode)

        exts = set(bundle.manifest.outputs.get("extensions", []))
        outputs = [p for p in output_dir.rglob("*") if p.is_file() and (not exts or p.suffix in exts)]

        if not outputs:
            return ProcessResult(
                False, [], proc.stdout, proc.stderr + "\n[no outputs produced]", proc.returncode
            )

        # Copy outputs out of work_dir before cleanup, so caller keeps them
        kept_root = work_root / "_staged" / granule_id
        kept_root.mkdir(parents=True, exist_ok=True)
        kept = []
        for p in outputs:
            rel = p.relative_to(output_dir)
            dst = kept_root / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(p), dst)
            kept.append(dst)

        return ProcessResult(True, kept, proc.stdout, proc.stderr, 0)

    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
