"""Plugin runner: execute a bundle for one granule, collect outputs.

The worker stays ignorant of what user scripts do. It only:
  1. stages inputs into <work_dir>/input/
  2. runs `manifest.execution.entrypoint` with env vars set
  3. on exit-code 0, collects files from <work_dir>/output/ by extension
  4. cleans up the work dir

The subprocess is launched via asyncio.create_subprocess_shell so that an
``asyncio.CancelledError`` (operator cancelled the batch / granule) reaches
us promptly and we can kill the child process — sync ``subprocess.run``
would hold the event-loop's hands tied behind a thread until the bundle
exits naturally or hits its `timeout_sec`, wasting CPU on ghost work.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
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


_GRACEFUL_KILL_WAIT_SEC = 5.0


def _build_env(
    bundle: BundleHandle,
    *,
    granule_id: str,
    batch_id: str,
    work_dir: Path,
    input_dir: Path,
    output_dir: Path,
    meta: dict,
    execution_env: dict[str, str] | None,
    progress_url: str | None,
) -> dict[str, str]:
    """Env precedence (later wins): os ⇒ bundle manifest ⇒ batch override ⇒
    internal SATHOP_* (system-owned, not operator-tunable). PATH is prefixed
    with the bundle venv's bin dir so the entrypoint can just invoke
    `python ...` cross-platform (cmd.exe doesn't expand $VAR)."""
    venv_bin = str(bundle.venv_python.parent)
    env = dict(os.environ)
    env.update(bundle.manifest.execution.get("env", {}))
    if execution_env:
        env.update(execution_env)
    env.update(
        {
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
    )
    if progress_url:
        env["SATHOP_PROGRESS_URL"] = progress_url
    return env


async def _kill_and_wait(proc: asyncio.subprocess.Process) -> None:
    """Best-effort: signal terminate, give the process a few seconds to flush
    open files, then SIGKILL. ``await proc.wait()`` is essential — without it
    Windows leaves an orphan handle, Linux leaves a zombie. We also explicitly
    close stdout/stderr transports afterwards because Windows' Proactor event
    loop emits a ResourceWarning at GC time otherwise."""
    if proc.returncode is None:
        try:
            proc.terminate()
        except ProcessLookupError:
            pass
        else:
            try:
                await asyncio.wait_for(proc.wait(), timeout=_GRACEFUL_KILL_WAIT_SEC)
            except TimeoutError:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
                else:
                    await proc.wait()
    for stream in (proc.stdout, proc.stderr):
        transport = getattr(stream, "_transport", None) if stream else None
        if transport is not None:
            transport.close()


async def run_bundle(
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

        env = _build_env(
            bundle,
            granule_id=granule_id,
            batch_id=batch_id,
            work_dir=work_dir,
            input_dir=input_dir,
            output_dir=output_dir,
            meta=meta,
            execution_env=execution_env,
            progress_url=progress_url,
        )

        cmd = bundle.manifest.execution["entrypoint"]
        timeout = int(bundle.manifest.execution.get("timeout_sec", 900))

        proc = await asyncio.create_subprocess_shell(
            cmd,
            cwd=str(bundle.root),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except (TimeoutError, asyncio.CancelledError):
            # Cancel comes from the worker's heartbeat-driven revoke loop;
            # timeout from manifest.execution.timeout_sec. Either way the
            # subprocess and its descendants must die before we propagate.
            await _kill_and_wait(proc)
            raise

        stdout = stdout_b.decode(errors="replace") if stdout_b else ""
        stderr = stderr_b.decode(errors="replace") if stderr_b else ""

        if proc.returncode != 0:
            return ProcessResult(False, [], stdout, stderr, proc.returncode or -1)

        exts = set(bundle.manifest.outputs.get("extensions", []))
        outputs = [p for p in output_dir.rglob("*") if p.is_file() and (not exts or p.suffix in exts)]

        if not outputs:
            return ProcessResult(False, [], stdout, stderr + "\n[no outputs produced]", proc.returncode or 0)

        # Copy outputs out of work_dir before cleanup, so caller keeps them.
        kept_root = work_root / "_staged" / granule_id
        kept_root.mkdir(parents=True, exist_ok=True)
        kept = []
        for p in outputs:
            rel = p.relative_to(output_dir)
            dst = kept_root / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(p), dst)
            kept.append(dst)

        return ProcessResult(True, kept, stdout, stderr, 0)

    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
