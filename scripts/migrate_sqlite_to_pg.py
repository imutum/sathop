"""One-shot SQLite → Postgres state migration for the orchestrator.

Usage:
  python scripts/migrate_sqlite_to_pg.py ./data/orchestrator.db \\
      postgresql+asyncpg://sathop:PASS@host:5432/sathop

Copies all authoritative state — workers, receivers, bundles, shared files,
batches, granules, objects, stage timings — from a single-process SQLite DB into
a FRESH Postgres DB, preserving primary keys (so in-flight object acks keep
working) and resetting identity sequences afterward. The event feed is NOT
migrated: it's ephemeral display-only data (in-memory in SQLite mode), so the PG
feed just starts empty. Run once, with the orchestrator stopped, before the
first multi-process boot. Refuses to run if the target already has granules.

Uses the project's own model definitions (declared column types), so JSON and
UTC-datetime columns round-trip correctly, and only columns present in the
source are copied (an older DB missing a later-added column → PG default).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from sqlalchemy import Integer, func, inspect, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sathop.orchestrator.db import (  # noqa: E402
    Base,
    Batch,
    Bundle,
    Granule,
    GranuleObject,
    GranuleStageTiming,
    Receiver,
    SharedFile,
    Worker,
)

# FK-safe insertion order: parents before children.
ORDER = [Worker, Receiver, Bundle, SharedFile, Batch, Granule, GranuleObject, GranuleStageTiming]


def _normalize_pg(url: str) -> str:
    if url.startswith("postgresql+asyncpg://"):
        return url
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    raise SystemExit(f"target must be a postgres URL, got: {url!r}")


async def _copy_table(src: AsyncSession, dst: AsyncSession, model) -> int:
    table = model.__table__
    # Select only columns that exist in the source (an older DB may lack a column
    # the model later added → PG fills its default). Use the declared column
    # objects so JSON / UtcDateTime type handling is applied on read.
    src_cols = await src.run_sync(
        lambda sc: {c["name"] for c in inspect(sc.connection()).get_columns(table.name)}
    )
    cols = [table.c[k] for k in table.c.keys() if k in src_cols]
    rows = (await src.execute(select(*cols))).mappings().all()
    if not rows:
        return 0
    await dst.execute(table.insert(), [dict(r) for r in rows])
    return len(rows)


async def _reset_sequence(dst: AsyncSession, model) -> None:
    """After inserting explicit integer PKs, advance the SERIAL sequence past
    MAX(id) so future auto-inserts don't collide. No-op for non-integer/composite PKs."""
    table = model.__table__
    pk = list(table.primary_key.columns)
    if len(pk) != 1 or not isinstance(pk[0].type, Integer):
        return
    col = pk[0].name
    await dst.execute(
        text(
            f"SELECT setval(pg_get_serial_sequence('{table.name}', '{col}'), "
            f'COALESCE((SELECT MAX("{col}") FROM "{table.name}"), 1))'
        )
    )


async def main(sqlite_path: str, pg_url: str) -> None:
    src_path = Path(sqlite_path)
    if not src_path.is_file():
        raise SystemExit(f"source SQLite DB not found: {src_path}")
    src_engine = create_async_engine(f"sqlite+aiosqlite:///{src_path.as_posix()}")
    dst_engine = create_async_engine(_normalize_pg(pg_url))
    try:
        async with dst_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with AsyncSession(src_engine) as src, AsyncSession(dst_engine) as dst:
            existing = await dst.scalar(select(func.count()).select_from(Granule.__table__))
            if existing:
                raise SystemExit(
                    f"target already has {existing} granules — refusing to migrate into a "
                    "non-empty DB (drop/recreate it to re-run)"
                )
            total: dict[str, int] = {}
            for model in ORDER:
                total[model.__tablename__] = await _copy_table(src, dst, model)
            await dst.commit()
            for model in ORDER:
                await _reset_sequence(dst, model)
            await dst.commit()
        print("migrated rows:", flush=True)
        for name, n in total.items():
            print(f"  {name:24} {n}", flush=True)
        print("done. event feed starts empty (ephemeral, not migrated).", flush=True)
    finally:
        await src_engine.dispose()
        await dst_engine.dispose()


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: migrate_sqlite_to_pg.py <sqlite_path> <postgres_url>")
    asyncio.run(main(sys.argv[1], sys.argv[2]))
