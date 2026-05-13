"""Bearer header + httpx client factories.

Covers `sathop.shared.http`: thin wrappers over httpx that everything else
in the project layers on top of. Verifies header shape + client kwargs are
threaded through correctly.
"""

from __future__ import annotations

import httpx
import pytest

from sathop.shared.http import bearer_headers, make_orch_client, make_sync_orch_client


def test_bearer_headers_shape():
    assert bearer_headers("abc") == {"Authorization": "Bearer abc"}


def test_bearer_headers_with_empty_token():
    """Empty token yields no header — anonymous callers (orchestrator in open
    mode, CLI without --token) don't send a phantom `Authorization: Bearer `
    that obscures the intent on the wire."""
    assert bearer_headers("") == {}


def test_bearer_headers_passes_through_special_chars():
    """No URL-encoding here — bearer tokens are opaque to the HTTP layer."""
    assert bearer_headers("tok=with/+special") == {"Authorization": "Bearer tok=with/+special"}


# ─── async client ──────────────────────────────────────────────────────────


async def test_make_orch_client_sets_base_url_and_auth():
    c = make_orch_client("http://host:8000", "tok")
    try:
        assert isinstance(c, httpx.AsyncClient)
        assert str(c.base_url) == "http://host:8000"
        assert c.headers["Authorization"] == "Bearer tok"
    finally:
        await c.aclose()


async def test_make_orch_client_default_timeout():
    c = make_orch_client("http://host:8000", "tok")
    try:
        assert c.timeout.read == pytest.approx(30.0)
    finally:
        await c.aclose()


async def test_make_orch_client_custom_timeout():
    c = make_orch_client("http://host:8000", "tok", timeout=5.0)
    try:
        assert c.timeout.read == pytest.approx(5.0)
    finally:
        await c.aclose()


# ─── sync client ───────────────────────────────────────────────────────────


def test_make_sync_orch_client_sets_base_url_and_auth():
    c = make_sync_orch_client("http://host:8000", "tok")
    try:
        assert isinstance(c, httpx.Client)
        assert str(c.base_url) == "http://host:8000"
        assert c.headers["Authorization"] == "Bearer tok"
    finally:
        c.close()


def test_make_sync_orch_client_default_timeout():
    c = make_sync_orch_client("http://host:8000", "tok")
    try:
        assert c.timeout.read == pytest.approx(30.0)
    finally:
        c.close()


def test_make_sync_orch_client_custom_timeout():
    c = make_sync_orch_client("http://host:8000", "tok", timeout=120.0)
    try:
        assert c.timeout.read == pytest.approx(120.0)
    finally:
        c.close()


# ─── live request roundtrip via MockTransport ──────────────────────────────


def test_sync_client_sends_bearer_header():
    """Real HTTP roundtrip through httpx's mock transport — confirms the
    header survives client construction → request dispatch."""
    captured: dict[str, str] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["auth"] = req.headers.get("Authorization", "")
        return httpx.Response(200, json={"ok": True})

    c = httpx.Client(
        base_url="http://host:8000",
        headers={"Authorization": "Bearer mytok"},
        transport=httpx.MockTransport(handler),
    )
    try:
        r = c.get("/api/anything")
        assert r.status_code == 200
        assert captured["auth"] == "Bearer mytok"
    finally:
        c.close()
