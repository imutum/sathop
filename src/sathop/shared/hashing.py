from __future__ import annotations

import hashlib
from pathlib import Path

_DEFAULT_CHUNK = 1 << 20  # 1 MiB — balances syscall overhead vs memory


def sha256_file(path: Path, chunk_size: int = _DEFAULT_CHUNK) -> str:
    """Hex-encoded sha256 of a file's contents, read in chunks."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(chunk_size), b""):
            h.update(block)
    return h.hexdigest()
