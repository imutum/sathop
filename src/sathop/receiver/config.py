"""Receiver runtime settings."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from sathop.shared.config import resolve_orch


@dataclass(frozen=True)
class Settings:
    receiver_id: str
    orchestrator_url: str
    token: str
    storage_dir: Path
    poll_interval: int
    concurrent_pulls: int
    platform: Literal["linux", "windows"]
    tls_verify: bool = True
    tls_trust_orch: bool = True
    pull_segments: int = 4
    pull_segment_min_bytes: int = 4 * 1024 * 1024
    health_port: int = 9003


def _parse_bool(s: str, default: bool) -> bool:
    return s.strip().lower() not in ("0", "false", "no", "off") if s else default


def load() -> Settings:
    orchestrator_url, token = resolve_orch()
    return Settings(
        receiver_id=os.environ["SATHOP_RECEIVER_ID"],
        orchestrator_url=orchestrator_url,
        token=token,
        storage_dir=Path(os.environ["SATHOP_STORAGE_DIR"]),
        poll_interval=int(os.getenv("SATHOP_POLL_INTERVAL", "10")),
        concurrent_pulls=int(os.getenv("SATHOP_CONCURRENT_PULLS", "16")),
        platform=cast(Literal["linux", "windows"], "windows" if sys.platform == "win32" else "linux"),
        tls_verify=_parse_bool(os.getenv("SATHOP_TLS_VERIFY", ""), True),
        tls_trust_orch=_parse_bool(os.getenv("SATHOP_TLS_TRUST_ORCH", ""), True),
        pull_segments=int(os.getenv("SATHOP_PULL_SEGMENTS", "4")),
        pull_segment_min_bytes=int(os.getenv("SATHOP_PULL_SEGMENT_MIN_BYTES", str(4 * 1024 * 1024))),
        health_port=int(os.getenv("SATHOP_HEALTH_PORT", "9003")),
    )
