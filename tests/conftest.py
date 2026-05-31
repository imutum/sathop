"""Shared test fixtures."""

from __future__ import annotations

import socket
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

src = ROOT / "src"
if src.is_dir() and str(src) not in sys.path:
    sys.path.insert(0, str(src))


@pytest.fixture(scope="session")
def project_root() -> Path:
    return ROOT


@pytest.fixture(scope="session")
def py() -> str:
    """Absolute path to the project venv's Python."""
    p = ROOT / ".venv" / "Scripts" / "python.exe"
    if not p.exists():
        p = ROOT / ".venv" / "bin" / "python"
    return str(p)


@pytest.fixture
def free_port() -> int:
    """Return an OS-assigned unused TCP port."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(autouse=True)
def _clear_in_memory_stores():
    from sathop.orchestrator.api.admin import reset_latest_cache, reset_overview_cache
    from sathop.orchestrator.api.batches import reset_batches_cache
    from sathop.orchestrator.api.metrics import reset_metrics_cache
    from sathop.orchestrator.api.progress import _clear as clear_progress
    from sathop.orchestrator.event_store import _clear as clear_events
    from sathop.orchestrator.pubsub import reset_coalesce, reset_shutdown
    from sathop.orchestrator.telemetry import _clear as clear_telemetry

    clear_events()
    clear_telemetry()
    clear_progress()
    reset_shutdown()  # module-global flag must not leak a "shutting down" state
    reset_coalesce()  # cancel pending nudge-window timers so they don't cross tests
    reset_overview_cache()  # 1s TTL cache must not leak a stale overview across tests
    reset_metrics_cache()  # same 1s TTL cache, on the metrics scrape path
    reset_batches_cache()  # 1s TTL cache on the batch-list aggregate
    reset_latest_cache()  # 5min latest-release cache must not leak across tests
    yield
    clear_events()
    clear_telemetry()
    clear_progress()
    reset_shutdown()
    reset_coalesce()
    reset_overview_cache()
    reset_metrics_cache()
    reset_batches_cache()
    reset_latest_cache()


@pytest.fixture
def patch_settings() -> Callable[..., None]:
    """Override orchestrator `Settings` fields for one test, with auto-restore.

    `Settings` is a frozen dataclass module-level singleton — fine for prod,
    but tests need per-test overrides (db_path, token, max_* thresholds…).
    This fixture is the sole place the project performs the `object.__setattr__`
    bypass; test files just call `patch_settings(field=value, …)` and the
    snapshot taken on first patch is rolled back at fixture teardown, even
    when the test raises.
    """
    from sathop.orchestrator.config import settings

    snapshot: dict[str, object] = {}

    def patch(**overrides: object) -> None:
        for name, value in overrides.items():
            if name not in snapshot:
                snapshot[name] = getattr(settings, name)
            object.__setattr__(settings, name, value)

    yield patch
    for name, value in snapshot.items():
        object.__setattr__(settings, name, value)
