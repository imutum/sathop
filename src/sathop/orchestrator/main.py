"""Orchestrator entrypoint."""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api import router as api_router
from .config import settings
from .db import init_db, shutdown_db
from .background import run_lease_sweeper, run_retention

PROJECT_ROOT = Path(__file__).resolve().parents[3]
WEB_DIST = PROJECT_ROOT / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
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
        for t in bg:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        await shutdown_db()


app = FastAPI(title="SatHop Orchestrator", version="0.1.0", lifespan=lifespan)
app.include_router(api_router)


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok", "version": "0.1.0"}


if WEB_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str) -> FileResponse:
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
    )


if __name__ == "__main__":
    run()
