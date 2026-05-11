"""URL parsing + env-based orchestrator resolution.

Covers `sathop.shared.config`: `parse_sathop_url`, `resolve_orch`, `cli_resolve_orch`.
Pure functions — no infrastructure mocks needed. Env tests use monkeypatch.
"""

from __future__ import annotations

import pytest

from sathop.shared.config import cli_resolve_orch, parse_sathop_url, resolve_orch

# ─── parse_sathop_url: scheme dispatch ─────────────────────────────────────


def test_parse_sathop_url_http_scheme():
    assert parse_sathop_url("sathop://tok@host:8000") == ("http://host:8000", "tok")


def test_parse_sathop_url_https_scheme():
    assert parse_sathop_url("sathops://tok@host:8443") == ("https://host:8443", "tok")


@pytest.mark.parametrize("bad", ["http://tok@host", "https://tok@host", "ftp://tok@host", "tok@host"])
def test_parse_sathop_url_rejects_other_schemes(bad: str):
    with pytest.raises(ValueError, match="sathop:// or sathops://"):
        parse_sathop_url(bad)


# ─── parse_sathop_url: token slot variations ───────────────────────────────


def test_parse_sathop_url_token_in_userinfo():
    """sathop://TOKEN@host — token sits in username slot."""
    assert parse_sathop_url("sathop://abc123@host:9000") == ("http://host:9000", "abc123")


def test_parse_sathop_url_token_in_password_slot():
    """sathop://:TOKEN@host — token sits in password slot (after the colon)."""
    assert parse_sathop_url("sathop://:abc123@host:9000") == ("http://host:9000", "abc123")


def test_parse_sathop_url_password_slot_wins_over_username():
    """If both userinfo halves are filled, the password half is taken first."""
    orch_url, token = parse_sathop_url("sathop://user:pwtok@host:9000")
    assert orch_url == "http://host:9000"
    assert token == "pwtok"


def test_parse_sathop_url_url_encoded_token():
    """URL-encoded tokens get decoded (so `+`, `/`, `=` in base64 tokens survive)."""
    _, token = parse_sathop_url("sathop://abc%2F%2B%3D@host:8000")
    assert token == "abc/+="


# ─── parse_sathop_url: rejection branches ──────────────────────────────────


def test_parse_sathop_url_missing_token():
    with pytest.raises(ValueError, match="missing token"):
        parse_sathop_url("sathop://host:8000")


def test_parse_sathop_url_empty_token():
    """sathop://@host: both userinfo slots empty → no token."""
    with pytest.raises(ValueError, match="missing token"):
        parse_sathop_url("sathop://@host:8000")


def test_parse_sathop_url_missing_host():
    with pytest.raises(ValueError, match="missing host"):
        parse_sathop_url("sathop://tok@")


# ─── parse_sathop_url: host/port/path shapes ───────────────────────────────


def test_parse_sathop_url_no_port():
    assert parse_sathop_url("sathop://tok@host") == ("http://host", "tok")


def test_parse_sathop_url_strips_trailing_slash():
    assert parse_sathop_url("sathop://tok@host:8000/") == ("http://host:8000", "tok")


def test_parse_sathop_url_keeps_subpath():
    """A non-trivial path is preserved (proxy-mounted orchestrator)."""
    assert parse_sathop_url("sathop://tok@host:8000/api/v1") == ("http://host:8000/api/v1", "tok")


def test_parse_sathop_url_strips_trailing_slash_on_subpath():
    assert parse_sathop_url("sathop://tok@host:8000/api/") == ("http://host:8000/api", "tok")


def test_parse_sathop_url_lowercases_hostname():
    """urlparse normalises hostname to lowercase — confirm that flows through."""
    orch_url, _ = parse_sathop_url("sathop://tok@EXAMPLE.com:8000")
    assert orch_url == "http://example.com:8000"


# ─── resolve_orch: env-driven ──────────────────────────────────────────────


def test_resolve_orch_url_form_wins(monkeypatch):
    """SATHOP_URL set → ignores split form entirely."""
    monkeypatch.setenv("SATHOP_URL", "sathops://tok@host:443")
    monkeypatch.setenv("SATHOP_ORCH_URL", "http://other")
    monkeypatch.setenv("SATHOP_TOKEN", "other-tok")
    assert resolve_orch() == ("https://host:443", "tok")


def test_resolve_orch_split_form(monkeypatch):
    monkeypatch.delenv("SATHOP_URL", raising=False)
    monkeypatch.setenv("SATHOP_ORCH_URL", "http://host:8000")
    monkeypatch.setenv("SATHOP_TOKEN", "tok")
    assert resolve_orch() == ("http://host:8000", "tok")


def test_resolve_orch_split_form_strips_trailing_slash(monkeypatch):
    monkeypatch.delenv("SATHOP_URL", raising=False)
    monkeypatch.setenv("SATHOP_ORCH_URL", "http://host:8000/")
    monkeypatch.setenv("SATHOP_TOKEN", "tok")
    assert resolve_orch() == ("http://host:8000", "tok")


def test_resolve_orch_url_overrides_whitespace_only(monkeypatch):
    """Whitespace-only SATHOP_URL is treated as unset (stripped → empty)."""
    monkeypatch.setenv("SATHOP_URL", "   ")
    monkeypatch.setenv("SATHOP_ORCH_URL", "http://host:8000")
    monkeypatch.setenv("SATHOP_TOKEN", "tok")
    assert resolve_orch() == ("http://host:8000", "tok")


def test_resolve_orch_missing_everything_raises(monkeypatch):
    monkeypatch.delenv("SATHOP_URL", raising=False)
    monkeypatch.delenv("SATHOP_ORCH_URL", raising=False)
    monkeypatch.delenv("SATHOP_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="missing orchestrator URL"):
        resolve_orch()


def test_resolve_orch_missing_token_raises(monkeypatch):
    monkeypatch.delenv("SATHOP_URL", raising=False)
    monkeypatch.setenv("SATHOP_ORCH_URL", "http://host:8000")
    monkeypatch.delenv("SATHOP_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="missing SATHOP_TOKEN"):
        resolve_orch()


def test_resolve_orch_invalid_url_propagates_value_error(monkeypatch):
    """parse_sathop_url's ValueError bubbles up unchanged."""
    monkeypatch.setenv("SATHOP_URL", "http://wrong-scheme")
    with pytest.raises(ValueError, match="sathop:// or sathops://"):
        resolve_orch()


# ─── cli_resolve_orch: arg-driven ──────────────────────────────────────────


def test_cli_resolve_orch_url_wins():
    """--url takes precedence; --orch-url + --token ignored."""
    assert cli_resolve_orch("sathop://tok@host:8000", "http://ignored", "ignored") == (
        "http://host:8000",
        "tok",
    )


def test_cli_resolve_orch_split_form():
    assert cli_resolve_orch("", "http://host:8000", "tok") == ("http://host:8000", "tok")


def test_cli_resolve_orch_strips_trailing_slash():
    assert cli_resolve_orch("", "http://host:8000/", "tok") == ("http://host:8000", "tok")


def test_cli_resolve_orch_missing_orch_url_raises():
    with pytest.raises(ValueError, match="missing orchestrator"):
        cli_resolve_orch("", "", "tok")


def test_cli_resolve_orch_missing_token_raises():
    with pytest.raises(ValueError, match="missing token"):
        cli_resolve_orch("", "http://host:8000", "")


def test_cli_resolve_orch_anonymous_allowed_when_not_required():
    """require_token=False permits an empty token (sathop-reconcile read-only paths)."""
    assert cli_resolve_orch("", "http://host:8000", "", require_token=False) == (
        "http://host:8000",
        "",
    )


def test_cli_resolve_orch_invalid_url_propagates_value_error():
    with pytest.raises(ValueError, match="sathop:// or sathops://"):
        cli_resolve_orch("ftp://wrong", "", "")
