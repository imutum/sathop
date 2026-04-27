"""Receiver agent: polls orchestrator, pulls from worker presigned URLs."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

import httpx

from sathop.shared.config import resolve_orch
from sathop.shared.http import make_orch_client
from sathop.shared.protocol import (
    AckReport,
    PullRequest,
    PullResponse,
    ReceiverHeartbeat,
    ReceiverRegister,
)


class OrchestratorClient:
    def __init__(self, base_url: str, token: str, timeout: float = 30.0) -> None:
        self._client = make_orch_client(base_url, token, timeout)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def register(self, req: ReceiverRegister) -> None:
        (await self._client.post("/api/receivers/register", json=req.model_dump())).raise_for_status()

    async def heartbeat(self, req: ReceiverHeartbeat) -> None:
        (await self._client.post("/api/receivers/heartbeat", json=req.model_dump())).raise_for_status()

    async def pull(self, req: PullRequest) -> PullResponse:
        r = await self._client.post("/api/receivers/pull", json=req.model_dump())
        r.raise_for_status()
        return PullResponse.model_validate(r.json())

    async def ack(self, req: AckReport) -> None:
        (await self._client.post("/api/receivers/ack", json=req.model_dump())).raise_for_status()


log = logging.getLogger("sathop.receiver")

_CHUNK = 256 * 1024


@dataclass(frozen=True)
class Settings:
    receiver_id: str
    orchestrator_url: str
    token: str
    storage_dir: Path
    poll_interval: int
    concurrent_pulls: int
    platform: Literal["linux", "windows"]


def load() -> Settings:
    orchestrator_url, token = resolve_orch()
    return Settings(
        receiver_id=os.environ["SATHOP_RECEIVER_ID"],
        orchestrator_url=orchestrator_url,
        token=token,
        storage_dir=Path(os.environ["SATHOP_STORAGE_DIR"]),
        poll_interval=int(os.getenv("SATHOP_POLL_INTERVAL", "10")),
        concurrent_pulls=int(os.getenv("SATHOP_CONCURRENT_PULLS", "4")),
        platform=cast(Literal["linux", "windows"], "windows" if sys.platform == "win32" else "linux"),
    )


async def _pull_http(url: str, dest: Path) -> tuple[str, int]:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    h = hashlib.sha256()
    size = 0
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, read=600.0), follow_redirects=True) as c:
        async with c.stream("GET", url) as r:
            r.raise_for_status()
            with tmp.open("wb") as f:
                async for chunk in r.aiter_bytes(_CHUNK):
                    f.write(chunk)
                    h.update(chunk)
                    size += len(chunk)
    tmp.replace(dest)
    return h.hexdigest(), size


class Receiver:
    def __init__(self, s: Settings) -> None:
        self.s = s
        self.client = OrchestratorClient(s.orchestrator_url, s.token)
        s.storage_dir.mkdir(parents=True, exist_ok=True)

    async def run(self) -> None:
        await self.client.register(
            ReceiverRegister(
                receiver_id=self.s.receiver_id,
                version="0.1.0",
                platform=self.s.platform,
            )
        )
        log.info("registered as %s (%s)", self.s.receiver_id, self.s.platform)

        async with asyncio.TaskGroup() as tg:
            tg.create_task(self._heartbeat_loop())
            tg.create_task(self._pull_loop())

    async def _heartbeat_loop(self) -> None:
        while True:
            try:
                free = shutil.disk_usage(str(self.s.storage_dir)).free / 1024**3
                await self.client.heartbeat(
                    ReceiverHeartbeat(
                        receiver_id=self.s.receiver_id,
                        disk_free_gb=free,
                    )
                )
            except Exception as e:
                log.warning("heartbeat failed: %s", e)
            await asyncio.sleep(self.s.poll_interval)

    async def _pull_loop(self) -> None:
        sem = asyncio.Semaphore(self.s.concurrent_pulls)
        while True:
            try:
                resp = await self.client.pull(
                    PullRequest(
                        receiver_id=self.s.receiver_id,
                        limit=self.s.concurrent_pulls * 4,
                    )
                )
            except Exception as e:
                log.warning("pull list failed: %s", e)
                await asyncio.sleep(self.s.poll_interval)
                continue

            if not resp.items:
                await asyncio.sleep(self.s.poll_interval)
                continue

            await asyncio.gather(*(self._fetch_one(sem, it) for it in resp.items))

    async def _fetch_one(self, sem: asyncio.Semaphore, item) -> None:
        async with sem:
            dest = self.s.storage_dir / item.object_key
            try:
                sha, size = await _pull_http(item.presigned_url, dest)
                ok = sha == item.sha256 and size == item.size
                if not ok:
                    dest.unlink(missing_ok=True)
                await self.client.ack(
                    AckReport(
                        receiver_id=self.s.receiver_id,
                        object_id=item.object_id,
                        sha256=sha,
                        success=ok,
                        error=None if ok else f"sha/size mismatch {sha}/{size} vs {item.sha256}/{item.size}",
                    )
                )
                if ok:
                    log.info("pulled %s (%d bytes)", item.object_key, size)
                else:
                    log.error("verify failed %s", item.object_key)
            except Exception as e:
                log.warning("pull %s failed: %s", item.object_key, e)
                try:
                    await self.client.ack(
                        AckReport(
                            receiver_id=self.s.receiver_id,
                            object_id=item.object_id,
                            sha256="",
                            success=False,
                            error=str(e),
                        )
                    )
                except Exception:
                    pass


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    r = Receiver(load())
    try:
        await r.run()
    finally:
        await r.client.aclose()


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
