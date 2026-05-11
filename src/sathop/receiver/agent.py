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
        r = await self.post("/api/receivers/heartbeat", json=req.model_dump())
        return ReceiverHeartbeatResponse.model_validate(r.json())

    async def pull(self, req: PullRequest) -> PullResponse:
        r = await self.post("/api/receivers/pull", json=req.model_dump())
        return PullResponse.model_validate(r.json())

    async def ack(self, req: AckReport) -> None:
        await self.post("/api/receivers/ack", json=req.model_dump())
