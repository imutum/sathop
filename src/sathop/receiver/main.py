"""Receiver agent: polls orchestrator, pulls from worker presigned URLs."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import shutil
import sys
import time
from collections import deque
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
_THROUGHPUT_WINDOW_SEC = 60.0


class _PullStats:
    """In-process counters surfaced via heartbeat. `in_flight` is incremented
    for the duration of each `_fetch_one`; bytes from successful pulls land
    in a (ts, bytes) deque and `recent_bps()` returns the current window
    rate so the operator can see pull throughput in the UI."""

    def __init__(self, window_sec: float = _THROUGHPUT_WINDOW_SEC) -> None:
        self.window = window_sec
        self.in_flight = 0
        self._events: deque[tuple[float, int]] = deque()

    def begin(self) -> None:
        self.in_flight += 1

    def end(self, bytes_pulled: int) -> None:
        self.in_flight -= 1
        if bytes_pulled > 0:
            self._events.append((time.monotonic(), bytes_pulled))

    def recent_bps(self) -> int:
        cutoff = time.monotonic() - self.window
        while self._events and self._events[0][0] < cutoff:
            self._events.popleft()
        if not self._events:
            return 0
        return int(sum(b for _, b in self._events) / self.window)


@dataclass(frozen=True)
class Settings:
    receiver_id: str
    orchestrator_url: str
    token: str
    storage_dir: Path
    poll_interval: int
    concurrent_pulls: int
    platform: Literal["linux", "windows"]
    # False ⇒ skip TLS cert verification entirely (insecure escape hatch).
    # True (default) ⇒ verify; if `tls_trust_orch` is also True, fetch the
    # orchestrator's aggregated worker-CA bundle at startup and verify against
    # it (precise trust without skip_verify). If False — system CA bundle only,
    # which fails for self-signed worker certs.
    tls_verify: bool = True
    # When True (and tls_verify True), download the orchestrator-aggregated
    # worker CA bundle at startup → use as httpx verify path. Fallback to system
    # CAs if the orchestrator returns 204 (no workers have uploaded a CA).
    tls_trust_orch: bool = False


def _parse_bool(s: str, default: bool) -> bool:
    return s.strip().lower() not in ("0", "false", "no", "off") if s else default


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
        tls_verify=_parse_bool(os.getenv("SATHOP_TLS_VERIFY", ""), True),
        tls_trust_orch=_parse_bool(os.getenv("SATHOP_TLS_TRUST_ORCH", ""), False),
    )


async def _pull_http(url: str, dest: Path, *, verify: bool | str = True) -> tuple[str, int]:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    h = hashlib.sha256()
    size = 0
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, read=600.0), follow_redirects=True, verify=verify
        ) as c:
            async with c.stream("GET", url) as r:
                r.raise_for_status()
                with tmp.open("wb") as f:
                    async for chunk in r.aiter_bytes(_CHUNK):
                        f.write(chunk)
                        h.update(chunk)
                        size += len(chunk)
        tmp.replace(dest)
    except BaseException:
        # Mid-stream failure (network, cancel, disk full): drop the partial.
        # Otherwise an orphan `<dest>.part` lingers if the orchestrator stops
        # offering this object before the next pull attempt overwrites it.
        tmp.unlink(missing_ok=True)
        raise
    return h.hexdigest(), size


class Receiver:
    def __init__(self, s: Settings) -> None:
        self.s = s
        self.client = OrchestratorClient(s.orchestrator_url, s.token)
        self.stats = _PullStats()
        s.storage_dir.mkdir(parents=True, exist_ok=True)
        # Resolved at run() start: bool (True/False) or path str pointing at an
        # orchestrator-aggregated CA bundle. Passed verbatim to httpx verify=.
        self._verify: bool | str = s.tls_verify

    async def _resolve_trust(self) -> None:
        """Wire up self._verify based on Settings. Called once at startup so the
        download loop carries a stable value (no per-pull HTTPS to the
        orchestrator)."""
        if not self.s.tls_verify:
            log.warning("TLS verification disabled (SATHOP_TLS_VERIFY=false)")
            return
        if not self.s.tls_trust_orch:
            return
        bundle_path = self.s.storage_dir / ".orch-ca-bundle.pem"
        url = f"{self.s.orchestrator_url}/api/receivers/ca-bundle"
        async with httpx.AsyncClient(timeout=15.0, headers={"Authorization": f"Bearer {self.s.token}"}) as c:
            r = await c.get(url)
        if r.status_code == 204:
            log.warning("orchestrator has no worker CAs to trust — falling back to system CAs")
            return
        r.raise_for_status()
        bundle_path.parent.mkdir(parents=True, exist_ok=True)
        bundle_path.write_text(r.text, encoding="utf-8")
        self._verify = str(bundle_path)
        log.info("trusting orchestrator-managed CA bundle at %s", bundle_path)

    async def run(self) -> None:
        await self._resolve_trust()
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
                        queue_pulling=self.stats.in_flight,
                        recent_pull_bps=self.stats.recent_bps(),
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
            self.stats.begin()
            pulled_bytes = 0
            try:
                dest = self.s.storage_dir / item.object_key
                try:
                    sha, size = await _pull_http(item.presigned_url, dest, verify=self._verify)
                    ok = sha == item.sha256 and size == item.size
                    if ok:
                        pulled_bytes = size
                    else:
                        dest.unlink(missing_ok=True)
                    await self.client.ack(
                        AckReport(
                            receiver_id=self.s.receiver_id,
                            object_id=item.object_id,
                            sha256=sha,
                            success=ok,
                            error=None
                            if ok
                            else f"sha/size mismatch {sha}/{size} vs {item.sha256}/{item.size}",
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
            finally:
                self.stats.end(pulled_bytes)


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
