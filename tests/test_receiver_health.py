"""Receiver HealthServer: tiny FastAPI app behind uvicorn.

The serve() coroutine runs uvicorn which would bind a real port — for unit
tests we drive the app directly through FastAPI's TestClient. The /health
shape is what docker-compose's healthcheck curl-greps for; locking it in
prevents an accidental rename or status-code drift from silently killing
container restarts.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from sathop.receiver.health import HealthServer


def test_health_endpoint_returns_ok_status():
    server = HealthServer(port=0)
    with TestClient(server.app) as client:
        r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_health_endpoint_only_path():
    """The server intentionally exposes nothing else — sniffing other paths
    must 404 so the surface stays minimal."""
    server = HealthServer(port=0)
    with TestClient(server.app) as client:
        assert client.get("/").status_code == 404
        assert client.get("/metrics").status_code == 404


def test_health_server_respects_host_and_port_args():
    """The constructor wires host/port into uvicorn.Config later; verifying
    the attrs guards against a refactor that loses one of the args."""
    server = HealthServer(port=9003, host="0.0.0.0")
    assert server._host == "0.0.0.0"
    assert server._port == 9003


def test_health_server_default_host_is_loopback():
    """The compose healthcheck targets 127.0.0.1 inside the container —
    binding to 0.0.0.0 by default would needlessly expose the port."""
    server = HealthServer(port=9003)
    assert server._host == "127.0.0.1"
