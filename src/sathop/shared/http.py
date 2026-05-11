from __future__ import annotations

import httpx


def bearer_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def make_orch_client(orch_url: str, token: str, timeout: float = 30.0) -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=orch_url, timeout=timeout, headers=bearer_headers(token))


def make_sync_orch_client(orch_url: str, token: str, timeout: float = 30.0) -> httpx.Client:
    """Sync counterpart to `make_orch_client` for thread-bound code paths
    (bundle fetch, shared-file sync) called via `asyncio.to_thread`."""
    return httpx.Client(base_url=orch_url, timeout=timeout, headers=bearer_headers(token))
