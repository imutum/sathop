from __future__ import annotations

from typing import Any

import httpx

from sathop.shared.http import make_orch_client


class AuthTokenInvalid(BaseException):
    """Orchestrator rejected the bearer token with HTTP 401. Inherits from
    BaseException — like CancelledError — so the typical `except Exception`
    in heartbeat / lease loops doesn't accidentally swallow it. `run_agent()`
    logs fatally and propagates `SystemExit` instead of retrying with a
    known-bad token.
    """


class OrchClient:
    """Bearer-authed httpx wrapper for orchestrator endpoints. Every call
    raises AuthTokenInvalid on 401 and raise_for_status on other non-2xx;
    subclasses parse the 2xx body."""

    def __init__(self, base_url: str, token: str, timeout: float = 30.0) -> None:
        self._client = make_orch_client(base_url, token, timeout)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def post(self, path: str, json: Any | None = None) -> httpx.Response:
        r = await self._client.post(path, json=json)
        self._check(r, path)
        return r

    async def get(self, path: str) -> httpx.Response:
        r = await self._client.get(path)
        self._check(r, path)
        return r

    @staticmethod
    def _check(r: httpx.Response, path: str) -> None:
        if r.status_code == 401:
            raise AuthTokenInvalid(f"orch {path} returned 401 — SATHOP_TOKEN mismatch")
        r.raise_for_status()
