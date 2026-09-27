"""Commercial operator workflows across SQLite and production PostgreSQL."""

import asyncio
import csv
import hashlib
import io
import os

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select
from test_receiver_pipeline import _serve_static

from sathop.orchestrator import db
from sathop.orchestrator.api.deliveries import export_deliveries
from sathop.orchestrator.delivery_ledger import archive_confirmed, iter_receipt_chunks
from sathop.orchestrator.main import app
from sathop.orchestrator.reaping import reap_granules
from sathop.receiver.ack_buffer import AckBuffer
from sathop.receiver.config import Settings as ReceiverSettings
from sathop.receiver.runtime import Receiver
from sathop.shared.protocol import PullResponse


@pytest.fixture(params=["sqlite", "postgres"])
async def client(tmp_path, patch_settings, request):
    url = os.getenv("SATHOP_TEST_PG_URL", "") if request.param == "postgres" else ""
    if request.param == "postgres" and not url:
        pytest.skip("SATHOP_TEST_PG_URL required")
    patch_settings(db_path=tmp_path / "service.db", database_url=url, token="")
    await db.init_db()
    async with db._engine.begin() as conn:
        await conn.run_sync(db.Base.metadata.drop_all)
        await conn.run_sync(db.Base.metadata.create_all)
    async with db.get_session_maker()() as s:
        s.add(db.Bundle(name="x", version="1", sha256="a" * 64, size=1, manifest={}))
        s.add(db.Receiver(receiver_id="r"))
        s.add(db.Batch(batch_id="b", name="=客户订单", bundle_ref="orch:x@1"))
        await s.flush()
        s.add(db.Granule(granule_id="b:g", batch_id="b", inputs=[], state="uploaded"))
        await s.flush()
        for i in (1, 2):
            s.add(
                db.GranuleObject(
                    granule_id="b:g",
                    worker_id="w",
                    object_key=f"=result_{i}%.tif",
                    sha256=str(i) * 64,
                    size=100 * i,
                    presigned_url="https://secret.invalid/PRIVATE_TOKEN",
                )
            )
        await s.commit()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c
    finally:
        await db.shutdown_db()


def ack_body(i=1, **overrides):
    return {"object_id": i, "receiver_id": "r", "sha256": str(i) * 64, "success": True, **overrides}


async def test_receipt_export_bounds_and_releases_connections_between_chunks(client):
    # Enough receipts to cross the default 500-row export boundary.
    async with db.get_session_maker()() as s:
        for index in range(503):
            s.add(
                db.DeliveryRecord(
                    identity=f"{index:064x}",
                    source_object_id=index,
                    uploaded_at=db.utcnow(),
                    batch_id="b" if index % 2 else "other",
                    batch_name="客户",
                    bundle_ref="orch:x@1",
                    granule_id=f"b:g{index}",
                    object_key=f"file-{index}.tif",
                    sha256="a" * 64,
                    size=index,
                    receiver_id="r",
                    delivered_at=db.utcnow(),
                )
            )
        await s.commit()
        upper = await s.scalar(select(func.max(db.DeliveryRecord.id)))
        response = await export_deliveries(conditions=[], s=s)

    # A successful ACK after the export starts must not extend that export.
    assert (await client.post("/api/receivers/ack", json=ack_body())).status_code == 200
    text = "".join([chunk async for chunk in response.body_iterator])
    rows = list(csv.reader(io.StringIO(text.lstrip("\ufeff"))))
    assert [row[4] for row in rows[3:]] == [f"file-{index}.tif" for index in range(503)]

    exported = []
    async for receipts in iter_receipt_chunks(
        db.DeliveryRecord.batch_id == "b", upper_id=upper, chunk_size=100
    ):
        assert len(receipts) <= 100
        assert db._engine.pool.checkedout() == 0
        exported.extend(receipt.object_key for receipt in receipts)
    assert exported == [f"file-{index}.tif" for index in range(1, 503, 2)]


async def test_ack_receipt_is_immutable_and_failure_cannot_undo_it(client):
    assert (await client.post("/api/receivers/ack", json=ack_body(sha256="wrong"))).status_code == 400
    assert (await client.get("/api/deliveries")).json()["total"] == 0
    assert (await client.post("/api/receivers/ack", json=ack_body())).status_code == 200
    first = (await client.get("/api/deliveries")).json()
    await client.post("/api/receivers/ack", json=ack_body(receiver_id="another"))
    await client.post("/api/receivers/ack", json=ack_body(success=False, error="late failure"))
    assert (await client.get("/api/deliveries")).json() == first
    async with db.get_session_maker()() as s:
        obj = await s.get(db.GranuleObject, 1)
        assert obj.acked_by == "r" and not obj.failed_pulls


async def test_batch_ack_deduplicates_and_promotes_task(client):
    body = {"acks": [ack_body(), ack_body(), ack_body(2), ack_body(2, success=False), ack_body(999)]}
    assert (await client.post("/api/receivers/ack/batch", json=body)).status_code == 200
    assert (await client.post("/api/receivers/ack/batch", json=body)).status_code == 200
    result = (await client.get("/api/deliveries")).json()
    assert (result["total"], result["total_bytes"], result["granules"], result["batches"]) == (2, 300, 1, 1)
    async with db.get_session_maker()() as s:
        assert (await s.get(db.Granule, "b:g")).state == "acked"


async def test_concurrent_ack_keeps_one_receipt(client):
    if not db.is_postgres():
        pytest.skip("row-lock concurrency is PostgreSQL-only")
    responses = await asyncio.gather(*(client.post("/api/receivers/ack", json=ack_body()) for _ in range(12)))
    assert all(r.status_code == 200 for r in responses)
    assert (await client.get("/api/deliveries")).json()["total"] == 1


async def test_receipt_and_task_rollback_together(client):
    async with db.get_session_maker()() as s:
        obj = await s.get(db.GranuleObject, 1)
        obj.acked_at = db.utcnow()
        obj.acked_by = "r"
        await s.flush()
        await archive_confirmed(s)
        assert await s.scalar(select(func.count()).select_from(db.DeliveryRecord)) == 1
        await s.rollback()
    assert (await client.get("/api/deliveries")).json()["total"] == 0
    async with db.get_session_maker()() as s:
        assert (await s.get(db.GranuleObject, 1)).acked_at is None


async def test_real_file_verified_then_receipt_survives_retention(client, tmp_path):
    payload = bytes(range(256)) * 2048
    sha = hashlib.sha256(payload).hexdigest()
    server, port = _serve_static(payload)
    receiver = Receiver(
        ReceiverSettings(
            receiver_id="r",
            orchestrator_url="http://test",
            token="",
            storage_dir=tmp_path / "received",
            poll_interval=1,
            concurrent_pulls=1,
            platform="windows",
            pull_segments=1,
        )
    )

    class AckEndpoint:
        async def ack_batch(self, batch):
            response = await client.post("/api/receivers/ack/batch", json=batch.model_dump())
            response.raise_for_status()

    receiver._acks = AckBuffer(AckEndpoint())
    try:
        async with db.get_session_maker()() as s:
            await s.execute(delete(db.GranuleObject).where(db.GranuleObject.id == 2))
            obj = await s.get(db.GranuleObject, 1)
            obj.object_key = "delivery/result.bin"
            obj.size = len(payload)
            obj.presigned_url = f"http://127.0.0.1:{port}/file"
            await s.commit()
        # First transfer deliberately advertises the wrong SHA: no receipt.
        response = await client.post("/api/receivers/pull", json={"receiver_id": "r", "limit": 1})
        item = PullResponse.model_validate(response.json()).items[0]
        await receiver._fetch_one_inner(item)
        await receiver._acks._flush()
        assert (await client.get("/api/deliveries")).json()["total"] == 0
        assert not (receiver.s.storage_dir / item.object_key).exists()
        async with db.get_session_maker()() as s:
            (await s.get(db.GranuleObject, 1)).sha256 = sha
            await s.commit()
        response = await client.post("/api/receivers/pull", json={"receiver_id": "r", "limit": 1})
        item = PullResponse.model_validate(response.json()).items[0]
        await receiver._fetch_one_inner(item)
        await receiver._acks._flush()
        assert (receiver.s.storage_dir / item.object_key).read_bytes() == payload
        receipt = (await client.get("/api/deliveries")).json()["items"][0]
        assert (receipt["sha256"], receipt["size"], receipt["receiver_id"]) == (sha, len(payload), "r")
        async with db.get_session_maker()() as s:
            await reap_granules(s, ["b:g"])
            await s.commit()
        assert sha in (await client.get("/api/deliveries/export")).text
    finally:
        await receiver.aclose()
        await asyncio.to_thread(server.shutdown)
        server.server_close()


async def test_upgrade_backfills_retained_rows_once_and_preserves_after_cleanup(client):
    async with db.get_session_maker()() as s:
        obj = await s.get(db.GranuleObject, 1)
        obj.acked_at = db.utcnow()
        obj.acked_by = "old-receiver"
        await s.commit()
    # Simulate v1.0.21 schema, then reconcile twice (multi-process / restart).
    async with db._engine.begin() as conn:
        await conn.run_sync(lambda c: db.DeliveryRecord.__table__.drop(c))
        await conn.run_sync(lambda c: db.TaskTemplate.__table__.drop(c))
    await db.shutdown_db()
    await db.init_db()
    await db.shutdown_db()
    await db.init_db()
    first = (await client.get("/api/deliveries")).json()
    assert first["total"] == 1
    assert first["items"][0]["receiver_id"] == "old-receiver"
    async with db.get_session_maker()() as s:
        await reap_granules(s, ["b:g"])
        await s.commit()
    assert (await client.get("/api/deliveries")).json() == first
    report = await client.get("/api/batches/b/delivery-report")
    assert report.text.count("'=result_1%.tif") == 1
    assert (await client.delete("/api/batches/b")).status_code == 200
    kept = (await client.get("/api/deliveries")).json()
    assert kept["total"] == 1 and not kept["items"][0]["batch_exists"]
    exported = await client.get("/api/deliveries/export")
    assert "'=客户订单" in exported.text and "PRIVATE_TOKEN" not in exported.text


async def test_report_combines_retained_pending_and_archived_without_duplicates(client):
    await client.post("/api/receivers/ack", json=ack_body())
    report = await client.get("/api/batches/b/delivery-report")
    rows = list(csv.reader(io.StringIO(report.text.lstrip("\ufeff"))))
    manifests = [r for r in rows if r and r[0] == "b:g"]
    assert len(manifests) == 2
    assert {r[4] for r in manifests} == {"已交付", "待交付"}


async def test_legacy_cleanup_archives_before_delete_and_id_reuse_is_safe(client):
    async with db.get_session_maker()() as s:
        obj = await s.get(db.GranuleObject, 1)
        obj.acked_at = db.utcnow()
        await s.flush()
        await reap_granules(s, ["b:g"])
        await s.commit()
        s.add(db.Granule(granule_id="b:g", batch_id="b", state="uploaded", inputs=[]))
        await s.flush()
        s.add(
            db.GranuleObject(
                id=1,
                granule_id="b:g",
                worker_id="w",
                object_key="fresh",
                size=1,
                sha256="1" * 64,
                presigned_url="",
            )
        )
        await s.commit()
    await client.post("/api/receivers/ack", json=ack_body())
    assert (await client.get("/api/deliveries")).json()["total"] == 2


async def test_search_dates_pagination_and_filtered_export(client):
    await client.post("/api/receivers/ack/batch", json={"acks": [ack_body(), ack_body(2)]})
    page = (await client.get("/api/deliveries?limit=1")).json()
    second = (await client.get("/api/deliveries?limit=1&offset=1")).json()
    assert page["total"] == 2 and page["items"][0]["id"] != second["items"][0]["id"]
    params = {"q": "_1%", "batch_id": "b", "since": "2020-01-01T00:00:00Z", "until": "2100-01-01T00:00:00Z"}
    filtered = (await client.get("/api/deliveries", params=params)).json()
    assert filtered["total"] == 1 and filtered["total_bytes"] == 100
    export = await client.get("/api/deliveries/export", params=params)
    assert "result_1%" in export.text and "result_2%" not in export.text
    assert "PRIVATE_TOKEN" not in export.text and "presigned" not in export.text
    assert (await client.get("/api/deliveries?batch_id=other")).json()["total"] == 0
    assert (await client.get("/api/deliveries?limit=201")).status_code == 422
    assert (
        await client.get("/api/deliveries?since=2030-01-01T00:00:00Z&until=2020-01-01T00:00:00Z")
    ).status_code == 422


def template_body(**kw):
    return {
        "name": "月度产品",
        "bundle_ref": "orch:x@1",
        "target_receiver_id": "r",
        "execution_env": {"FACTOR": "4"},
        **kw,
    }


async def test_template_lifecycle_persistence_and_conflict(client):
    created = await client.post("/api/task-templates", json=template_body())
    assert created.status_code == 201
    tid = created.json()["template_id"]
    assert (await client.post("/api/task-templates", json=template_body())).status_code == 409
    await db.shutdown_db()
    await db.init_db()
    assert (await client.get("/api/task-templates")).json()[0]["template_id"] == tid
    updated = await client.put(
        f"/api/task-templates/{tid}", json=template_body(name="年度产品", execution_env={})
    )
    assert updated.status_code == 200 and updated.json()["execution_env"] == {}
    assert (await client.delete(f"/api/task-templates/{tid}")).status_code == 200
    assert (await client.get("/api/task-templates")).json() == []
    assert (await client.put(f"/api/task-templates/{tid}", json=template_body())).status_code == 404


@pytest.mark.parametrize(
    "changes",
    [
        {"credentials": {"token": "SECRET"}},
        {"granules": []},
        {"name": "  "},
        {"bundle_ref": "url:invalid"},
        {"bundle_ref": "orch:missing@1"},
        {"target_receiver_id": "missing"},
        {"execution_env": {"TOO_BIG": "a" * 17_000}},
    ],
)
async def test_template_rejects_private_fields_and_invalid_config(client, changes):
    assert (await client.post("/api/task-templates", json=template_body(**changes))).status_code == 422


async def test_service_endpoints_require_auth(client, patch_settings):
    patch_settings(token="test-secret")
    for path in ["/api/deliveries", "/api/deliveries/export", "/api/task-templates"]:
        assert (await client.get(path)).status_code == 401
    assert (await client.post("/api/task-templates", json=template_body())).status_code == 401
