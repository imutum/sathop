"""Strict byte-range metadata parsing shared by both download paths (RFC 9110)."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ContentRange:
    start: int
    end: int
    total: int | None


def parse_content_range(value: str) -> ContentRange | None:
    match = re.fullmatch(r"bytes ([0-9]+)-([0-9]+)/([0-9]+|\*)", value.strip(), re.IGNORECASE)
    if not match:
        return None
    start, end = int(match[1]), int(match[2])
    total = None if match[3] == "*" else int(match[3])
    if start > end or (total is not None and end >= total):
        return None
    return ContentRange(start, end, total)


def unsatisfied_range_size(value: str) -> int | None:
    match = re.fullmatch(r"bytes \*/([0-9]+)", value.strip(), re.IGNORECASE)
    return int(match[1]) if match else None
