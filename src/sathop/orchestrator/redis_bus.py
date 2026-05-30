"""Optional Redis bus for the multi-process orchestrator (route A).

Single-process is the default: with ``SATHOP_REDIS_URL`` unset, ``enabled()`` is
False and every ephemeral subsystem (pubsub, events, telemetry, progress) keeps
its in-memory backend — nothing here engages. Set the URL (and
``SATHOP_ORCH_WORKERS`` > 1) to run N uvicorn worker processes sharing one Redis
instance as the cross-process substrate for: SSE pub/sub fan-out, the events
feed, worker/receiver telemetry, granule progress, and a leader lock that keeps
the background sweepers running in exactly one process.

Two clients on purpose:
  - a **sync** client for the simple KV/list ops on the request hot path
    (events append, telemetry write) — sub-ms on a co-located Redis, so the brief
    event-loop block is negligible, and keeping the ops sync means none of the
    existing sync call sites change.
  - an **async** client for pub/sub, which needs an awaitable listener loop.
"""

from __future__ import annotations

import logging

from .config import settings

log = logging.getLogger("sathop.orch.redis")

_sync = None  # redis.Redis | None — KV/list hot-path ops
_async = None  # redis.asyncio.Redis | None — pub/sub


def enabled() -> bool:
    # Redis is being removed in favour of Postgres-native pubsub/ephemeral
    # (LISTEN/NOTIFY + UNLOGGED tables). Hard-disabled so all stores use their
    # in-memory backend until the PG backends land; this module is deleted then.
    return False


def init() -> None:
    """Open both clients; verify connectivity. Called from lifespan when enabled."""
    global _sync, _async
    if not enabled():
        return
    import redis
    import redis.asyncio as aredis

    # The sync client runs on the request event loop (hot-path KV/list ops), so a
    # stalled Redis must fail fast rather than block the loop indefinitely — the
    # bounded reads keep Redis unsaturated, this timeout is the backstop.
    _sync = redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_timeout=3,
        socket_connect_timeout=3,
    )
    _async = aredis.from_url(settings.redis_url, decode_responses=True)
    _sync.ping()
    log.info("redis bus enabled (workers=%d)", settings.orch_workers)


async def aclose() -> None:
    global _sync, _async
    if _async is not None:
        await _async.aclose()
        _async = None
    if _sync is not None:
        _sync.close()
        _sync = None


def sync():
    """Sync client for hot-path KV/list ops; None when disabled."""
    return _sync


def aclient():
    """Async client for pub/sub; None when disabled."""
    return _async


# ── Leader lock (background sweepers run in one process only) ─────────────────
#
# Renew/release are GET-then-(PEXPIRE/DEL), guarded by an owner check rather than
# a Lua CAS: renewal fires at TTL/3, far from the expiry boundary, so the tiny
# non-atomic window is never actually hit in practice — and avoiding EVAL keeps
# the dependency surface (and test doubles) simpler.


async def acquire_leader(key: str, token: str, ttl_ms: int) -> bool:
    c = _async
    return bool(c is not None and await c.set(key, token, nx=True, px=ttl_ms))


async def renew_leader(key: str, token: str, ttl_ms: int) -> bool:
    c = _async
    if c is None or await c.get(key) != token:
        return False
    return bool(await c.pexpire(key, ttl_ms))


async def release_leader(key: str, token: str) -> None:
    c = _async
    if c is not None and await c.get(key) == token:
        await c.delete(key)
