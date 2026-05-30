"""Isolated orch-CPU micro-benchmark for the events ingress: per-event vs batch.

Floods ONLY one transition (download_started: QUEUED→DOWNLOADING) with no
receiver/progress/lease noise, so an external CPU sample of the orch process is
fully attributable to the events path. Seeds N granules QUEUED+leased, then fires
all N transitions at fixed concurrency and reports transitions/sec + wall.

  # phase 1 (per-event):
  python scripts/bench_events.py --pg <url> --orch <url> --reset --mode per-event
  # phase 2 (batch) — reset state first:
  python scripts/bench_events.py --pg <url> --orch <url> --reset --mode batch --batch-size 50

Bracket each invocation with a CPU snapshot of the orch PID to get core-seconds.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

BATCH_ID = "bench"
N_WORKERS = 16


async def reset(pg_url: str, n: int) -> None:
    from datetime import timedelta

    from sqlalchemy import delete, select, text
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

    from sathop.orchestrator.db import (
        Base,
        Batch,
        Granule,
        GranuleObject,
        GranuleStageTiming,
        Worker,
        utcnow,
    )
    from sathop.shared.protocol import GranuleState

    eng = create_async_engine(pg_url)
    try:
        async with eng.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with AsyncSession(eng) as s:
            # Children before parents — a prior flood leaves stage-timing rows.
            gids = select(Granule.granule_id).where(Granule.batch_id == BATCH_ID)
            await s.execute(delete(GranuleStageTiming).where(GranuleStageTiming.batch_id == BATCH_ID))
            await s.execute(delete(GranuleObject).where(GranuleObject.granule_id.in_(gids)))
            await s.execute(delete(Granule).where(Granule.batch_id == BATCH_ID))
            if await s.get(Batch, BATCH_ID) is None:
                s.add(Batch(batch_id=BATCH_ID, name="bench", bundle_ref="bench:fake"))
            for i in range(N_WORKERS):
                if await s.get(Worker, f"bw{i}") is None:
                    s.add(Worker(worker_id=f"bw{i}", version="t", capacity=64))
            await s.flush()
            exp = utcnow() + timedelta(hours=1)
            for base in range(0, n, 1000):
                s.add_all(
                    Granule(
                        granule_id=f"{BATCH_ID}:g{i}",
                        batch_id=BATCH_ID,
                        state=GranuleState.QUEUED.value,
                        inputs=[],
                        leased_by=f"bw{i % N_WORKERS}",
                        lease_expires_at=exp,
                    )
                    for i in range(base, min(base + 1000, n))
                )
                await s.flush()
            await s.commit()
        # ANALYZE so the planner has fresh stats for the flood.
        async with eng.begin() as conn:
            await conn.execute(text("ANALYZE granules"))
    finally:
        await eng.dispose()


def _event(i: int) -> dict:
    return {"kind": "download_started", "granule_id": f"{BATCH_ID}:g{i}", "worker_id": f"bw{i % N_WORKERS}"}


async def run(a: argparse.Namespace) -> None:
    headers = {"Authorization": f"Bearer {a.token}"} if a.token else {}
    limits = httpx.Limits(max_connections=a.concurrency + 4, max_keepalive_connections=a.concurrency + 4)
    sem = asyncio.Semaphore(a.concurrency)
    errors = 0

    if a.mode == "per-event":
        payloads = [("/api/workers/events", _event(i)) for i in range(a.granules)]
    else:
        payloads = []
        for base in range(0, a.granules, a.batch_size):
            events = [_event(i) for i in range(base, min(base + a.batch_size, a.granules))]
            payloads.append(("/api/workers/events/batch", {"events": events}))

    async with httpx.AsyncClient(base_url=a.orch, headers=headers, timeout=60.0, limits=limits) as c:

        async def fire(path: str, body: dict) -> None:
            nonlocal errors
            async with sem:
                try:
                    r = await c.post(path, json=body)
                    if r.status_code != 200:
                        errors += 1
                except Exception:
                    errors += 1

        proc = None
        cpu0 = 0.0
        if a.orch_pid:
            import psutil

            proc = psutil.Process(a.orch_pid)
            t = proc.cpu_times()
            cpu0 = t.user + t.system

        t0 = time.monotonic()
        await asyncio.gather(*(fire(p, b) for p, b in payloads))
        wall = time.monotonic() - t0

        cpu = 0.0
        if proc is not None:
            t = proc.cpu_times()
            cpu = (t.user + t.system) - cpu0

    reqs = len(payloads)
    bs = a.batch_size if a.mode == "batch" else 1
    cpu_str = (
        f"  orch_cpu={cpu:.2f}s ({cpu / wall:.2f} cores)  us/transition={cpu / a.granules * 1e6:,.0f}"
        if a.orch_pid
        else ""
    )
    print(
        f"mode={a.mode:9s} batch={bs:3d} requests={reqs:6d} "
        f"wall={wall:6.2f}s  transitions/sec={a.granules / wall:7,.0f}  errors={errors}{cpu_str}",
        flush=True,
    )


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pg", required=True)
    ap.add_argument("--orch", required=True)
    ap.add_argument("--token", default="")
    ap.add_argument("--granules", type=int, default=20000)
    ap.add_argument("--concurrency", type=int, default=64)
    ap.add_argument("--mode", choices=["per-event", "batch"], default="per-event")
    ap.add_argument("--batch-size", type=int, default=50)
    ap.add_argument("--reset", action="store_true", help="re-seed all granules to QUEUED first")
    ap.add_argument("--orch-pid", type=int, default=0, help="sample this orch PID's CPU over the flood")
    a = ap.parse_args()

    if a.reset:
        print(f"seeding {a.granules} granules QUEUED …", flush=True)
        await reset(a.pg, a.granules)
    await run(a)


if __name__ == "__main__":
    asyncio.run(main())
