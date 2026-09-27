"""SPA catch-all must not swallow unrouted /api/* paths.

Regression: the catch-all `/{full_path:path}` was matching `/api/wrong-thing`
and serving index.html with HTTP 200. API clients then saw HTML where they
expected JSON. The fix re-raises 404 for any unrouted /api path so FastAPI's
default error envelope flows through.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI

from sathop.orchestrator import main
from sathop.orchestrator.main import WEB_DIST, app


async def _get(path: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        return await c.get(path)


async def test_health_returns_json():
    r = await _get("/api/health")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")


async def test_unknown_api_path_returns_json_404():
    r = await _get("/api/no-such-endpoint")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/json")


async def test_spa_route_returns_index_html():
    if not WEB_DIST.is_dir():
        # Without a built SPA there's no fallback; skip.
        return
    r = await _get("/batches")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")


@pytest.fixture
async def spa_client(tmp_path, monkeypatch):
    # Independent of a frontend build, so these guards also run in Python CI.
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<html>test app</html>")
    (web / "icon.svg").write_text("<svg/>")
    (tmp_path / "private.txt").write_text("private fixture outside web root")
    monkeypatch.setattr(main, "WEB_DIST", web)
    test_app = FastAPI()
    test_app.get("/{full_path:path}")(main.spa_fallback)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=test_app), base_url="http://test"
    ) as client:
        yield client


@pytest.mark.parametrize(
    "path", ["/%2e%2e/private.txt", "/..%2fprivate.txt", "/%2e%2e%5cprivate.txt", "/bad%00path"]
)
async def test_spa_rejects_paths_outside_web_root(spa_client, path):
    response = await spa_client.get(path)
    assert response.status_code == 404
    assert "private fixture" not in response.text


async def test_spa_still_serves_assets_and_client_routes(spa_client):
    assert (await spa_client.get("/icon.svg")).text == "<svg/>"
    assert (await spa_client.get("/batches/example")).text == "<html>test app</html>"
    assert (await spa_client.get("/api/missing")).status_code == 404
