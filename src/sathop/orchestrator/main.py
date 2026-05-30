"""Orchestrator entrypoint."""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from sathop import __version__

from .api import router as api_router
from .background import run_lease_sweeper, run_retention
from .config import settings
from .db import init_db, shutdown_db

PROJECT_ROOT = Path(__file__).resolve().parents[3]
WEB_DIST = PROJECT_ROOT / "frontend" / "dist"


def _print_banner() -> None:
    """Friendly startup summary — answers 'what URL do I visit?' on first run."""
    base = f"http://{settings.host}:{settings.port}"
    if WEB_DIST.is_dir():
        web = "mounted"
    else:
        web = "missing (run `cd frontend && npm run build`)"
    token = "set ✓" if settings.token else "OPEN — anyone on the network can call /api/*"
    lines = [
        "",
        f"  SatHop Orchestrator v{__version__}",
        f"    Listen   {settings.host}:{settings.port}",
        f"    API      {base}/api",
        f"    Web UI   {base}/   ({web})",
        f"    Token    {token}",
        f"    DB       {settings.db_path}",
        f"    Dev      {'on (autoreload)' if settings.dev else 'off'}",
        "",
    ]
    for ln in lines:
        print(ln, flush=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # frontend/dist ships inside the per-version bundle the entrypoint installs,
    # so it's always in lockstep with this code — no boot-time sync needed.
    _print_banner()
    await init_db()
    bg = [
        asyncio.create_task(run_lease_sweeper()),
        asyncio.create_task(run_retention()),
    ]
    try:
        yield
    finally:
        for t in bg:
            t.cancel()
        # gather(return_exceptions=True) swallows both CancelledError and any
        # exception a task raised during shutdown — same intent as the prior
        # per-task try/except, half the lines, parallel awaits.
        await asyncio.gather(*bg, return_exceptions=True)
        await shutdown_db()


app = FastAPI(title="SatHop Orchestrator", version=__version__, lifespan=lifespan)
app.include_router(api_router)


@app.get("/api/health")
async def health() -> dict:
    # web_sha lets the SPA detect a UI rebuild across reconnect and hard-reload
    # into the new bundle (version alone misses same-version asset rebuilds).
    stamp = WEB_DIST / ".sha256"
    web_sha = stamp.read_text().strip() if stamp.is_file() else None
    return {"status": "ok", "version": __version__, "web_sha": web_sha}


if WEB_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str) -> FileResponse:
        # Don't swallow unrouted /api/* — let FastAPI return its native 404 JSON
        # so API clients see a proper error envelope instead of HTML.
        if full_path.startswith("api/") or full_path == "api":
            raise HTTPException(status_code=404, detail="Not Found")
        target = WEB_DIST / full_path
        if full_path and target.is_file():
            return FileResponse(target)
        return FileResponse(WEB_DIST / "index.html")


def run() -> None:
    import uvicorn

    uvicorn.run(
        "sathop.orchestrator.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.dev,
        # Backstop: force-close any connection still open 3s into shutdown so a
        # lingering /api/stream can never hang the supervisor's restart. The
        # restart endpoint signals streams to close first, so this rarely fires.
        timeout_graceful_shutdown=3,
    )


if __name__ == "__main__":
    run()
