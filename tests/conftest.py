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
