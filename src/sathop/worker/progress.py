"""Local HTTP endpoint the running bundle POSTs checkpoints to.

Binds 127.0.0.1:<progress_port>. For each granule we issue a short-lived
nonce that rides in the URL path — the nonce IS the auth, and it's revoked
the moment the granule finishes. Each checkpoint is handed to a non-blocking
sink (the worker's `ProgressBuffer`) that coalesces it with every other
in-flight granule's progress into batched POSTs upstream; the download
callback's ticks feed the same sink via `forward()`, so this server is the
single progress funnel. Sink-failure is swallowed (the bundle shouldn't care
if upstream is briefly down — the buffer owns retry/shedding)."""

from __future__ import annotations

import logging
import secrets
from collections.abc import Callable

import uvicorn
from fastapi import FastAPI, HTTPException, Request

from sathop.shared.protocol import ProgressEvent

log = logging.getLogger("sathop.worker.progress")

ProgressSink = Callable[[str, ProgressEvent], None]


class ProgressServer:
    def __init__(self, sink: ProgressSink, port: int, host: str = "127.0.0.1") -> None:
        self._sink = sink
        # Display-only progress can be turned off fleet-wide (fast detail mode):
        # both funnels — the download callback and the bundle's self-report — go
        # through forward(), so this one flag suppresses every progress checkpoint
        # without refusing the bundle's POST (it still gets a 200).
        self._enabled = True
        self._port = port
        self._host = host
        self._tokens: dict[str, tuple[str, str]] = {}  # nonce → (granule_id, batch_id)
        self.base_url = f"http://{host}:{port}"
        self.app = FastAPI()

        @self.app.get("/health")
        async def health() -> dict:
            return {"status": "ok"}

        @self.app.post("/progress/{nonce}")
        async def progress(nonce: str, req: Request) -> dict:
            ids = self._tokens.get(nonce)
            if ids is None:
                raise HTTPException(404, "unknown or expired progress token")
            gid, batch_id = ids
            try:
                body = await req.json()
            except Exception as e:
                raise HTTPException(400, f"invalid json: {e}")
            try:
                event = ProgressEvent.model_validate(body)
            except Exception as e:
                raise HTTPException(422, f"bad event shape: {e}")
            event.batch_id = batch_id
            self.forward(gid, event)
            return {"ok": True}

    def forward(self, granule_id: str, event: ProgressEvent) -> None:
        """Hand a checkpoint to the buffer. Non-blocking and best-effort: a sink
        error is swallowed so neither the bundle's POST nor the download callback
        is ever broken by progress plumbing. A no-op when progress is disabled
        (fast detail mode)."""
        if not self._enabled:
            return
        try:
            self._sink(granule_id, event)
        except Exception as e:  # noqa: BLE001
            log.warning("forward progress for %s failed: %s", granule_id, e)

    def issue(self, granule_id: str, batch_id: str) -> tuple[str, str]:
        nonce = secrets.token_urlsafe(16)
        self._tokens[nonce] = (granule_id, batch_id)
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
