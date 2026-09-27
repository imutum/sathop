"""Exercise PG connection loss and batching without requiring a database."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, Mock

import asyncpg

from sathop.orchestrator import pubsub


def connection():
    return Mock(
        close=AsyncMock(), execute=AsyncMock(), add_listener=AsyncMock(), is_closed=Mock(return_value=False)
    )


async def test_sender_coalesces_bursts_without_losing_distinct_payloads(monkeypatch):
    queue = asyncio.Queue()
    monkeypatch.setattr(pubsub, "_notify_q", queue)
    for _ in range(200):
        queue.put_nowait('{"scope":"batches"}')
    for gid in ("g1", "g2"):
        queue.put_nowait(json.dumps({"scope": "progress", "granule_id": gid}))
    conn = connection()
    conn.execute.side_effect = lambda *args: pubsub.request_shutdown()
    monkeypatch.setattr(asyncpg, "connect", AsyncMock(return_value=conn))
    await pubsub.run_notify_sender()
    conn.execute.assert_awaited_once()
    sent = conn.execute.call_args.args[2]
    assert len(sent) == 3  # 202 nudges -> one round trip, three distinct payloads
    assert {json.loads(p).get("granule_id") for p in sent} == {None, "g1", "g2"}
    assert queue.empty()
    conn.close.assert_awaited_once()


async def test_sender_requeues_batch_after_database_timeout(monkeypatch):
    queue = asyncio.Queue()
    monkeypatch.setattr(pubsub, "_notify_q", queue)
    queue.put_nowait('{"scope":"batches"}')
    first, second = connection(), connection()
    first.execute.side_effect = TimeoutError("database timed out")
    second.execute.side_effect = lambda *args: pubsub.request_shutdown()
    connect = AsyncMock(side_effect=[first, second])
    monkeypatch.setattr(asyncpg, "connect", connect)
    monkeypatch.setattr(pubsub.asyncio, "sleep", AsyncMock())
    await pubsub.run_notify_sender()
    assert first.execute.call_args.args[2] == second.execute.call_args.args[2]
    assert connect.await_count == 2
    first.close.assert_awaited_once()
    second.close.assert_awaited_once()


async def test_listener_reconnects_after_silent_socket_loss(monkeypatch):
    first, second = connection(), connection()
    first.is_closed.return_value = True
    connect = AsyncMock(side_effect=[first, second])
    monkeypatch.setattr(asyncpg, "connect", connect)
    ticks = 0

    async def tick(_delay):
        nonlocal ticks
        ticks += 1
        if ticks >= 3:
            pubsub.request_shutdown()

    monkeypatch.setattr(pubsub.asyncio, "sleep", tick)
    nudges = Mock()
    monkeypatch.setattr(pubsub, "_local_publish", nudges)
    await pubsub.run_listener()
    assert connect.await_count == 2
    first.close.assert_awaited_once()
    second.close.assert_awaited_once()
    assert nudges.call_args_list.count((({"scope": "batches"},),)) == 2


async def test_listener_closes_connection_when_cancelled(monkeypatch):
    conn = connection()
    monkeypatch.setattr(asyncpg, "connect", AsyncMock(return_value=conn))
    monkeypatch.setattr(pubsub.asyncio, "sleep", AsyncMock(side_effect=asyncio.CancelledError()))
    try:
        await pubsub.run_listener()
    except asyncio.CancelledError:
        pass
    conn.close.assert_awaited_once()
