"""Path-traversal guard tests — covers both layers (input validation +
defense-in-depth resolve check) and the cross-cutting integration in
InputSpec, parse_shared_files, and add_granules."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from sathop.orchestrator.bundle_schema import parse_shared_files
from sathop.shared.protocol import InputSpec
from sathop.shared.safe_path import is_safe_name, safe_join

# ─── is_safe_name ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "name",
    ["file.tif", "MOD09A1.A2024001.h09v05.061.tif", "no-dots", "_underscore", "数据"],
)
def test_is_safe_name_accepts_plain_segments(name: str) -> None:
    assert is_safe_name(name) is True


@pytest.mark.parametrize(
    "name",
    [
        "",
        "..",
        "../escape",
        "sub/file.tif",
        "sub\\file.tif",
        "/abs/path",
        "C:/Windows",
        "with\x00null",
    ],
)
def test_is_safe_name_rejects_unsafe(name: str) -> None:
    assert is_safe_name(name) is False


# ─── safe_join containment ─────────────────────────────────────────────────


def test_safe_join_returns_child_path(tmp_path):
    base = tmp_path / "data"
    base.mkdir()
    p = safe_join(base, "obj.tif")
    assert p == (base / "obj.tif").resolve()


def test_safe_join_allows_multi_segment_key(tmp_path):
    base = tmp_path / "data"
    base.mkdir()
    p = safe_join(base, "year/2024/obj.tif")
    assert p == (base / "year/2024/obj.tif").resolve()


def test_safe_join_rejects_parent_escape(tmp_path):
    base = tmp_path / "data"
    base.mkdir()
    with pytest.raises(ValueError, match="escapes base"):
        safe_join(base, "../escape.tif")


def test_safe_join_rejects_absolute_segment(tmp_path):
    base = tmp_path / "data"
    base.mkdir()
    other = tmp_path / "elsewhere"
    other.mkdir()
    with pytest.raises(ValueError, match="escapes base"):
        safe_join(base, str(other / "x.tif"))


# ─── input-layer rejection on Pydantic + manifest ─────────────────────────


def test_input_spec_filename_rejects_path_traversal():
    with pytest.raises(ValidationError):
        InputSpec(url="http://x", filename="../escape.tif", product="P")


def test_input_spec_filename_rejects_separator():
    with pytest.raises(ValidationError):
        InputSpec(url="http://x", filename="sub/file.tif", product="P")


def test_parse_shared_files_rejects_path_traversal():
    with pytest.raises(ValueError, match="safe segment"):
        parse_shared_files({"shared_files": ["../escape"]})


def test_parse_shared_files_rejects_separator():
    with pytest.raises(ValueError, match="safe segment"):
        parse_shared_files({"shared_files": ["sub/coast.shp"]})
