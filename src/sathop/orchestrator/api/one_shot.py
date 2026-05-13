"""Heartbeat-side helpers: one-shot signal request/consume pair + version flap detection.

The one-shot signal pattern is producer/consumer: an operator endpoint sets
`entity.<attr>` to a timestamp (the request), the next heartbeat clears it
and logs the delivery (the consume). Both sides are attr-based and uniform
across Worker / Receiver — adding a new flag or a new agent kind doesn't
grow sibling boilerplate.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from sathop.shared.state_machine import Scope

from ..db import Receiver, Worker, utcnow
from ..pubsub import commit_and_publish
from ..pubsub import log_event as log

# Versioned heartbeat agents. Explicit union (not a Protocol) because
# SQLAlchemy's `Mapped[str]` descriptor doesn't satisfy a `version: str`
# Protocol under pyright's invariance rules — and the two concrete agents
# are the only callers anyway, so naming them is accurate, not constraining.
_VersionedAgent = Worker | Receiver


async def request_one_shot_signal(
    s: AsyncSession,
    entity: object,
    attr: str,
    *,
    source: str,
    message: str,
    scope: Scope,
) -> None:
    """Producer side. Stamp `entity.<attr>` with utcnow(), log the request,
    commit + publish the scope. The next heartbeat consumes the stamp via
    `consume_one_shot_signal`. Idempotent — re-stamps just refresh the
    timestamp; one stamp delivers exactly once."""
    setattr(entity, attr, utcnow())
    await log(s, source, message)
    await commit_and_publish(s, scope)


async def consume_one_shot_signal(
    s: AsyncSession,
    entity: object,
    attr: str,
    *,
    source: str,
    message: str,
) -> bool:
    """Consumer side. Clear `entity.<attr>` if set and log; return True iff
    the flag fired. Same shape works across Worker.restart_requested_at /
    gc_requested_at / Receiver.restart_requested_at."""
    if getattr(entity, attr) is None:
        return False
    setattr(entity, attr, None)
    await log(s, source, message)
    return True


async def record_version_flap(
    s: AsyncSession,
    entity: _VersionedAgent,
    *,
    new_version: str,
    source: str,
    kind: str,
) -> None:
    """Warn-log + update if `new_version` differs from the stored one.

    Empty `new_version` (old client) is treated as no-info — never a flap.
    `kind` is the noun for the log line ("worker" / "receiver"); the orphan-
    container guidance text is the same across agents.
    """
    if not new_version or new_version == entity.version:
        return
    await log(
        s,
        source,
        f"{kind} version changed {entity.version!r} → {new_version!r} "
        f"(if this keeps flipping, two containers likely share the {kind}_id)",
        level="warn",
    )
    entity.version = new_version
