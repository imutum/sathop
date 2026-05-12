"""Shared config helpers for worker / receiver / CLI."""

from __future__ import annotations

import argparse
import os
import sys
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
        raise ValueError(f"SATHOP_URL must use sathop:// or sathops:// scheme, got: {url!r}")
    token = unquote(p.password or p.username or "")
    if not token:
        raise ValueError(f"SATHOP_URL missing token (expected sathop://TOKEN@host:port): {url!r}")
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
    orch_url = os.getenv("SATHOP_ORCH_URL", "").strip()
    if not orch_url:
        raise RuntimeError(
            "missing orchestrator URL: set SATHOP_URL (sathop://TOKEN@host:port) "
            "or SATHOP_ORCH_URL + SATHOP_TOKEN"
        )
    token = os.getenv("SATHOP_TOKEN", "")
    if not token:
        raise RuntimeError("missing SATHOP_TOKEN (or use SATHOP_URL=sathop://TOKEN@host:port)")
    return orch_url.rstrip("/"), token


def cli_resolve_orch(url: str, orch_url: str, token: str, *, require_token: bool = True) -> tuple[str, str]:
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


def add_orch_args(parser: argparse.ArgumentParser, *, default_orch_url: str = "") -> None:
    """Register the standard `--url` / `--orch-url` / `--token` triplet on a CLI
    parser. Defaults read from `SATHOP_URL` / `SATHOP_ORCH_URL` / `SATHOP_TOKEN`."""
    parser.add_argument(
        "--url",
        default=os.getenv("SATHOP_URL", ""),
        help="sathop://TOKEN@host:port — overrides --orch-url/--token (reads SATHOP_URL env)",
    )
    parser.add_argument(
        "--orch-url",
        default=os.getenv("SATHOP_ORCH_URL", default_orch_url),
        help="env SATHOP_ORCH_URL",
    )
    parser.add_argument(
        "--token",
        default=os.getenv("SATHOP_TOKEN", ""),
        help="env SATHOP_TOKEN",
    )


def resolve_orch_or_exit(args: argparse.Namespace, *, require_token: bool = True) -> tuple[str, str]:
    """Resolve (orch_url, token) from parsed args; on ValueError, `sys.exit` with
    a stderr error line. Combines with `add_orch_args` to collapse the standard
    CLI boilerplate to two calls."""
    try:
        return cli_resolve_orch(args.url, args.orch_url, args.token, require_token=require_token)
    except ValueError as e:
        sys.exit(f"error: {e}")
