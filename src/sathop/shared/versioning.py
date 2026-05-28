"""Semantic-version parsing for minimum-version enforcement."""

from __future__ import annotations

import re

_NUM_PREFIX = re.compile(r"^(\d+)")


def parse_version(v: str) -> tuple[int, int, int]:
    parts: list[int] = []
    for seg in v.strip().lstrip("v").split(".")[:3]:
        m = _NUM_PREFIX.match(seg)
        parts.append(int(m.group(1)) if m else 0)
    while len(parts) < 3:
        parts.append(0)
    return (parts[0], parts[1], parts[2])
