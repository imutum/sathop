from __future__ import annotations

from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession

from ..pubsub import log_event as log


async def consume_one_shot_signal(
    s: AsyncSession,
    requested: bool,
    clear: Callable[[], None],
    *,
    source: str,
    message: str,
) -> bool:
    if not requested:
        return False
    clear()
    await log(s, source, message)
    return True
