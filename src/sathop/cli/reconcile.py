"""Operational status report. Queries orchestrator, prints summary + anomalies.

Usage:
    sathop-reconcile --url sathop://TOKEN@host:port
    sathop-reconcile --orchestrator http://... --token ...   # legacy split form
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime

import httpx

from sathop.shared.config import cli_resolve_orch
from sathop.shared.http import bearer_headers


def _fmt_age(iso: str) -> str:
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    secs = (datetime.now(UTC) - dt).total_seconds()
    if secs < 60:
        return f"{int(secs)}s"
    if secs < 3600:
        return f"{int(secs // 60)}m"
    if secs < 86400:
        return f"{secs / 3600:.1f}h"
    return f"{secs / 86400:.1f}d"


def main() -> int:
    p = argparse.ArgumentParser(description="SatHop operational status report")
    p.add_argument(
        "--url",
        default=os.getenv("SATHOP_URL", ""),
        help="sathop://TOKEN@host:port — overrides --orchestrator/--token (reads SATHOP_URL env)",
    )
    p.add_argument("--orchestrator", default=os.getenv("SATHOP_ORCH_URL", "http://127.0.0.1:8765"))
    p.add_argument("--token", default=os.getenv("SATHOP_TOKEN", ""))
    args = p.parse_args()
    try:
        base, token = cli_resolve_orch(args.url, args.orchestrator, args.token, require_token=False)
    except ValueError as e:
        sys.exit(f"error: {e}")
    headers = bearer_headers(token) if token else {}

    issues: list[str] = []

    with httpx.Client(timeout=15, headers=headers) as c:
        overview = c.get(f"{base}/api/admin/overview").json()
        workers = c.get(f"{base}/api/workers").json()
        receivers = c.get(f"{base}/api/receivers").json()
        batches = c.get(f"{base}/api/batches").json()

        print("=" * 60)
        print(f"SatHop @ {base}")
        print("=" * 60)

        print("\n── Granule state totals ──")
        counts = overview["state_counts"]
        if not counts:
            print("  (empty)")
        for state, n in sorted(counts.items(), key=lambda kv: -kv[1]):
            print(f"  {state:<14} {n:>8}")

        stuck_h = overview["stuck_over_hours"]
        stuck = overview["stuck_by_state"]
        if stuck:
            print(f"\n── Stuck > {stuck_h}h ──")
            for state, n in stuck.items():
                print(f"  {state:<14} {n:>8}")
                issues.append(f"{n} granules stuck in '{state}' > {stuck_h}h")
                sample = c.get(f"{base}/api/admin/stuck/{state}").json()[:3]
                for g in sample:
                    print(
                        f"     └─ {g['granule_id']}  age={g['age_hours']:.1f}h  batch={g['batch_id']}  err={g.get('error') or '-'}"
                    )

        print("\n── Workers ──")
        if not workers:
            print("  (none registered)")
        for w in workers:
            age = _fmt_age(w["last_seen"])
            bar = f"{w['disk_used_gb']:.1f}/{w['disk_total_gb']:.1f}G"
            print(
                f"  {w['worker_id']:<12}  last_seen={age:<6}  disk={bar:<14}  cpu={w['cpu_percent']:>5.1f}%  queues d/p/u={w['queue_downloading']}/{w['queue_processing']}/{w['queue_uploading']}"
            )
            if age.endswith(("h", "d")) or (age.endswith("m") and int(age[:-1]) > 5):
                issues.append(f"worker {w['worker_id']} stale heartbeat: {age}")

        print("\n── Receivers ──")
        if not receivers:
            print("  (none registered)")
        for r in receivers:
            age = _fmt_age(r["last_seen"])
            print(
                f"  {r['receiver_id']:<16}  platform={r['platform']:<8}  last_seen={age:<6}  free={r['disk_free_gb']:.1f}G"
            )
            if age.endswith(("h", "d")) or (age.endswith("m") and int(age[:-1]) > 5):
                issues.append(f"receiver {r['receiver_id']} stale heartbeat: {age}")

        print("\n── Batches ──")
        if not batches:
            print("  (none)")
        for b in batches:
            counts = b["counts"]
            done = counts.get("deleted", 0) + counts.get("acked", 0)
            total = sum(counts.values())
            pct = (done / total * 100) if total else 0
            err = counts.get("blacklisted", 0) + counts.get("failed", 0)
            tag = f"{done}/{total}  {pct:.0f}%"
            if err:
                tag += f"  !!{err} errors"
            print(f"  {b['batch_id']:<24}  target={b['target_receiver_id'] or 'any':<16}  {tag}")
            if err:
                issues.append(f"batch {b['batch_id']}: {err} failed/blacklisted granules")

        print("\n── Recent events ──")
        for e in overview["last_events"]:
            print(f"  [{e['level']:<5}] {_fmt_age(e['ts']):<6} {e['source']:<14} {e['message']}")

    print("\n" + ("─" * 60))
    if issues:
        print(f"ISSUES ({len(issues)}):")
        for i in issues:
            print(f"  ! {i}")
        return 1
    print("OK — no anomalies.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
