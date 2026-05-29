"""SSE /api/stream — survives heartbeat cycles, delivers published events.

Regression: an earlier impl wrapped ``q.get()`` in an async generator and
called ``asyncio.wait_for(gen.__anext__(), timeout=HB)``. The first heartbeat
cancelled the wrapped ``__anext__`` and corrupted the generator — every
subsequent ``__anext__`` raised ``StopAsyncIteration`` immediately, ending the
stream right after the first keepalive. The fix exposes the queue directly so
each ``q.get()`` is a fresh awaitable that cancels safely.
"""

from __future__ import annotations

import asyncio

import pytest

from sathop.orchestrator.pubsub import publish, subscribe, subscriber_count


async def test_subscribe_cleans_up_queue_on_exit():
    before = subscriber_count()
    with subscribe() as q:
        assert subscriber_count() == before + 1
        publish({"scope": "events"})
        assert q.get_nowait() == {"scope": "events"}
    assert subscriber_count() == before


async def test_subscribe_queue_survives_wait_for_cancellation():
    """Repro the heartbeat bug: cancelling a wait_for(q.get()) must NOT
    corrupt the queue. After timeout, the next q.get() must still deliver
    a freshly-published event. (The pre-fix async-generator wrapper would
    raise StopAsyncIteration on the second __anext__ here.)"""
    with subscribe() as q:
        # First poll: nothing pending, must time out.
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(q.get(), timeout=0.05)

        # Now publish and consume — must succeed.
        publish({"scope": "batches"})
        evt = await asyncio.wait_for(q.get(), timeout=0.5)
        assert evt == {"scope": "batches"}

        # And again, to be sure the queue is still healthy.
        publish({"scope": "workers"})
        evt = await asyncio.wait_for(q.get(), timeout=0.5)
        assert evt == {"scope": "workers"}


async def test_publish_to_no_subscribers_is_safe():
    # Drain in case of leakage from earlier tests.
    assert subscriber_count() == 0
    publish({"scope": "events"})  # must not raise


async def test_concurrent_subscribers_each_get_event():
    with subscribe() as q1, subscribe() as q2:
        publish({"scope": "shared"})
        assert q1.get_nowait() == {"scope": "shared"}
        assert q2.get_nowait() == {"scope": "shared"}


async def test_repeat_scope_nudges_coalesced():
    # A burst of the same scope (the receiver-ack storm): the first nudge fans out
    # immediately; the rest collapse into the 1s window instead of one-per-ack.
    with subscribe() as q:
        for _ in range(10):
            publish({"scope": "batches"})
        assert q.get_nowait() == {"scope": "batches"}  # leading edge, immediate
        assert q.empty()  # the other 9 coalesced — not yet flushed


async def test_coalesced_scope_flushes_on_trailing_edge():
    with subscribe() as q:
        publish({"scope": "batches"})  # leading
        publish({"scope": "batches"})  # coalesced into the window
        assert q.get_nowait() == {"scope": "batches"}
        evt = await asyncio.wait_for(q.get(), timeout=2.0)  # trailing flush ~1s later
        assert evt == {"scope": "batches"}
        assert q.empty()  # exactly one trailing flush, window then closes


async def test_distinct_scopes_not_coalesced():
    # Per-scope windows: a different scope is never delayed by another's open window.
    with subscribe() as q:
        publish({"scope": "batches"})
        publish({"scope": "workers"})
        got = {q.get_nowait()["scope"], q.get_nowait()["scope"]}
        assert got == {"batches", "workers"}  # both immediate


async def test_shutdown_and_data_events_bypass_coalescing():
    with subscribe() as q:
        publish({"scope": "batches"})  # opens a batches window
        assert q.get_nowait() == {"scope": "batches"}
        # __shutdown__ and data-carrying events must never be coalesced/delayed.
        publish({"scope": "__shutdown__"})
        publish({"scope": "progress", "granule_id": "g1", "batch_id": "b1"})
        assert q.get_nowait() == {"scope": "__shutdown__"}
        assert q.get_nowait() == {"scope": "progress", "granule_id": "g1", "batch_id": "b1"}
