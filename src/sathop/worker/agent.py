"""Async HTTP client for the worker → orchestrator API. Thin wrapper over
`sathop.shared.orch_client.OrchClient`; each method just serialises a DTO,
hits the matching endpoint, and parses the response back into a model.

The shared base raises `AuthTokenInvalid` on HTTP 401; `agent_lifecycle.run_agent()`
turns that into a clean process exit (no `os._exit`, finally blocks run, httpx
client closes)."""

from __future__ import annotations

from datetime import datetime

from sathop.shared.orch_client import OrchClient
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


class OrchestratorClient(OrchClient):
    async def register(self, req: WorkerRegister) -> WorkerRegisterResponse:
        r = await self.post("/api/workers/register", json=req.model_dump())
        return WorkerRegisterResponse.model_validate(r.json())

    async def heartbeat(self, req: WorkerHeartbeat) -> WorkerHeartbeatResponse:
        r = await self.post("/api/workers/heartbeat", json=req.model_dump())
        return WorkerHeartbeatResponse.model_validate(r.json())

    async def lease(self, req: LeaseRequest) -> LeaseResponse:
        r = await self.post("/api/workers/lease", json=req.model_dump())
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
        await self.post("/api/workers/upload", json=req.model_dump(mode="json"))

    async def report_failure(self, req: ProcessFailure) -> None:
        await self.post("/api/workers/failure", json=req.model_dump())

    async def report_state(self, granule_id: str, worker_id: str, state: GranuleState) -> None:
        req = StateUpdate(granule_id=granule_id, worker_id=worker_id, state=state)
        await self.post("/api/workers/state", json=req.model_dump(mode="json"))

    async def get_deletable(self, worker_id: str) -> list[DeletableGranule]:
        r = await self.get(f"/api/workers/deletable/{worker_id}")
        return [DeletableGranule.model_validate(x) for x in r.json()]

    async def confirm_deleted(self, granule: DeletableGranule) -> None:
        await self.post("/api/workers/delete-confirmed", json=granule.model_dump())

    async def report_progress(self, granule_id: str, event: ProgressEvent) -> None:
        await self.post(
            f"/api/granules/{granule_id}/progress",
            json=event.model_dump(mode="json", exclude_none=True),
        )
