"""Worker runtime helper functions."""

from __future__ import annotations

import traceback
from pathlib import Path

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


def download_progress_detail(downloaded: int, total: int | None) -> str:
    downloaded_mb = downloaded / 1_000_000
    if total:
        return f"{downloaded_mb:.1f}/{total / 1_000_000:.1f} MB"
    return f"{downloaded_mb:.1f} MB"


def render_key(template: str, out: Path, meta: dict) -> str:
    fields = {
        "stem": out.stem,
        "ext": out.suffix,
        "name": out.name,
        **{k: str(v) for k, v in meta.items()},
    }
    try:
        return template.format(**fields)
    except KeyError:
        return out.name
