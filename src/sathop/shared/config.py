"""Shared config helpers for worker / receiver / CLI."""

from __future__ import annotations

import os
from urllib.parse import unquote, urlparse


def parse_sathop_url(url: str) -> tuple[str, str]:
    """Parse a sathop://TOKEN@host:port[/path] connection string.

    sathop://  → http transport,  sathops:// → https transport.
    Token may sit in either userinfo slot (sathop://TOKEN@host or sathop://:TOKEN@host).
    Returns (orch_url, token).
    """
    p = urlparse(url)
    if p.scheme == "sathop":
        transport = "http"
    elif p.scheme == "sathops":
        transport = "https"
    else:
        raise ValueError(
            f"SATHOP_URL must use sathop:// or sathops:// scheme, got: {url!r}"
        )
    token = unquote(p.password or p.username or "")
    if not token:
        raise ValueError(
            f"SATHOP_URL missing token (expected sathop://TOKEN@host:port): {url!r}"
        )
    if not p.hostname:
        raise ValueError(f"SATHOP_URL missing host: {url!r}")
    netloc = p.hostname + (f":{p.port}" if p.port else "")
    return f"{transport}://{netloc}{p.path.rstrip('/')}", token


def resolve_orch() -> tuple[str, str]:
    """Read orchestrator URL + token from env.

    SATHOP_URL (sathop://TOKEN@host:port) takes precedence.
    Falls back to SATHOP_ORCH_URL + SATHOP_TOKEN when SATHOP_URL is unset.
    """
    url = os.getenv("SATHOP_URL", "").strip()
    if url:
        return parse_sathop_url(url)
    return os.environ["SATHOP_ORCH_URL"].rstrip("/"), os.environ["SATHOP_TOKEN"]


def cli_resolve_orch(
    url: str, orch_url: str, token: str, *, require_token: bool = True
) -> tuple[str, str]:
    """Resolve (orch_url, token) from CLI args. --url overrides --orch-url + --token.

    Each arg may be empty (unset env, empty default). Pass require_token=False to
    permit anonymous access when --orch-url is set without a token.
    """
    if url:
        return parse_sathop_url(url)
    if not orch_url:
        raise ValueError(
            "missing orchestrator: pass --url sathop://TOKEN@host:port or --orch-url "
            "(env SATHOP_URL / SATHOP_ORCH_URL also accepted)"
        )
    if require_token and not token:
        raise ValueError(
            "missing token: pass --token or set SATHOP_TOKEN (or use --url sathop://TOKEN@host:port)"
        )
    return orch_url.rstrip("/"), token
