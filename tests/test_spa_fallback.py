"""SPA catch-all must not swallow unrouted /api/* paths.

Regression: the catch-all `/{full_path:path}` was matching `/api/wrong-thing`
and serving index.html with HTTP 200. API clients then saw HTML where they
expected JSON. The fix re-raises 404 for any unrouted /api path so FastAPI's
default error envelope flows through.
"""

from __future__ import annotations

import httpx

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
