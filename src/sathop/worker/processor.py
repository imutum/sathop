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

# Per-stream cap on captured bundle output. Orchestrator persists 16 KB; 64 KB
# gives a comfortable headroom for debugging while bounding worker RAM so a
# runaway bundle (infinite print loop, binary blob to stdout) can't OOM the
# host. We keep reading after the cap is reached — silently discarding — so
# the child never blocks on a full pipe buffer.
_OUTPUT_CAP_BYTES = 64 * 1024

# Bundle subprocesses are user-supplied code with full filesystem access; we
# don't sandbox them. But we DO refuse to leak the worker's own secrets — most
# critically SATHOP_TOKEN, which would let a malicious bundle call the
# orchestrator API as the worker. Beyond that, we also keep HOME / USERPROFILE
# / APPDATA / LOCALAPPDATA / PROGRAMDATA *off* the whitelist: those directories
# routinely hold cloud credentials (~/.aws, ~/.config/gcloud, Earthdata cookie
# jars, browser/profile data on Windows). Bundles that genuinely need a per-
# user config dir should write to SATHOP_WORK_DIR or have the operator inject
# the specific values via manifest.execution.env / batch credentials.
# Unknown SATHOP_* values are explicitly NOT inherited; the worker injects the
# small set bundles legitimately need (SATHOP_INPUT_DIR / OUTPUT_DIR / WORK_DIR
# / SHARED_DIR / GRANULE_ID / BATCH_ID / META_JSON / BUNDLE_PYTHON /
# PROGRESS_URL) below.
_ENV_WHITELIST: frozenset[str] = frozenset(
    {
        # Cross-platform: PATH for executables, locale + TZ for predictable output.
        "PATH",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "LC_MESSAGES",
        "TZ",
        # POSIX: temp dirs only — HOME/USER/LOGNAME/SHELL deliberately omitted.
        "TMPDIR",
        "TMP",
        "TEMP",
        # Windows: paths Python itself reads at interpreter start, temp + arch
        # info. USERPROFILE/APPDATA/LOCALAPPDATA/PROGRAMDATA deliberately omitted.
        "SYSTEMROOT",
        "WINDIR",
        "PROGRAMFILES",
        "PROGRAMFILES(X86)",
        "PATHEXT",
        "COMSPEC",
        "NUMBER_OF_PROCESSORS",
        "PROCESSOR_ARCHITECTURE",
        "OS",
        "COMPUTERNAME",
    }
)


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
    """Env precedence (later wins): whitelisted os ⇒ bundle manifest ⇒ batch
    override ⇒ internal SATHOP_* (system-owned, not operator-tunable). PATH is
    prefixed with the selected runtime Python's dir so the entrypoint can just
    invoke `python ...` cross-platform (cmd.exe doesn't expand $VAR).

    The whitelist filter prevents worker-process secrets (e.g. SATHOP_TOKEN)
    from being inherited by user bundle code. See _ENV_WHITELIST above."""
    python_bin = str(bundle.python.parent)
    env = {k: v for k, v in os.environ.items() if k in _ENV_WHITELIST}
    env.update(bundle.manifest.execution.env)
    if execution_env:
        env.update(execution_env)
    env.update(
        {
            "PATH": python_bin + os.pathsep + os.environ.get("PATH", ""),
            "SATHOP_INPUT_DIR": str(input_dir),
            "SATHOP_OUTPUT_DIR": str(output_dir),
            "SATHOP_WORK_DIR": str(work_dir),
            "SATHOP_SHARED_DIR": str(bundle.shared_dir),
            "SATHOP_GRANULE_ID": granule_id,
            "SATHOP_BATCH_ID": batch_id,
            "SATHOP_META_JSON": json.dumps(meta, ensure_ascii=False),
            "SATHOP_BUNDLE_PYTHON": str(bundle.python),
        }
    )
    if progress_url:
        env["SATHOP_PROGRESS_URL"] = progress_url
    return env


async def _drain_to_cap(stream: asyncio.StreamReader | None, cap: int) -> tuple[bytes, bool]:
    """Read until EOF, keeping at most ``cap`` bytes. Continues reading past
    the cap (discarding) so the child process never blocks on a full pipe."""
    if stream is None:
        return b"", False
    buf = bytearray()
    truncated = False
    while True:
        chunk = await stream.read(64 * 1024)
        if not chunk:
            return bytes(buf), truncated
        room = cap - len(buf)
        if room > 0:
            buf.extend(chunk[:room])
            if len(chunk) > room:
                truncated = True
        else:
            truncated = True


async def _communicate_bounded(proc: asyncio.subprocess.Process, cap: int) -> tuple[bytes, bytes, bool, bool]:
    """Like ``proc.communicate()`` but stdout/stderr each capped at ``cap``."""
    out_task = asyncio.create_task(_drain_to_cap(proc.stdout, cap))
    err_task = asyncio.create_task(_drain_to_cap(proc.stderr, cap))
    await proc.wait()
    out_b, out_trunc = await out_task
    err_b, err_trunc = await err_task
    return out_b, err_b, out_trunc, err_trunc


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
        # CPython-specific: ``_transport`` is private asyncio detail; closing
        # it explicitly suppresses Windows ProactorEventLoop ResourceWarning
        # at GC time. Both the attribute lookup and close() are best-effort —
        # non-CPython runtimes simply skip this cleanup.
        transport = getattr(stream, "_transport", None) if stream else None
        if transport is not None:
            try:
                transport.close()
            except Exception:
                pass


async def run_bundle(
    bundle: BundleHandle,
    granule_id: str,
    batch_id: str,
    inputs: list[Path],
    meta: dict,
    work_dir: Path,
    execution_env: dict[str, str] | None = None,
    progress_url: str | None = None,
) -> ProcessResult:
    # work_dir is the caller's per-granule directory; the caller owns its
    # cleanup. We run inside a scratch subdir and stage outputs into
    # work_dir/output, so the caller's single rmtree(work_dir) reaps the run
    # scratch and the staged outputs alike — no orphan tree left behind.
    run_dir = Path(tempfile.mkdtemp(prefix="run-", dir=work_dir))
    input_dir = run_dir / "input"
    output_dir = run_dir / bundle.manifest.outputs.watch_dir
    input_dir.mkdir(parents=True)
    output_dir.mkdir(parents=True)

    try:
        for src in inputs:
            dst = input_dir / src.name
            # Inputs were just downloaded to the caller's work_dir, and run_dir is a
            # mkdtemp *inside* work_dir — same filesystem — so a hardlink stages them
            # into the bundle's isolated input dir with zero byte-copy. copy2 here
            # re-read+re-wrote every input on the event loop. Fall back to a real copy
            # only when the link can't be made (cross-FS / unsupported).
            try:
                os.link(src, dst)
            except OSError:
                shutil.copy2(src, dst)

        env = _build_env(
            bundle,
            granule_id=granule_id,
            batch_id=batch_id,
            work_dir=run_dir,
            input_dir=input_dir,
            output_dir=output_dir,
            meta=meta,
            execution_env=execution_env,
            progress_url=progress_url,
        )

        cmd = bundle.manifest.execution.entrypoint
        timeout = bundle.manifest.execution.timeout_sec

        proc = await asyncio.create_subprocess_shell(
            cmd,
            cwd=str(bundle.root),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_b, stderr_b, out_trunc, err_trunc = await asyncio.wait_for(
                _communicate_bounded(proc, _OUTPUT_CAP_BYTES), timeout=timeout
            )
        except (TimeoutError, asyncio.CancelledError):
            # Cancel comes from the worker's heartbeat-driven revoke loop;
            # timeout from manifest.execution.timeout_sec. Either way the
            # subprocess and its descendants must die before we propagate.
            await _kill_and_wait(proc)
            raise

        stdout = stdout_b.decode(errors="replace") if stdout_b else ""
        stderr = stderr_b.decode(errors="replace") if stderr_b else ""
        if out_trunc:
            stdout += f"\n[... stdout truncated at {_OUTPUT_CAP_BYTES} bytes]"
        if err_trunc:
            stderr += f"\n[... stderr truncated at {_OUTPUT_CAP_BYTES} bytes]"

        if proc.returncode != 0:
            return ProcessResult(False, [], stdout, stderr, proc.returncode or -1)

        exts = set(bundle.manifest.outputs.extensions)
        outputs = [p for p in output_dir.rglob("*") if p.is_file() and (not exts or p.suffix in exts)]

        if not outputs:
            return ProcessResult(False, [], stdout, stderr + "\n[no outputs produced]", proc.returncode or 0)

        # Move outputs into the caller-owned work_dir before dropping the run
        # scratch, so they survive until the caller reaps work_dir post-upload.
        kept_root = work_dir / "output"
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
        shutil.rmtree(run_dir, ignore_errors=True)
