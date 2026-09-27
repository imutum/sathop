"""Operator workflow regressions: retained pagination, safe retries, export."""

from __future__ import annotations

import csv
import io
import os

import pytest
from httpx import ASGITransport, AsyncClient

from sathop.orchestrator import db
from sathop.orchestrator.api import batch_reports
from sathop.orchestrator.db import Batch, Granule, GranuleObject, utcnow
from sathop.orchestrator.main import app


@pytest.fixture(params=["sqlite", "postgres"])
async def client(tmp_path, patch_settings, request):
    pg_url = os.getenv("SATHOP_TEST_PG_URL") if request.param == "postgres" else ""
    if request.param == "postgres" and not pg_url:
        pytest.skip("set SATHOP_TEST_PG_URL for Postgres operator workflow tests")
    patch_settings(db_path=tmp_path / "operations.db", database_url=pg_url, token="")
    await db.init_db()
    if pg_url:
        async with db._engine.begin() as conn:
            await conn.run_sync(db.Base.metadata.drop_all)
            await conn.run_sync(db.Base.metadata.create_all)
    async with db.get_session_maker()() as s:
        s.add(
            Batch(
                batch_id="b",
                name="=客户项目",
                bundle_ref="orch:x@1",
                delivered_count=468,
                credentials={"source": {"token": "SECRET_CREDENTIAL"}},
            )
        )
        s.add(Batch(batch_id="other", name="other", bundle_ref="orch:x@1"))
        await s.flush()
        for bid, gid, state in [
            ("b", "b:tile_01", "failed"),
            ("b", "b:tile_02", "blacklisted"),
            ("b", "b:tileX01", "uploaded"),
            ("b", "b:100%", "deleted"),
            ("other", "other:tile_01", "failed"),
        ]:
            s.add(
                Granule(
                    batch_id=bid,
                    granule_id=gid,
                    state=state,
                    inputs=[],
                    error="SECRET_ERROR",
                    stdout_tail="SECRET_LOG",
                )
            )
        await s.flush()
        for i in range(5):
            s.add(
                GranuleObject(
                    granule_id="b:tileX01",
                    worker_id="worker",
                    object_key="=formula.csv" if i == 0 else f"result-{i}.tif",
                    presigned_url="https://private.invalid/?token=SECRET_URL",
                    size=i + 100,
                    sha256=str(i) * 64,
                    acked_at=utcnow() if i else None,
                    acked_by="receiver" if i else None,
                )
            )
        s.add(
            GranuleObject(
                granule_id="other:tile_01",
                worker_id="worker",
                object_key="OTHER_BATCH_PRIVATE",
                presigned_url="",
                size=1,
                sha256="f" * 64,
            )
        )
        await s.commit()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as test_client:
            yield test_client
    finally:
        await db.shutdown_db()


async def test_retained_page_ignores_pruned_cumulative_total(client):
    r = await client.get("/api/batches/b/granule-page?limit=2")
    assert r.status_code == 200
    assert r.json()["total"] == 4
    assert r.json()["archived_delivered"] == 467
    first = {g["granule_id"] for g in r.json()["items"]}
    next_page = (await client.get("/api/batches/b/granule-page?limit=2&offset=2")).json()
    assert first.isdisjoint(g["granule_id"] for g in next_page["items"])
    deleted = (await client.get("/api/batches/b/granule-page?state=deleted")).json()
    assert deleted["total"] == 1
    assert len(deleted["items"]) == 1


@pytest.mark.parametrize(
    ("q", "state", "ids"),
    [
        ("TILE_01", None, ["b:tile_01"]),
        ("%", None, ["b:100%"]),
        ("tile", "blacklisted", ["b:tile_02"]),
        ("absent", None, []),
    ],
)
async def test_search_literal_case_insensitive_and_batch_scoped(client, q, state, ids):
    params = {"q": q}
    if state:
        params["state"] = state
    data = (await client.get("/api/batches/b/granule-page", params=params)).json()
    assert data["total"] == len(ids)
    assert [r["granule_id"] for r in data["items"]] == ids


@pytest.mark.parametrize("query", ["state=bogus", "limit=0", "offset=-1", "q=" + "x" * 201])
async def test_invalid_page_query_rejected(client, query):
    assert (await client.get(f"/api/batches/b/granule-page?{query}")).status_code == 422


async def test_normal_retry_does_not_restart_cancelled_or_other_batch(client):
    response = await client.post("/api/batches/b/retry-failed?include_blacklisted=false")
    assert response.json()["reset"] == 1
    async with db.get_session_maker()() as s:
        assert (await s.get(Granule, "b:tile_01")).state == "pending"
        assert (await s.get(Granule, "b:tile_02")).state == "blacklisted"
        assert (await s.get(Granule, "other:tile_01")).state == "failed"
    assert (await client.post("/api/batches/b/retry-failed?include_blacklisted=true")).json()["reset"] == 1


async def test_report_manifests_all_chunks_without_private_fields(client, monkeypatch):
    monkeypatch.setattr(batch_reports, "_CHUNK_SIZE", 2)
    r = await client.get("/api/batches/b/delivery-report")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"
    assert "attachment" in r.headers["content-disposition"]
    assert r.text.startswith("\ufeff")
    rows = list(csv.reader(io.StringIO(r.text.lstrip("\ufeff"))))
    assert ["批次名称", "'=客户项目"] in rows
    assert ["累计已交付", "468"] in rows
    assert ["历史已清理明细（数据粒）", "467"] in rows
    manifests = [row for row in rows if row and row[0] == "b:tileX01"]
    assert len(manifests) == 5
    assert manifests[0][1] == "'=formula.csv"
    assert manifests[0][4] == "待交付"
    assert all(row[4] == "已交付" for row in manifests[1:])
    assert "SECRET" not in r.text
    assert "OTHER_BATCH_PRIVATE" not in r.text


@pytest.mark.parametrize("path", ["granule-page", "delivery-report", "retry-failed"])
async def test_missing_batch(client, path):
    call = client.post if path == "retry-failed" else client.get
    assert (await call(f"/api/batches/missing/{path}")).status_code == 404


@pytest.mark.parametrize("path", ["granule-page", "delivery-report"])
async def test_report_and_search_require_auth(client, patch_settings, path):
    patch_settings(token="example-test-token")
    assert (await client.get(f"/api/batches/b/{path}")).status_code == 401


@pytest.mark.parametrize("value", ["=1+1", "  +1", "-1", "@SUM(A1)", "\tplain", "\rplain", "\nplain"])
def test_report_formula_escaping(value):
    assert next(csv.reader(io.StringIO(batch_reports._csv([[value]]))))[0] == "'" + value
