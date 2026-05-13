"""Worker runtime per-granule helpers.

Small functions that shape worker output into wire-format events:
  - `auth_for` resolves a `Credential` by name (with operator-visible warning
    when the bundle requested a name the batch didn't carry).
  - `processing_failed_from_result` / `processing_failed_from_exception` build
    the `ProcessingFailed` event for the two ways a granule can fail — bundle
    exited non-zero vs. worker raised — each one capping text tails so a
    misbehaving bundle can't write multi-MB rows.

Per-storage and per-downloader formatters that used to live here have moved
to their domain homes:
  - `render_key` → `worker.storage.render_key`
  - `download_progress_detail` → `worker.downloader.progress_detail`
"""

from __future__ import annotations

import traceback
from typing import TYPE_CHECKING

from sathop.shared.protocol import Credential
from sathop.shared.state_machine import ProcessingFailed

if TYPE_CHECKING:
    from .processor import ProcessResult

PROCESSING_FAILURE_TAIL_CHARS = 2000
WORKER_TRACEBACK_TAIL_CHARS = 1500
PROCESS_OUTPUT_TAIL_CHARS = 16000


def auth_for(creds: dict[str, Credential], name: str | None, gid: str, log) -> Credential | None:
    if not name:
        return None
    credential = creds.get(name)
    if credential is None:
        log.warning("[%s] credential %r not provided by batch", gid, name)
    return credential


def processing_failure_message(stderr: str) -> str:
    return (stderr or "no output")[-PROCESSING_FAILURE_TAIL_CHARS:]


def tail_or_none(value: str, n: int) -> str | None:
    if not value:
        return None
    return value if len(value) <= n else value[-n:]


def traceback_tail(exc: Exception) -> str:
    return "".join(traceback.format_exception(exc))[-WORKER_TRACEBACK_TAIL_CHARS:]


def processing_failed_from_result(gid: str, worker_id: str, result: ProcessResult) -> ProcessingFailed:
    return ProcessingFailed(
        granule_id=gid,
        worker_id=worker_id,
        error=processing_failure_message(result.stderr),
        stdout_tail=tail_or_none(result.stdout, PROCESS_OUTPUT_TAIL_CHARS),
        stderr_tail=tail_or_none(result.stderr, PROCESS_OUTPUT_TAIL_CHARS),
        exit_code=result.exit_code,
    )


def processing_failed_from_exception(gid: str, worker_id: str, exc: Exception) -> ProcessingFailed:
    return ProcessingFailed(
        granule_id=gid,
        worker_id=worker_id,
        error=f"worker {type(exc).__name__}: {exc}\n\n{traceback_tail(exc)}",
        exit_code=None,
    )
