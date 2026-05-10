"""Worker-side pipeline stage accounting.

The worker reports these counters on every heartbeat. Keeping the names and
heartbeat field mapping in one place prevents the pipeline loop, heartbeat
payload, and UI-facing queue labels from drifting apart.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Literal

StageName = Literal[
    "pending_download",
    "downloading",
    "pending_processing",
    "processing",
    "pending_upload",
    "uploading",
]

PENDING_DOWNLOAD: StageName = "pending_download"
DOWNLOADING: StageName = "downloading"
PENDING_PROCESSING: StageName = "pending_processing"
PROCESSING: StageName = "processing"
PENDING_UPLOAD: StageName = "pending_upload"
UPLOADING: StageName = "uploading"

_STAGE_NAMES: tuple[StageName, ...] = (
    PENDING_DOWNLOAD,
    DOWNLOADING,
    PENDING_PROCESSING,
    PROCESSING,
    PENDING_UPLOAD,
    UPLOADING,
)


@dataclass(frozen=True)
class StageSnapshot:
    pending_download: int = 0
    downloading: int = 0
    pending_processing: int = 0
    processing: int = 0
    pending_upload: int = 0
    uploading: int = 0

    @property
    def total(self) -> int:
        return (
            self.pending_download
            + self.downloading
            + self.pending_processing
            + self.processing
            + self.pending_upload
            + self.uploading
        )

    def heartbeat_fields(self) -> dict[str, int]:
        return {
            "queue_pending_download": self.pending_download,
            "queue_downloading": self.downloading,
            "queue_pending_processing": self.pending_processing,
            "queue_processing": self.processing,
            "queue_pending_upload": self.pending_upload,
            "queue_uploading": self.uploading,
        }


class WorkerStages:
    def __init__(self) -> None:
        self._counts: Counter[str] = Counter()

    @property
    def total(self) -> int:
        return self.snapshot().total

    def snapshot(self) -> StageSnapshot:
        return StageSnapshot(*(self._counts[stage] for stage in _STAGE_NAMES))

    def tracker(self) -> StageTracker:
        return StageTracker(self)

    def _enter(self, stage: StageName) -> None:
        self._counts[stage] += 1

    def _exit(self, stage: StageName) -> None:
        self._counts[stage] -= 1
        if self._counts[stage] <= 0:
            del self._counts[stage]


class StageTracker:
    """Tracks the single queue stage held by one granule handler."""

    def __init__(self, stages: WorkerStages) -> None:
        self._stages = stages
        self._current: StageName | None = None

    def enter(self, stage: StageName) -> None:
        self.exit()
        self._stages._enter(stage)
        self._current = stage

    def exit(self) -> None:
        if self._current is None:
            return
        self._stages._exit(self._current)
        self._current = None
