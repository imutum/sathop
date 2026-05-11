from __future__ import annotations

from sathop.shared.http import make_orch_client
from sathop.shared.protocol import (
    AckReport,
    PullRequest,
    PullResponse,
    ReceiverHeartbeat,
    ReceiverHeartbeatResponse,
    ReceiverRegister,
)


class OrchestratorClient:
    def __init__(self, base_url: str, token: str, timeout: float = 30.0) -> None:
        self._client = make_orch_client(base_url, token, timeout)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def register(self, req: ReceiverRegister) -> None:
        (await self._client.post("/api/receivers/register", json=req.model_dump())).raise_for_status()

    async def heartbeat(self, req: ReceiverHeartbeat) -> ReceiverHeartbeatResponse:
        r = await self._client.post("/api/receivers/heartbeat", json=req.model_dump())
        r.raise_for_status()
        return ReceiverHeartbeatResponse.model_validate(r.json())

    async def pull(self, req: PullRequest) -> PullResponse:
        r = await self._client.post("/api/receivers/pull", json=req.model_dump())
        r.raise_for_status()
        return PullResponse.model_validate(r.json())

    async def ack(self, req: AckReport) -> None:
        (await self._client.post("/api/receivers/ack", json=req.model_dump())).raise_for_status()
