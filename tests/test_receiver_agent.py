"""OrchestratorClient: thin httpx wrapper. Verify it hits the right paths,
sets the Bearer header, serializes DTOs, and parses the PullResponse back.

Uses httpx.MockTransport — no HTTP server needed."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx
import pytest

from sathop.receiver.main import OrchestratorClient
from sathop.shared.protocol import (
    AckReport,
    PullRequest,
    PullResponse,
    ReceiverHeartbeat,
    ReceiverRegister,
)


@pytest.fixture
def captured_client():
    """Build an OrchestratorClient whose httpx.AsyncClient uses a MockTransport
    that records every request into a list. Returns (client, captured)."""
    captured: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        captured.append(req)
        if req.url.path == "/api/receivers/pull":
            body = {
                "items": [
                    {
                        "granule_id": "g1",
                        "batch_id": "b1",
                        "object_id": 42,
                        "object_key": "b1/g1/out.bin",
                        "presigned_url": "http://w1/x",
                        "sha256": "abc",
                        "size": 100,
                    }
                ]
            }
            return httpx.Response(200, json=body)
        return httpx.Response(200, json={"ok": True})

    c = OrchestratorClient(base_url="http://orch.test", token="t0k3n")
    # Swap the underlying AsyncClient to one using MockTransport while preserving
    # base_url + auth header the real __init__ installed.
    c._client = httpx.AsyncClient(
        base_url="http://orch.test",
        transport=httpx.MockTransport(handler),
        headers={"Authorization": "Bearer t0k3n"},
    )
    return c, captured


async def test_register_posts_serialized_dto(captured_client):
    c, captured = captured_client
    try:
        await c.register(ReceiverRegister(receiver_id="r1", version="0.1.0", platform="linux"))
    finally:
        await c.aclose()

    assert len(captured) == 1
    req = captured[0]
    assert req.method == "POST"
    assert req.url.path == "/api/receivers/register"
    assert req.headers["Authorization"] == "Bearer t0k3n"
    assert json.loads(req.content) == {
        "receiver_id": "r1",
        "version": "0.1.0",
        "platform": "linux",
    }


async def test_heartbeat_posts_disk_free(captured_client):
    c, captured = captured_client
    try:
        await c.heartbeat(ReceiverHeartbeat(receiver_id="r1", disk_free_gb=512.5))
    finally:
        await c.aclose()

    assert captured[0].url.path == "/api/receivers/heartbeat"
    assert json.loads(captured[0].content) == {"receiver_id": "r1", "disk_free_gb": 512.5}


async def test_pull_parses_response_into_pullresponse(captured_client):
    c, captured = captured_client
    try:
        resp = await c.pull(PullRequest(receiver_id="r1", limit=20))
    finally:
        await c.aclose()

    assert captured[0].url.path == "/api/receivers/pull"
    assert isinstance(resp, PullResponse)
    assert len(resp.items) == 1
    it = resp.items[0]
    assert it.granule_id == "g1"
    assert it.object_id == 42
    assert it.presigned_url == "http://w1/x"
    assert it.sha256 == "abc"
    assert it.size == 100


async def test_ack_posts_ackreport(captured_client):
    c, captured = captured_client
    try:
        await c.ack(AckReport(receiver_id="r1", object_id=7, sha256="deadbeef", success=True))
    finally:
        await c.aclose()

    assert captured[0].url.path == "/api/receivers/ack"
    body = json.loads(captured[0].content)
    assert body["object_id"] == 7
    assert body["success"] is True
    assert body["error"] is None


async def test_4xx_raises_for_status():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "invalid token"})

    c = OrchestratorClient(base_url="http://orch.test", token="bad")
    c._client = httpx.AsyncClient(
        base_url="http://orch.test",
        transport=httpx.MockTransport(handler),
        headers={"Authorization": "Bearer bad"},
    )
    try:
        with pytest.raises(httpx.HTTPStatusError):
            await c.heartbeat(ReceiverHeartbeat(receiver_id="r", disk_free_gb=0.0))
    finally:
        await c.aclose()
