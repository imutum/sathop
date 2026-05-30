"""Async HTTP client for the worker → orchestrator API. Thin wrapper over
`sathop.shared.orch_client.OrchClient`; each method just serialises a DTO,
hits the matching endpoint, and parses the response back into a model.

The shared base raises `AuthTokenInvalid` on HTTP 401; `agent_lifecycle.run_agent()`
turns that into a clean process exit (no `os._exit`, finally blocks run, httpx
client closes)."""

from __future__ import annotations

from sathop.shared.orch_client import OrchClient
from sathop.shared.protocol import (
    DeletableGranule,
    LeaseRequest,
    LeaseResponse,
    ProgressEvent,
    WorkerEventBatch,
    WorkerEventBatchResponse,
    WorkerHeartbeat,
    WorkerHeartbeatResponse,
    WorkerRegister,
    WorkerRegisterResponse,
)


class OrchestratorClient(OrchClient):
    async def register(self, req: WorkerRegister) -> WorkerRegisterResponse:
        return await self.post_typed("/api/workers/register", req, WorkerRegisterResponse)

    async def heartbeat(self, req: WorkerHeartbeat) -> WorkerHeartbeatResponse:
        return await self.post_typed("/api/workers/heartbeat", req, WorkerHeartbeatResponse)

    async def lease(self, req: LeaseRequest) -> LeaseResponse:
        return await self.post_typed("/api/workers/lease", req, LeaseResponse)

    async def emit_events_batch(self, batch: WorkerEventBatch) -> WorkerEventBatchResponse:
        # The worker's only emit path: buffered transitions in one request.
        # mode="json" because event payloads carry datetimes (can't use post_typed).
        r = await self.post("/api/workers/events/batch", json=batch.model_dump(mode="json"))
        return WorkerEventBatchResponse.model_validate(r.json())

    async def get_deletable(self, worker_id: str) -> list[DeletableGranule]:
        r = await self.get(f"/api/workers/deletable/{worker_id}")
        return [DeletableGranule.model_validate(x) for x in r.json()]

    async def report_progress(self, granule_id: str, event: ProgressEvent) -> None:
        await self.post(
            f"/api/granules/{granule_id}/progress",
            json=event.model_dump(mode="json", exclude_none=True),
        )
