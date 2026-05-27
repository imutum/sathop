from __future__ import annotations

from typing import Any, TypeVar

import httpx
from pydantic import BaseModel

from sathop.shared.http import make_orch_client

T = TypeVar("T", bound=BaseModel)


class AuthTokenInvalid(BaseException):
    """Orchestrator rejected the bearer token with HTTP 401. Inherits from
    BaseException — like CancelledError — so the typical `except Exception`
    in heartbeat / lease loops doesn't accidentally swallow it. `run_agent()`
    logs fatally and propagates `SystemExit` instead of retrying with a
    known-bad token.
    """


class VersionTooOld(BaseException):
    """Orchestrator rejected agent with HTTP 426 (Upgrade Required).
    Same BaseException pattern as AuthTokenInvalid — `run_agent()` logs the
    upgrade instructions and exits."""


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

    async def post_typed(self, path: str, req: BaseModel, resp_cls: type[T]) -> T:
        """POST a Pydantic request, parse the response into `resp_cls`. The
        typed-RPC shape every wire-symmetric endpoint follows — collapses the
        `model_dump` + `model_validate(r.json())` boilerplate at every call site.
        Use `post()` directly only when the request needs non-default dump
        options (e.g. `mode="json"`, `exclude_none=True`) or no response parsing."""
        r = await self.post(path, json=req.model_dump())
        return resp_cls.model_validate(r.json())

    @staticmethod
    def _check(r: httpx.Response, path: str) -> None:
        if r.status_code == 401:
            raise AuthTokenInvalid(f"orch {path} returned 401 — SATHOP_TOKEN mismatch")
        if r.status_code == 426:
            detail = r.json().get("detail", "") if r.headers.get("content-type", "").startswith("application/json") else r.text
            raise VersionTooOld(detail)
        r.raise_for_status()
