"""Worker runtime per-granule helpers.

Small functions that shape worker output into wire-format events:
  - `auth_for` resolves a `Credential` by name (with operator-visible warning
    when the bundle requested a name the batch didn't carry).
  - `processing_failure_message` / `tail_or_none` / `traceback_tail` cap text
    fields on `ProcessingFailed` so a misbehaving bundle can't write multi-MB
    rows.

Per-storage and per-downloader formatters that used to live here have moved
to their domain homes:
  - `render_key` → `worker.storage.render_key`
  - `download_progress_detail` → `worker.downloader.progress_detail`
"""

from __future__ import annotations

import traceback

from sathop.shared.protocol import Credential

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
