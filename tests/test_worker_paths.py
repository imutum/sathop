"""Worker path-segment helper.

Granule IDs are `<batch_id>:<user_gid>` from the orchestrator, with `:` an
NTFS-illegal character that broke `Path.mkdir` on Windows operators. The
helper centralizes filesystem-safe normalization so any path-component
derivation that incorporates a granule_id stays platform-portable."""

from __future__ import annotations

from sathop.worker._paths import safe_segment


def test_replaces_colon():
    """The colon between batch_id and user_gid is the production case."""
    assert safe_segment("rrsF87rs:2025327_0840") == "rrsF87rs_2025327_0840"


def test_replaces_all_windows_reserved_chars():
    """One pass through every char Windows rejects in a path component."""
    raw = 'a<b>c:d"e/f\\g|h?i*j'
    assert safe_segment(raw) == "a_b_c_d_e_f_g_h_i_j"


def test_passes_through_legal_chars():
    """Hyphens, underscores, dots, alnum — no rewrite, segment must be stable."""
    s = "batch_42-v1.0.tar.gz"
    assert safe_segment(s) == s


def test_replaces_nul_byte():
    """\\x00 is illegal in paths on every common OS — covers POSIX too."""
    assert safe_segment("a\x00b") == "a_b"


def test_idempotent():
    """safe_segment(safe_segment(x)) == safe_segment(x): the substitute char
    `_` is itself safe, so nothing flips on a second pass."""
    s = "rrsF87rs:2025327_0840"
    once = safe_segment(s)
    assert safe_segment(once) == once
