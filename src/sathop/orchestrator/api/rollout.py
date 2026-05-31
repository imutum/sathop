"""Staged fleet rollout (L2) operator endpoints. The leader (background.run_rollout)
does all the actual wave advancement; these handlers only seed / inspect / abort /
resume the single active rollout row. Worker-only for now (receivers have no
versioned-update channel — hard fact #4)."""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sathop import __version__
from sathop.shared.release import normalize_version
from sathop.shared.state_machine import Scope
from sathop.shared.versioning import parse_version

from ..background import _WAVE_LABELS, rollout_member_breakdown
from ..config import require_token, settings
from ..db import Rollout, Worker, session, utcnow
from ..pubsub import commit_and_publish
from ..pubsub import log_event as log
from . import admin

router = APIRouter(prefix="/admin/rollout", tags=["rollout"], dependencies=[Depends(require_token)])

_ACTIVE = ("pending", "running", "halted")


class RolloutStart(BaseModel):
    target_version: str | None = None  # explicit version wins; else resolve `channel`
    channel: str | None = None  # stable|edge (defaults to SATHOP_CHANNEL)
    canary_count: int | None = None
    batch_pct: float | None = None
    wave_timeout_sec: int | None = None


class RolloutMemberCounts(BaseModel):
    confirmed: int = 0
    pending: int = 0
    excused: int = 0


class RolloutStatus(BaseModel):
    active: bool
    id: int | None = None
    target_version: str | None = None
    channel: str | None = None
    phase: str | None = None  # pending|running|halted|done|aborted
    wave: str | None = None  # canary|batch|fleet
    wave_index: int | None = None
    members: RolloutMemberCounts | None = None
    pending_ids: list[str] = []
    wave_deadline_at: datetime | None = None
    halt_reason: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


def _status(r: Rollout, confirmed: list[str], pending: list[str], excused: list[str]) -> RolloutStatus:
    label = _WAVE_LABELS[r.wave_index] if 0 <= r.wave_index < len(_WAVE_LABELS) else None
    return RolloutStatus(
        active=r.phase in _ACTIVE,
        id=r.id,
        target_version=r.target_version,
        channel=r.channel,
        phase=r.phase,
        wave=label,
        wave_index=r.wave_index,
        members=RolloutMemberCounts(confirmed=len(confirmed), pending=len(pending), excused=len(excused)),
        pending_ids=pending,
        wave_deadline_at=r.wave_deadline_at,
        halt_reason=r.halt_reason,
        started_at=r.started_at,
        finished_at=r.finished_at,
    )


async def _active_rollout(s: AsyncSession) -> Rollout | None:
    return await s.scalar(
        select(Rollout).where(Rollout.phase.in_(_ACTIVE)).order_by(Rollout.id.desc()).limit(1)
    )


@router.post("")
async def start_rollout(body: RolloutStart, s: AsyncSession = Depends(session)) -> RolloutStatus:
    if await _active_rollout(s) is not None:
        raise HTTPException(409, "a rollout is already in progress; abort it first")

    # Resolve the concrete target: an explicit version wins, else resolve a channel.
    if body.target_version:
        try:
            target = normalize_version(body.target_version)
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        channel = None
    else:
        channel = admin._normalize_channel(body.channel or settings.channel)
        try:
            data = await admin._fetch_latest_release(channel)
        except Exception as e:
            raise HTTPException(502, f"could not resolve the {channel} channel: {e}")
        try:
            target = normalize_version(data.get("tag") or "")
        except ValueError:
            raise HTTPException(502, f"the {channel} channel has no usable release (got {data.get('tag')!r})")

    # orch-before-worker: never roll workers to a version the orchestrator isn't on yet.
    if parse_version(target) > parse_version(__version__):
        raise HTTPException(
            409, f"orchestrator is on v{__version__}; upgrade it to v{target} before rolling out workers"
        )

    # Fail fast on an undownloadable release (shared with POST /api/admin/upgrade).
    await admin.head_release_asset(target)

    r = Rollout(
        target_version=target,
        channel=channel,
        phase="pending",
        wave_index=-1,
        canary_count=body.canary_count or settings.rollout_canary_count,
        batch_pct=settings.rollout_batch_pct if body.batch_pct is None else body.batch_pct,
        wave_timeout_sec=body.wave_timeout_sec or settings.rollout_wave_timeout_sec,
        started_by="ui",
    )
    s.add(r)
    await log(
        s,
        "operator",
        f"rollout to v{target} started (canary={r.canary_count}, batch_pct={r.batch_pct}, "
        f"timeout={r.wave_timeout_sec}s)",
    )
    await commit_and_publish(s, Scope.ROLLOUT)
    await s.refresh(r)
    return _status(r, [], [], [])


@router.get("")
async def rollout_status(s: AsyncSession = Depends(session)) -> RolloutStatus:
    r = await s.scalar(select(Rollout).order_by(Rollout.id.desc()).limit(1))
    if r is None:
        return RolloutStatus(active=False)
    confirmed, pending, excused = await rollout_member_breakdown(s, r)
    return _status(r, confirmed, pending, excused)


@router.post("/abort")
async def abort_rollout(s: AsyncSession = Depends(session)) -> RolloutStatus:
    r = await _active_rollout(s)
    if r is None:
        raise HTTPException(404, "no active rollout to abort")
    now = utcnow()
    r.phase, r.finished_at, r.updated_at = "aborted", now, now
    await log(s, "operator", f"rollout v{r.target_version} aborted via UI", level="warn")
    await commit_and_publish(s, Scope.ROLLOUT)
    confirmed, pending, excused = await rollout_member_breakdown(s, r)
    return _status(r, confirmed, pending, excused)


@router.post("/resume")
async def resume_rollout(s: AsyncSession = Depends(session)) -> RolloutStatus:
    """Resume a HALTed rollout: re-stamp the still-pending members (retry the
    signal) and extend the wave deadline. The leader takes it from there."""
    r = await s.scalar(select(Rollout).where(Rollout.phase == "halted").order_by(Rollout.id.desc()).limit(1))
    if r is None:
        raise HTTPException(404, "no halted rollout to resume")
    now = utcnow()
    confirmed, pending, excused = await rollout_member_breakdown(s, r)
    if pending:
        rows = (await s.execute(select(Worker).where(Worker.worker_id.in_(pending)))).scalars().all()
        for w in rows:
            w.update_requested_at = now
            w.update_to_version = r.target_version
    r.phase = "running"
    r.wave_deadline_at = now + timedelta(seconds=r.wave_timeout_sec)
    r.halt_reason = None
    r.updated_at = now
    await log(s, "operator", f"rollout v{r.target_version} resumed ({len(pending)} pending re-stamped)")
    await commit_and_publish(s, Scope.WORKERS, Scope.ROLLOUT)
    return _status(r, confirmed, pending, excused)
