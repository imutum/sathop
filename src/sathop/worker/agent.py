"""Async HTTP client for orchestrator API.

Every method goes through `_post` / `_get`, which centralise:
  - Bearer auth (via shared.http)
  - 401 → fatal os._exit(1) (token mismatch silently retrying would mask
    config errors; surfacing as a flapping container makes them obvious)
  - raise_for_status on other non-2xx so callers can decide handler-level
    semantics (e.g. heartbeat 404 → re-register, lease 403 → backoff)
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any

import httpx

from sathop.shared.http import make_orch_client
from sathop.shared.protocol import (
    DeletableGranule,
    GranuleState,
    LeaseRequest,
    LeaseResponse,
    ProcessFailure,
    ProgressEvent,
    StateUpdate,
    UploadedObject,
    UploadReport,
    WorkerHeartbeat,
    WorkerHeartbeatResponse,
    WorkerRegister,
    WorkerRegisterResponse,
)

log = logging.getLogger("sathop.worker.agent")


class OrchestratorClient:
    def __init__(self, base_url: str, token: str, timeout: float = 30.0) -> None:
        self._client = make_orch_client(base_url, token, timeout)

    async def aclose(self) -> None:
        await self._client.aclose()

    def _check_auth(self, r: httpx.Response, path: str) -> None:
        """SATHOP_TOKEN mismatch on any orch endpoint is fatal — silent retry
        would mask the misconfig. os._exit(1) lets docker `restart:
        unless-stopped` make the problem visible (flapping container)."""
        if r.status_code == 401:
            log.error("orch %s returned 401 — SATHOP_TOKEN mismatch; exiting for container restart", path)
            os._exit(1)

    async def _post(self, path: str, json: Any | None = None) -> httpx.Response:
        r = await self._client.post(path, json=json)
        self._check_auth(r, path)
        r.raise_for_status()
        return r

    async def _get(self, path: str) -> httpx.Response:
        r = await self._client.get(path)
        self._check_auth(r, path)
        r.raise_for_status()
        return r

    async def register(self, req: WorkerRegister) -> WorkerRegisterResponse:
        r = await self._post("/api/workers/register", json=req.model_dump())
        return WorkerRegisterResponse.model_validate(r.json())

    async def heartbeat(self, req: WorkerHeartbeat) -> WorkerHeartbeatResponse:
        r = await self._post("/api/workers/heartbeat", json=req.model_dump())
        return WorkerHeartbeatResponse.model_validate(r.json())

    async def lease(self, req: LeaseRequest) -> LeaseResponse:
        r = await self._post("/api/workers/lease", json=req.model_dump())
        return LeaseResponse.model_validate(r.json())

    async def report_upload(
        self,
        granule_id: str,
        worker_id: str,
        objects: list[UploadedObject],
        upload_started_at: datetime | None = None,
    ) -> None:
        req = UploadReport(
            granule_id=granule_id,
            worker_id=worker_id,
            objects=objects,
            upload_started_at=upload_started_at,
        )
        await self._post("/api/workers/upload", json=req.model_dump(mode="json"))

    async def report_failure(self, req: ProcessFailure) -> None:
        await self._post("/api/workers/failure", json=req.model_dump())

    async def report_state(self, granule_id: str, worker_id: str, state: GranuleState) -> None:
        req = StateUpdate(granule_id=granule_id, worker_id=worker_id, state=state)
        await self._post("/api/workers/state", json=req.model_dump(mode="json"))

    async def get_deletable(self, worker_id: str) -> list[DeletableGranule]:
        r = await self._get(f"/api/workers/deletable/{worker_id}")
        return [DeletableGranule.model_validate(x) for x in r.json()]

    async def confirm_deleted(self, granule: DeletableGranule) -> None:
        await self._post("/api/workers/delete-confirmed", json=granule.model_dump())

    async def report_progress(self, granule_id: str, event: ProgressEvent) -> None:
        await self._post(
            f"/api/granules/{granule_id}/progress",
            json=event.model_dump(mode="json", exclude_none=True),
        )
