from __future__ import annotations

import pytest
from fastapi import HTTPException

from sathop.orchestrator.api._helpers import get_or_404
from sathop.orchestrator.db import Worker


class Session:
    def __init__(self, obj):
        self.obj = obj

    async def get(self, model, key):
        self.model = model
        self.key = key
        return self.obj


async def test_get_or_404_returns_object():
    worker = Worker(worker_id="w1")
    s = Session(worker)
    assert await get_or_404(s, Worker, "w1", "missing") is worker
    assert s.model is Worker
    assert s.key == "w1"


async def test_get_or_404_raises_404():
    with pytest.raises(HTTPException) as exc:
        await get_or_404(Session(None), Worker, "w1", "missing")
    assert exc.value.status_code == 404
    assert exc.value.detail == "missing"
