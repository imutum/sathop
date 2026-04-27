"""Local HTTP endpoint the running bundle POSTs checkpoints to.

Binds 127.0.0.1:<progress_port>. For each granule we issue a short-lived
nonce that rides in the URL path — the nonce IS the auth, and it's revoked
the moment the granule finishes. Events are forwarded to the orchestrator
via the worker's existing client; forward-failure is swallowed (bundle
shouldn't care if upstream is briefly down)."""

from __future__ import annotations

import logging
import secrets
from typing import TYPE_CHECKING

import uvicorn
from fastapi import FastAPI, HTTPException, Request

from sathop.shared.protocol import ProgressEvent

if TYPE_CHECKING:
    from .agent import OrchestratorClient

log = logging.getLogger("sathop.worker.progress")


class ProgressServer:
    def __init__(self, client: OrchestratorClient, port: int, host: str = "127.0.0.1") -> None:
        self._client = client
        self._port = port
        self._host = host
        self._tokens: dict[str, str] = {}  # nonce → granule_id
        self.base_url = f"http://{host}:{port}"
        self.app = FastAPI()

        @self.app.post("/progress/{nonce}")
        async def progress(nonce: str, req: Request) -> dict:
            gid = self._tokens.get(nonce)
            if gid is None:
                raise HTTPException(404, "unknown or expired progress token")
            try:
                body = await req.json()
            except Exception as e:
                raise HTTPException(400, f"invalid json: {e}")
            try:
                event = ProgressEvent.model_validate(body)
            except Exception as e:
                raise HTTPException(422, f"bad event shape: {e}")
            try:
                await self._client.report_progress(gid, event)
            except Exception as e:
                # Upstream failure is not the bundle's problem.
                log.warning("forward progress for %s failed: %s", gid, e)
            return {"ok": True}

    def issue(self, granule_id: str) -> tuple[str, str]:
        nonce = secrets.token_urlsafe(16)
        self._tokens[nonce] = granule_id
        return nonce, f"{self.base_url}/progress/{nonce}"

    def revoke(self, nonce: str) -> None:
        self._tokens.pop(nonce, None)

    async def serve(self) -> None:
        config = uvicorn.Config(
            self.app,
            host=self._host,
            port=self._port,
            log_level="warning",
            access_log=False,
            lifespan="off",
        )
        server = uvicorn.Server(config)
        await server.serve()
