"""Shared test fixtures."""

from __future__ import annotations

import socket
import sys
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
