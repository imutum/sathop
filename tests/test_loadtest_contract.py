"""The release load gate must count HTTP failures, not only transport errors."""

import asyncio
import runpy

import httpx
import pytest


@pytest.mark.parametrize("loop", ["worker_loop", "health_sampler"])
async def test_http_500_fails_load_gate(project_root, loop):
    driver = runpy.run_path(str(project_root / "scripts" / "loadtest_orch.py"))
    stop = asyncio.Event()
    stats = driver["Stats"]()

    def respond(request):
        if request.url.path.endswith("/register"):
            return httpx.Response(200, json={"ok": True})
        if "/deletable/" in request.url.path:
            return httpx.Response(200, json=[])
        stop.set()
        return httpx.Response(500, json={"detail": "injected server failure"})

    async with httpx.AsyncClient(
        base_url="http://test",
        transport=httpx.MockTransport(respond),
        event_hooks={"response": [driver["check_response"]]},
    ) as client:
        if loop == "worker_loop":
            await driver[loop](client, "worker", 1, stats, stop, batch=True)
            assert stats.events == 0
        else:
            await driver[loop](client, stats, stop)
            assert stats.health == [99_999.0]
    assert stats.errors == 1
