"""GET /api/admin/stuck — top-N stuck granules across every non-terminal state.
Powers the Dashboard's stuck-granule drill-down so operators can actually see
which granules to investigate, instead of just the count."""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from sathop.orchestrator import db as orch_db
from sathop.orchestrator.api.admin import STUCK_AGE_HOURS
from sathop.orchestrator.config import settings
from sathop.orchestrator.db import Batch, Granule, utcnow
from sathop.orchestrator.main import app
from sathop.shared.protocol import GranuleState


@pytest.fixture
async def client(tmp_path):
    object.__setattr__(settings, "db_path", tmp_path / "test.db")
    object.__setattr__(settings, "token", "")
    await orch_db.init_db()
    try:
        yield TestClient(app)
    finally:
        await orch_db.shutdown_db()


async def _seed(rows: list[tuple[str, str, float]]) -> None:
    """rows: (granule_id, state, age_hours_since_update)."""
    now = utcnow()
    async with orch_db._session_maker() as s:
        s.add(Batch(batch_id="b", name="t", bundle_ref="orch:x@1"))
        for gid, state, age_h in rows:
            s.add(
                Granule(
                    granule_id=gid,
                    batch_id="b",
                    state=state,
                    inputs_json="[]",
                    updated_at=now - timedelta(hours=age_h),
                )
            )
        await s.commit()


async def test_returns_stuck_across_every_state(client):
    """One stuck granule per non-terminal state — endpoint surfaces them all."""
    threshold = STUCK_AGE_HOURS + 1
    await _seed(
        [
            ("g_pending", GranuleState.PENDING.value, threshold),
            ("g_downloading", GranuleState.DOWNLOADING.value, threshold),
            ("g_processing", GranuleState.PROCESSING.value, threshold),
            ("g_uploaded", GranuleState.UPLOADED.value, threshold),
            ("g_acked", GranuleState.ACKED.value, threshold),  # acked is non-terminal here
        ]
    )
    rows = client.get("/api/admin/stuck").json()
    assert {r["granule_id"] for r in rows} == {
        "g_pending",
        "g_downloading",
        "g_processing",
        "g_uploaded",
        "g_acked",
    }
    # Each row carries the state — the UI shows it as a Badge.
    states = {r["granule_id"]: r["state"] for r in rows}
    assert states["g_pending"] == GranuleState.PENDING.value


async def test_excludes_terminal_states(client):
    """deleted / failed / blacklisted are terminal — never "stuck", even if old."""
    await _seed(
        [
            ("g_done", GranuleState.DELETED.value, 100),
            ("g_failed", GranuleState.FAILED.value, 100),
            ("g_blacklisted", GranuleState.BLACKLISTED.value, 100),
        ]
    )
    rows = client.get("/api/admin/stuck").json()
    assert rows == []


async def test_excludes_recent_non_terminal(client):
    """Same state, just updated — not stuck yet."""
    await _seed(
        [
            ("g_old", GranuleState.PROCESSING.value, STUCK_AGE_HOURS + 5),
            ("g_fresh", GranuleState.PROCESSING.value, 0.5),
        ]
    )
    ids = {r["granule_id"] for r in client.get("/api/admin/stuck").json()}
    assert ids == {"g_old"}


async def test_oldest_first(client):
    await _seed(
        [
            ("g_50h", GranuleState.PROCESSING.value, 50),
            ("g_8h", GranuleState.PROCESSING.value, 8),
            ("g_24h", GranuleState.PROCESSING.value, 24),
        ]
    )
    rows = client.get("/api/admin/stuck").json()
    assert [r["granule_id"] for r in rows] == ["g_50h", "g_24h", "g_8h"]
    # age_hours is roughly the seeded age — within rounding.
    assert rows[0]["age_hours"] >= 49


async def test_limit_clamped(client):
    await _seed([(f"g{i}", GranuleState.PROCESSING.value, STUCK_AGE_HOURS + 1) for i in range(60)])
    assert len(client.get("/api/admin/stuck?limit=10").json()) == 10
    # Caller-supplied 0 / negative → server clamps to 1, not silently disabled.
    assert len(client.get("/api/admin/stuck?limit=0").json()) == 1


async def test_orchestrator_info_exposes_new_fields(client):
    body = client.get("/api/admin/settings/info").json()
    assert "max_pull_failures" in body
    assert "stuck_age_hours" in body
    assert body["stuck_age_hours"] == STUCK_AGE_HOURS
    assert body["max_pull_failures"] == settings.max_pull_failures
