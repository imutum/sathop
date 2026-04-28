"""Async HTTP client for orchestrator API."""

from __future__ import annotations

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


class OrchestratorClient:
    def __init__(self, base_url: str, token: str, timeout: float = 30.0) -> None:
        self._client = make_orch_client(base_url, token, timeout)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def register(self, req: WorkerRegister) -> WorkerRegisterResponse:
        r = await self._client.post("/api/workers/register", json=req.model_dump())
        r.raise_for_status()
        return WorkerRegisterResponse.model_validate(r.json())

    async def heartbeat(self, req: WorkerHeartbeat) -> WorkerHeartbeatResponse:
        r = await self._client.post("/api/workers/heartbeat", json=req.model_dump())
        r.raise_for_status()
        return WorkerHeartbeatResponse.model_validate(r.json())

    async def lease(self, req: LeaseRequest) -> LeaseResponse:
        r = await self._client.post("/api/workers/lease", json=req.model_dump())
        r.raise_for_status()
        return LeaseResponse.model_validate(r.json())

    async def report_upload(self, granule_id: str, worker_id: str, objects: list[UploadedObject]) -> None:
        req = UploadReport(granule_id=granule_id, worker_id=worker_id, objects=objects)
        r = await self._client.post("/api/workers/upload", json=req.model_dump())
        r.raise_for_status()

    async def report_failure(self, req: ProcessFailure) -> None:
        r = await self._client.post("/api/workers/failure", json=req.model_dump())
        r.raise_for_status()

    async def report_state(self, granule_id: str, worker_id: str, state: GranuleState) -> None:
        req = StateUpdate(granule_id=granule_id, worker_id=worker_id, state=state)
        r = await self._client.post("/api/workers/state", json=req.model_dump(mode="json"))
        r.raise_for_status()

    async def get_deletable(self, worker_id: str) -> list[DeletableGranule]:
        r = await self._client.get(f"/api/workers/deletable/{worker_id}")
        r.raise_for_status()
        return [DeletableGranule.model_validate(x) for x in r.json()]

    async def confirm_deleted(self, granule: DeletableGranule) -> None:
        r = await self._client.post("/api/workers/delete-confirmed", json=granule.model_dump())
        r.raise_for_status()

    async def report_progress(self, granule_id: str, event: ProgressEvent) -> None:
        r = await self._client.post(
            f"/api/granules/{granule_id}/progress",
            json=event.model_dump(mode="json", exclude_none=True),
        )
        r.raise_for_status()
