"""Granule reaping: hard-delete a Granule and every row that references it.

`reap_granules` is the single owner of the granule-children set and the
child-before-parent delete order. The batch-delete handler and the retention
sweeper both call it instead of hand-listing tables, so adding a new
granule-child table means editing one place — not hunting down every cascade.

Stays a pure DB cascade: caller keeps transaction control (this never commits)
and owns any in-memory eviction (event_store, progress) and SSE publish. That
line is the same one ADR-0002/0003 draw — side-channel artefacts are the
handler's concern — and it keeps the reaper testable on an in-memory session
with no pubsub/event_store wiring.
"""

from __future__ import annotations

from collections.abc import Collection

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from .db import Granule, GranuleObject, GranuleStageTiming

# Children before parent. The reaper exists so this tuple is the *only* place
# the granule-child topology is spelled out.
_CHILD_TABLES = ((GranuleObject, "objects"), (GranuleStageTiming, "stage_timings"))


async def reap_granules(s: AsyncSession, granule_ids: Collection[str]) -> dict[str, int]:
    """Delete the given granules and all rows referencing them, children first.

    Returns per-table rowcounts ({"objects", "stage_timings", "granules"}).
    Empty input is a no-op that issues no queries. Does not commit."""
    counts = {key: 0 for _, key in _CHILD_TABLES}
    counts["granules"] = 0
    ids = list(granule_ids)
    if not ids:
        return counts
    for table, key in _CHILD_TABLES:
        r = await s.execute(delete(table).where(table.granule_id.in_(ids)))
        counts[key] = getattr(r, "rowcount", 0) or 0
    r = await s.execute(delete(Granule).where(Granule.granule_id.in_(ids)))
    counts["granules"] = getattr(r, "rowcount", 0) or 0
    return counts
