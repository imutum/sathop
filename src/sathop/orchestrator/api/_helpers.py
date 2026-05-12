from __future__ import annotations

from typing import Any, TypeVar

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

T = TypeVar("T")


async def get_or_404(s: AsyncSession, model: type[T], key: Any, detail: str) -> T:
    obj = await s.get(model, key)
    if obj is None:
        raise HTTPException(404, detail)
    return obj
