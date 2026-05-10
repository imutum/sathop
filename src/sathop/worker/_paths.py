"""Worker filesystem path helpers."""

from __future__ import annotations

import re
import time
from pathlib import Path

_BAD = re.compile(r'[<>:"/\\|?*\x00]')


def safe_segment(value: str) -> str:
    return _BAD.sub("_", value)


def dir_size_bytes(path: Path) -> int:
    total = 0
    for p in path.rglob("*"):
        if p.is_file():
            try:
                total += p.stat().st_size
            except OSError:
                pass
    return total


def work_dir_path(work_root: Path, granule_id: str, timestamp: int | None = None) -> Path:
    ts = int(time.time()) if timestamp is None else timestamp
    return work_root / f"g-{safe_segment(granule_id)}-{ts}"


def parse_work_dir_name(name: str) -> tuple[str, int] | None:
    if not name.startswith("g-"):
        return None
    try:
        stem, ts_str = name.rsplit("-", 1)
        return stem[2:], int(ts_str)
    except ValueError:
        return None
