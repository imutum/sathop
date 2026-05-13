from __future__ import annotations

from sathop.shared.orch_client import OrchClient
from sathop.shared.protocol import (
    AckReport,
    PullRequest,
    PullResponse,
    ReceiverHeartbeat,
    ReceiverHeartbeatResponse,
    ReceiverRegister,
)


class OrchestratorClient(OrchClient):
    async def register(self, req: ReceiverRegister) -> None:
        await self.post("/api/receivers/register", json=req.model_dump())

    async def heartbeat(self, req: ReceiverHeartbeat) -> ReceiverHeartbeatResponse:
        return await self.post_typed("/api/receivers/heartbeat", req, ReceiverHeartbeatResponse)

    async def pull(self, req: PullRequest) -> PullResponse:
        return await self.post_typed("/api/receivers/pull", req, PullResponse)

    async def ack(self, req: AckReport) -> None:
        await self.post("/api/receivers/ack", json=req.model_dump())
