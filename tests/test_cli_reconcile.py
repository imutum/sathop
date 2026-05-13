"""CLI `sathop-reconcile`: read-only orchestrator status report.

`httpx.Client` is monkeypatched to route through `MockTransport` — the CLI
talks to a synthetic orchestrator in-process, so we can drive exact response
shapes (stuck rows, stale heartbeats, batch errors) and assert exit codes +
captured stdout.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from sathop.cli import reconcile
from sathop.shared import config as shared_config

# ─── _fmt_age boundaries ────────────────────────────────────────────────────


def _iso(ago_secs: float) -> str:
    return (datetime.now(UTC) - timedelta(seconds=ago_secs)).isoformat()


def test_fmt_age_seconds():
    assert reconcile._fmt_age(_iso(5)).endswith("s")


def test_fmt_age_minutes():
    assert reconcile._fmt_age(_iso(120)).endswith("m")


def test_fmt_age_hours():
    out = reconcile._fmt_age(_iso(7200))
    assert out.endswith("h") and out.startswith("2.0")


def test_fmt_age_days():
    out = reconcile._fmt_age(_iso(86400 * 3))
    assert out.endswith("d") and out.startswith("3.0")


def test_fmt_age_accepts_naive_iso():
    """ISO strings without tz info are treated as UTC — older granule rows
    sometimes get written that way."""
    naive = (datetime.now(UTC) - timedelta(seconds=30)).replace(tzinfo=None).isoformat()
    assert reconcile._fmt_age(naive).endswith("s")


# ─── main() — wired via MockTransport ─────────────────────────────────────


def _install_orch(monkeypatch: pytest.MonkeyPatch, routes: dict[str, object]) -> list[httpx.Request]:
    """Replace `make_sync_orch_client` so the CLI's outbound calls route
    through a MockTransport whose handler picks responses from `routes` by
    URL path. Returns a list that captures each intercepted request."""
    captured: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        captured.append(req)
        body = routes.get(req.url.path)
        if body is None:
            return httpx.Response(404, json={"detail": f"no mock for {req.url.path}"})
        return httpx.Response(200, json=body)

    transport = httpx.MockTransport(handler)

    def patched_factory(orch_url: str, token: str, timeout: float = 30.0) -> httpx.Client:
        from sathop.shared.http import bearer_headers

        return httpx.Client(
            base_url=orch_url,
            timeout=timeout,
            headers=bearer_headers(token),
            transport=transport,
        )

    monkeypatch.setattr(reconcile, "make_sync_orch_client", patched_factory)
    return captured


def _baseline_routes() -> dict[str, object]:
    """A clean orchestrator: no stuck, fresh heartbeats, no batches, no events."""
    fresh = _iso(2)  # 2s ago — well under 5min stale threshold
    return {
        "/api/admin/overview": {
            "state_counts": {"pending": 0, "acked": 5},
            "stuck_over_hours": 6,
            "stuck_by_state": {},
            "last_events": [],
        },
        "/api/workers": [
            {
                "worker_id": "w1",
                "last_seen": fresh,
                "disk_used_gb": 10.0,
                "disk_total_gb": 100.0,
                "cpu_percent": 5.0,
                "queue_downloading": 0,
                "queue_processing": 0,
                "queue_uploading": 0,
            }
        ],
        "/api/receivers": [
            {"receiver_id": "r1", "platform": "linux", "last_seen": fresh, "disk_free_gb": 500.0}
        ],
        "/api/batches": [],
    }


def test_reconcile_clean_exits_zero(monkeypatch, capsys):
    _install_orch(monkeypatch, _baseline_routes())
    monkeypatch.setattr(sys, "argv", ["sathop-reconcile", "--orch-url", "http://x", "--token", "tok"])
    assert reconcile.main() == 0
    out = capsys.readouterr().out
    assert "SatHop @ http://x" in out
    assert "OK — no anomalies." in out


def test_reconcile_empty_overview_prints_empty_marker(monkeypatch, capsys):
    routes = _baseline_routes()
    routes["/api/admin/overview"] = {  # type: ignore[index]
        "state_counts": {},
        "stuck_over_hours": 6,
        "stuck_by_state": {},
        "last_events": [],
    }
    routes["/api/workers"] = []
    routes["/api/receivers"] = []
    _install_orch(monkeypatch, routes)
    monkeypatch.setattr(sys, "argv", ["sathop-reconcile", "--orch-url", "http://x", "--token", ""])
    assert reconcile.main() == 0
    out = capsys.readouterr().out
    assert "(empty)" in out
    assert "(none registered)" in out  # workers + receivers


def test_reconcile_stuck_granules_report_anomaly(monkeypatch, capsys):
    routes = _baseline_routes()
    routes["/api/admin/overview"] = {  # type: ignore[index]
        "state_counts": {"processing": 3},
        "stuck_over_hours": 6,
        "stuck_by_state": {"processing": 2},
        "last_events": [],
    }
    routes["/api/admin/stuck/processing"] = [
        {"granule_id": "g-stuck-1", "age_hours": 12.4, "batch_id": "b1", "error": None},
        {"granule_id": "g-stuck-2", "age_hours": 18.0, "batch_id": "b1", "error": "boom"},
    ]
    _install_orch(monkeypatch, routes)
    monkeypatch.setattr(sys, "argv", ["sathop-reconcile", "--orch-url", "http://x", "--token", "tok"])
    assert reconcile.main() == 1
    out = capsys.readouterr().out
    assert "Stuck > 6h" in out
    assert "g-stuck-1" in out
    assert "ISSUES (1)" in out
    assert "2 granules stuck in 'processing'" in out


def test_reconcile_stale_worker_heartbeat_flagged(monkeypatch, capsys):
    routes = _baseline_routes()
    routes["/api/workers"] = [
        {
            "worker_id": "w-stale",
            "last_seen": _iso(7200),  # 2h ago → ends with 'h'
            "disk_used_gb": 10.0,
            "disk_total_gb": 100.0,
            "cpu_percent": 5.0,
            "queue_downloading": 0,
            "queue_processing": 0,
            "queue_uploading": 0,
        }
    ]
    _install_orch(monkeypatch, routes)
    monkeypatch.setattr(sys, "argv", ["sathop-reconcile", "--orch-url", "http://x", "--token", "tok"])
    assert reconcile.main() == 1
    out = capsys.readouterr().out
    assert "w-stale stale heartbeat" in out


def test_reconcile_batch_errors_flagged(monkeypatch, capsys):
    routes = _baseline_routes()
    routes["/api/batches"] = [
        {
            "batch_id": "b-bad",
            "target_receiver_id": None,
            "counts": {"acked": 1, "blacklisted": 2, "failed": 1},
        }
    ]
    _install_orch(monkeypatch, routes)
    monkeypatch.setattr(sys, "argv", ["sathop-reconcile", "--orch-url", "http://x", "--token", "tok"])
    assert reconcile.main() == 1
    out = capsys.readouterr().out
    assert "b-bad" in out
    assert "!!3 errors" in out
    assert "3 failed/blacklisted" in out


def test_reconcile_missing_token_with_orch_url_ok_anonymous(monkeypatch, capsys):
    """reconcile passes require_token=False → empty token is allowed."""
    _install_orch(monkeypatch, _baseline_routes())
    monkeypatch.setattr(sys, "argv", ["sathop-reconcile", "--orch-url", "http://x"])
    monkeypatch.delenv("SATHOP_TOKEN", raising=False)
    monkeypatch.delenv("SATHOP_URL", raising=False)
    assert reconcile.main() == 0


def test_reconcile_missing_orch_url_exits_with_message(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["sathop-reconcile"])
    monkeypatch.delenv("SATHOP_URL", raising=False)
    monkeypatch.delenv("SATHOP_ORCH_URL", raising=False)
    monkeypatch.setattr(
        shared_config.os,
        "getenv",
        lambda k, default="": "" if k in {"SATHOP_URL", "SATHOP_ORCH_URL", "SATHOP_TOKEN"} else default,
    )
    with pytest.raises(SystemExit) as exc:
        reconcile.main()
    # cli_resolve_orch raises ValueError, main wraps it via sys.exit(str)
    assert "missing orchestrator" in str(exc.value)


def test_reconcile_includes_bearer_when_token_set(monkeypatch):
    captured = _install_orch(monkeypatch, _baseline_routes())
    monkeypatch.setattr(sys, "argv", ["sathop-reconcile", "--orch-url", "http://x", "--token", "secret-tok"])
    reconcile.main()
    auths = {req.headers.get("Authorization", "") for req in captured}
    assert auths == {"Bearer secret-tok"}


def test_reconcile_omits_auth_header_when_token_empty(monkeypatch):
    captured = _install_orch(monkeypatch, _baseline_routes())
    monkeypatch.setattr(sys, "argv", ["sathop-reconcile", "--orch-url", "http://x"])
    monkeypatch.delenv("SATHOP_TOKEN", raising=False)
    monkeypatch.delenv("SATHOP_URL", raising=False)
    reconcile.main()
    auths = {req.headers.get("Authorization") for req in captured}
    assert auths == {None}
