"""Local multi-process Postgres load test for the orchestrator — fake data, no
real downloads. Drives the full pending→delivered pipeline over the documented
HTTP API exactly as real workers/receivers do (lease → 3 state events → pull →
ack → delete_confirmed), while sampling /api/health latency concurrently — the
exact signal that spiked to 10-22s in the Redis regression.

Run an orchestrator against a real Postgres first (single- and multi-process),
then point this at it:

  python scripts/loadtest_orch.py \\
    --pg postgresql+asyncpg://box:box_secret@127.0.0.1:15432/sathop_lt \\
    --orch http://127.0.0.1:8000 --token T \\
    --granules 4000 --workers 16 --receivers 4 --duration 60

Reports delivered/min throughput + health p50/p95/max. Compare workers=1 vs
workers=N: throughput should rise with cores and health must stay flat (no
event-loop blocking).
"""

from __future__ import annotations

import argparse
import asyncio
import secrets
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

_SHA = "0" * 64


async def seed(pg_url: str, batch_id: str, n: int) -> None:
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

    from sathop.orchestrator.db import Base, Batch, Granule
    from sathop.shared.protocol import GranuleState

    eng = create_async_engine(pg_url)
    try:
        async with eng.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with AsyncSession(eng) as s:
            s.add(Batch(batch_id=batch_id, name="loadtest", bundle_ref="loadtest:fake"))
            await s.flush()
            for base in range(0, n, 1000):
                s.add_all(
                    Granule(
                        granule_id=f"{batch_id}:g{i}",
                        batch_id=batch_id,
                        state=GranuleState.PENDING.value,
                        inputs=[],
                    )
                    for i in range(base, min(base + 1000, n))
                )
                await s.flush()
            await s.commit()
    finally:
        await eng.dispose()


class Stats:
    def __init__(self) -> None:
        self.events = 0
        self.acks = 0
        self.deletes = 0
        self.errors = 0
        self.health: list[float] = []


async def worker_loop(c: httpx.AsyncClient, wid: str, capacity: int, st: Stats, stop: asyncio.Event) -> None:
    await c.post("/api/workers/register", json={"worker_id": wid, "capacity": capacity})
    while not stop.is_set():
        # Confirm anything delivered (acked) so it reaches DELETED.
        try:
            d = await c.get(f"/api/workers/deletable/{wid}")
            for g in d.json():
                await c.post(
                    "/api/workers/events",
                    json={
                        "kind": "delete_confirmed",
                        "granule_id": g["granule_id"],
                        "worker_id": wid,
                        "object_keys": g["object_keys"],
                    },
                )
                st.deletes += 1
        except Exception:
            st.errors += 1

        try:
            r = await c.post("/api/workers/lease", json={"worker_id": wid, "capacity": capacity})
            items = r.json().get("items", [])
        except Exception:
            st.errors += 1
            await asyncio.sleep(0.05)
            continue
        if not items:
            await asyncio.sleep(0.02)
            continue
        for it in items:
            gid = it["granule_id"]
            try:
                await c.post(
                    "/api/workers/events",
                    json={"kind": "download_started", "granule_id": gid, "worker_id": wid},
                )
                await c.post(
                    "/api/workers/events",
                    json={"kind": "process_started", "granule_id": gid, "worker_id": wid, "download_ms": 5},
                )
                await c.post(
                    f"/api/granules/{gid}/progress",
                    json={"step": "process", "pct": 50.0, "batch_id": it["batch_id"]},
                )
                await c.post(
                    "/api/workers/events",
                    json={
                        "kind": "upload_completed",
                        "granule_id": gid,
                        "worker_id": wid,
                        "process_ms": 5,
                        "objects": [
                            {
                                "object_key": f"{gid}.out",
                                "presigned_url": f"http://w/{gid}.out",
                                "sha256": _SHA,
                                "size": 100,
                            }
                        ],
                    },
                )
                st.events += 3
            except Exception:
                st.errors += 1


async def receiver_loop(c: httpx.AsyncClient, rid: str, st: Stats, stop: asyncio.Event) -> None:
    await c.post("/api/receivers/register", json={"receiver_id": rid})
    while not stop.is_set():
        try:
            r = await c.post("/api/receivers/pull", json={"receiver_id": rid, "limit": 50})
            items = r.json().get("items", [])
        except Exception:
            st.errors += 1
            await asyncio.sleep(0.05)
            continue
        if not items:
            await asyncio.sleep(0.02)
            continue
        for it in items:
            try:
                await c.post(
                    "/api/receivers/ack",
                    json={
                        "receiver_id": rid,
                        "object_id": it["object_id"],
                        "sha256": it["sha256"],
                        "success": True,
                    },
                )
                st.acks += 1
            except Exception:
                st.errors += 1


async def health_sampler(c: httpx.AsyncClient, st: Stats, stop: asyncio.Event) -> None:
    while not stop.is_set():
        t0 = time.monotonic()
        try:
            await c.get("/api/health")
            st.health.append((time.monotonic() - t0) * 1000)
        except Exception:
            st.health.append(99_999.0)
        await asyncio.sleep(0.2)


async def delivered(c: httpx.AsyncClient) -> int:
    try:
        r = await c.get("/api/admin/overview")
        return int(r.json().get("state_counts", {}).get("deleted", 0))
    except Exception:
        return -1


def pct(xs: list[float], p: float) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    return s[min(len(s) - 1, int(len(s) * p))]


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pg", required=True)
    ap.add_argument("--orch", required=True)
    ap.add_argument("--token", default="")
    ap.add_argument("--granules", type=int, default=4000)
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--receivers", type=int, default=4)
    ap.add_argument("--capacity", type=int, default=20)
    ap.add_argument("--duration", type=int, default=60)
    ap.add_argument("--tag", default="", help="disambiguates the batch id + node ids for parallel drivers")
    ap.add_argument("--seed-only", action="store_true")
    a = ap.parse_args()

    tag = a.tag or "0"
    batch_id = f"lt-{tag}-{secrets.token_hex(3)}"  # unique per run → re-runnable without recreating the DB
    print(f"seeding {a.granules} granules into batch {batch_id} …", flush=True)
    await seed(a.pg, batch_id, a.granules)
    if a.seed_only:
        return

    headers = {"Authorization": f"Bearer {a.token}"} if a.token else {}
    limits = httpx.Limits(max_connections=a.workers + a.receivers + 4, max_keepalive_connections=64)
    st = Stats()
    stop = asyncio.Event()

    async with httpx.AsyncClient(base_url=a.orch, headers=headers, timeout=30.0, limits=limits) as c:
        d0 = await delivered(c)
        t0 = time.monotonic()
        tasks = [
            asyncio.create_task(worker_loop(c, f"lt-{tag}-w{i}", a.capacity, st, stop))
            for i in range(a.workers)
        ]
        tasks += [
            asyncio.create_task(receiver_loop(c, f"lt-{tag}-r{i}", st, stop)) for i in range(a.receivers)
        ]
        tasks.append(asyncio.create_task(health_sampler(c, st, stop)))

        # Stop early once everything is delivered.
        deadline = t0 + a.duration
        last = d0
        while time.monotonic() < deadline:
            await asyncio.sleep(2.0)
            now = await delivered(c)
            elapsed = time.monotonic() - t0
            rate = (now - d0) / elapsed * 60 if elapsed > 0 else 0
            print(
                f"  t={elapsed:5.1f}s delivered={now:6d} (+{now - last:4d}) "
                f"~{rate:7.1f}/min health_p95={pct(st.health, 0.95):6.1f}ms",
                flush=True,
            )
            last = now
            if now - d0 >= a.granules:
                break

        stop.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        elapsed = time.monotonic() - t0
        final = await delivered(c)

    done = final - d0
    print("\n=== load test result ===", flush=True)
    print(f"workers={a.workers} receivers={a.receivers} granules={a.granules}", flush=True)
    print(f"delivered={done} in {elapsed:.1f}s  →  {done / elapsed * 60:.1f}/min", flush=True)
    print(f"events={st.events} acks={st.acks} deletes={st.deletes} errors={st.errors}", flush=True)
    h = st.health
    print(
        f"health latency (n={len(h)}): p50={pct(h, 0.5):.1f}ms "
        f"p95={pct(h, 0.95):.1f}ms p99={pct(h, 0.99):.1f}ms max={max(h) if h else 0:.1f}ms",
        flush=True,
    )


if __name__ == "__main__":
    asyncio.run(main())
