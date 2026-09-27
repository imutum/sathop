"""Reusable operator presets. Credentials and source URLs are never accepted."""

from __future__ import annotations

import json
import secrets
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from sathop.shared.bundle_ref import parse_bundle_ref

from ..config import require_token
from ..db import Bundle, Receiver, TaskTemplate, session, utcnow
from ._helpers import get_or_404

router = APIRouter(prefix="/task-templates", tags=["templates"], dependencies=[Depends(require_token)])


class TemplateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    bundle_ref: str = Field(min_length=1, max_length=200)
    target_receiver_id: str | None = Field(None, max_length=200)
    execution_env: dict[str, str] = Field(default_factory=dict, max_length=50)

    @field_validator("name", "bundle_ref", "target_receiver_id", mode="before")
    @classmethod
    def trim_labels(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("execution_env")
    @classmethod
    def bounded_env(cls, value: dict[str, str]) -> dict[str, str]:
        if len(json.dumps(value).encode()) > 16_384:
            raise ValueError("环境变量内容不得超过 16 KB")
        return value


class TemplateOut(TemplateInput):
    model_config = ConfigDict(from_attributes=True)
    template_id: str
    created_at: datetime
    updated_at: datetime


async def validate_references(s: AsyncSession, req: TemplateInput) -> None:
    try:
        name, version = parse_bundle_ref(req.bundle_ref)
    except ValueError as exc:
        raise HTTPException(422, "请选择已注册的任务包") from exc
    if await s.get(Bundle, (name, version)) is None:
        raise HTTPException(422, "任务包已不存在，请重新选择")
    if req.target_receiver_id and await s.get(Receiver, req.target_receiver_id) is None:
        raise HTTPException(422, "接收端已不存在，请重新选择")


async def save(s: AsyncSession, row: TaskTemplate) -> TemplateOut:
    try:
        await s.commit()
    except IntegrityError as exc:
        await s.rollback()
        raise HTTPException(409, "已有同名模板，请更换名称或更新原模板") from exc
    return TemplateOut.model_validate(row)


@router.get("", response_model=list[TemplateOut])
async def list_templates(s: AsyncSession = Depends(session)):
    return (
        await s.scalars(
            select(TaskTemplate).order_by(TaskTemplate.updated_at.desc(), TaskTemplate.template_id)
        )
    ).all()


@router.post("", response_model=TemplateOut, status_code=201)
async def create_template(req: TemplateInput, s: AsyncSession = Depends(session)):
    await validate_references(s, req)
    row = TaskTemplate(template_id=secrets.token_urlsafe(12), **req.model_dump())
    s.add(row)
    return await save(s, row)


@router.put("/{template_id}", response_model=TemplateOut)
async def update_template(template_id: str, req: TemplateInput, s: AsyncSession = Depends(session)):
    row = await get_or_404(s, TaskTemplate, template_id, "模板不存在")
    await validate_references(s, req)
    for key, value in req.model_dump().items():
        setattr(row, key, value)
    row.updated_at = utcnow()
    return await save(s, row)


@router.delete("/{template_id}")
async def delete_template(template_id: str, s: AsyncSession = Depends(session)):
    row = await get_or_404(s, TaskTemplate, template_id, "模板不存在")
    await s.delete(row)
    await s.commit()
    return {"ok": True}
