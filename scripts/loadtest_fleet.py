"""Fleet load driver: spawn K independent OS driver processes (each its own core,
so the single-process asyncio/GIL ceiling can't cap aggregate load) and measure
GLOBAL orchestrator throughput externally. Lets a saturating client reveal the
orch's real per-core scaling, which one single-process driver cannot.

  python scripts/loadtest_fleet.py --pg <url> --orch http://127.0.0.1:8801 \\
    --token lt --procs 4 --workers-per 8 --receivers-per 3 --granules-per 4000 \\
    --duration 55 --measure 30 --warmup 12
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

import httpx


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--orch", required=True)
    ap.add_argument("--pg", required=True)
    ap.add_argument("--token", default="")
    ap.add_argument("--procs", type=int, default=4)
    ap.add_argument("--workers-per", type=int, default=8)
    ap.add_argument("--receivers-per", type=int, default=3)
    ap.add_argument("--granules-per", type=int, default=4000)
    ap.add_argument("--duration", type=int, default=55)
    ap.add_argument("--measure", type=int, default=30)
    ap.add_argument("--warmup", type=int, default=12)
    a = ap.parse_args()

    here = Path(__file__).resolve().parent
    headers = {"Authorization": f"Bearer {a.token}"} if a.token else {}

    procs = []
    for i in range(a.procs):
        cmd = [
            sys.executable,
            str(here / "loadtest_orch.py"),
            "--pg",
            a.pg,
            "--orch",
            a.orch,
            "--token",
            a.token,
            "--granules",
            str(a.granules_per),
            "--workers",
            str(a.workers_per),
            "--receivers",
            str(a.receivers_per),
            "--duration",
            str(a.duration),
            "--tag",
            f"f{i}",
        ]
        procs.append(subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))

    def deleted(c: httpx.Client) -> int:
        try:
            return int(c.get("/api/admin/overview", headers=headers).json()["state_counts"].get("deleted", 0))
        except Exception:
            return -1

    try:
        with httpx.Client(base_url=a.orch, timeout=10.0) as c:
            time.sleep(a.warmup)
            d0 = deleted(c)
            t0 = time.monotonic()
            end = t0 + a.measure
            while time.monotonic() < end:
                time.sleep(3)
                d = deleted(c)
                el = time.monotonic() - t0
                print(f"  t={el:5.1f}s global_delivered={d:7d} ~{(d - d0) / el * 60:8.1f}/min", flush=True)
            d1 = deleted(c)
            dt = time.monotonic() - t0
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.wait(timeout=5)
            except Exception:
                p.kill()

    print(
        f"\nFLEET procs={a.procs} total_workers={a.procs * a.workers_per} "
        f"total_receivers={a.procs * a.receivers_per}: aggregate {(d1 - d0) / dt * 60:.0f}/min "
        f"(delivered {d1 - d0} in {dt:.1f}s)",
        flush=True,
    )


if __name__ == "__main__":
    main()
