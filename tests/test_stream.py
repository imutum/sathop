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
