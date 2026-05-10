"""Receiver health endpoint."""

from __future__ import annotations

import uvicorn
from fastapi import FastAPI


class HealthServer:
    def __init__(self, port: int, host: str = "127.0.0.1") -> None:
        self._host = host
        self._port = port
        self.app = FastAPI()

        @self.app.get("/health")
        async def health() -> dict:
            return {"status": "ok"}

    async def serve(self) -> None:
        config = uvicorn.Config(
            self.app,
            host=self._host,
            port=self._port,
            log_level="warning",
            access_log=False,
            lifespan="off",
        )
        await uvicorn.Server(config).serve()
