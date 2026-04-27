"""Shared HTTP helpers for SatHop components."""

from __future__ import annotations

import httpx


def bearer_headers(token: str) -> dict[str, str]:
    """Standard Authorization header for SatHop bearer-token auth."""
    return {"Authorization": f"Bearer {token}"}


def make_orch_client(orch_url: str, token: str, timeout: float = 30.0) -> httpx.AsyncClient:
    """Async httpx client preconfigured for orchestrator API calls."""
    return httpx.AsyncClient(base_url=orch_url, timeout=timeout, headers=bearer_headers(token))
