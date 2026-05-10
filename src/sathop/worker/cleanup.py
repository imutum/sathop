"""Worker local cleanup jobs."""

from __future__ import annotations

import asyncio
import logging
import shutil
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

from . import bundle
from . import shared as shared_sync
from ._paths import dir_size_bytes, parse_work_dir_name, safe_segment
from .config import Settings

log = logging.getLogger("sathop.worker.cleanup")

# work_root/g-* dirs older than this with no active handler are SIGKILL
# orphans. Regular handler exit removes work dirs via finally.
_WORK_DIR_ORPHAN_AGE_SEC = 3600


def prune_work_dir_orphans(work_root: Path, active_segments: set[str]) -> dict[str, int]:
    threshold = time.time() - _WORK_DIR_ORPHAN_AGE_SEC
    removed = 0
    freed = 0
    if not work_root.is_dir():
        return {"removed": 0, "freed_bytes": 0}
    for entry in work_root.iterdir():
        parsed = parse_work_dir_name(entry.name)
        if not entry.is_dir() or parsed is None:
            continue
        segment, ts = parsed
        if ts > threshold or segment in active_segments:
            continue
        size = dir_size_bytes(entry)
        shutil.rmtree(entry, ignore_errors=True)
        removed += 1
        freed += size
    return {"removed": removed, "freed_bytes": freed}


class CacheCleaner:
    def __init__(self, settings: Settings, active_granule_ids: Callable[[], set[str]]) -> None:
        self.s = settings
        self._active_granule_ids = active_granule_ids

    async def loop(self, wake: asyncio.Event) -> None:
        periodic = self.s.gc_interval_sec > 0
        if not periodic:
            log.info("gc loop periodic disabled (SATHOP_GC_INTERVAL=0); event-driven GC still active")
        wake.set()
        while True:
            if periodic:
                try:
                    await asyncio.wait_for(wake.wait(), timeout=self.s.gc_interval_sec)
                except TimeoutError:
                    pass
            else:
                await wake.wait()
            wake.clear()
            await self.run_once()

    async def run_once(self) -> None:
        await asyncio.gather(
            self._run_job("venv LRU cleanup", self._prune_venvs),
            self._run_job("shared orphan cleanup", self._prune_shared_files),
            self._run_job("work_dir orphan cleanup", self._prune_work_dirs),
        )

    async def _run_job(self, name: str, job: Callable[[], Awaitable[None]]) -> None:
        try:
            await job()
        except Exception as e:
            log.warning("%s failed: %s", name, e)

    async def _prune_venvs(self) -> None:
        limit_bytes = int(self.s.venv_cache_limit_gb * 1024**3)
        r = await asyncio.to_thread(bundle.prune_caches, self.s.venv_cache, self.s.bundle_cache, limit_bytes)
        if r["removed"]:
            log.info(
                "venv LRU evicted %d entr(ies), freed %.1f GB (now %.1f GB total)",
                r["removed"],
                r["freed_bytes"] / 1024**3,
                r["total_bytes"] / 1024**3,
            )

    async def _prune_shared_files(self) -> None:
        r = await asyncio.to_thread(
            shared_sync.prune_orphans,
            self.s.shared_cache,
            self.s.orchestrator_url,
            self.s.token,
        )
        if r["removed"]:
            log.info(
                "shared orphan cleanup removed %d file(s), freed %.1f MB",
                r["removed"],
                r["freed_bytes"] / 1024**2,
            )

    async def _prune_work_dirs(self) -> None:
        active = {safe_segment(g) for g in self._active_granule_ids()}
        r = await asyncio.to_thread(prune_work_dir_orphans, self.s.work_root, active)
        if r["removed"]:
            log.info(
                "work_dir orphan cleanup removed %d dir(s), freed %.1f MB",
                r["removed"],
                r["freed_bytes"] / 1024**2,
            )
