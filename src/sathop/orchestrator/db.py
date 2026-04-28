"""SQLite schema + async engine. Orchestrator owns all authoritative state."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, TypeDecorator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from .config import settings


def utcnow() -> datetime:
    return datetime.now(UTC)


class UtcDateTime(TypeDecorator):
    """DateTime column that always round-trips as UTC-aware.

    SQLite has no native timezone: SQLAlchemy writes an ISO string but reads
    back naive datetime. Browsers then parse the ISO-without-tz as local time
    and wall-clock ages come out offset (8h here). This decorator tags naive
    values with UTC on read so Pydantic/isoformat emit `+00:00` and UI code
    can just call `new Date()`."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value


class Base(DeclarativeBase):
    pass


class Worker(Base):
    __tablename__ = "workers"
    worker_id: Mapped[str] = mapped_column(String, primary_key=True)
    version: Mapped[str] = mapped_column(String, default="")
    capacity: Mapped[int] = mapped_column(Integer, default=20)
    public_url: Mapped[str | None] = mapped_column(String, nullable=True)
    last_seen: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)
    disk_used_gb: Mapped[float] = mapped_column(Float, default=0.0)
    disk_total_gb: Mapped[float] = mapped_column(Float, default=0.0)
    cpu_percent: Mapped[float] = mapped_column(Float, default=0.0)
    mem_percent: Mapped[float] = mapped_column(Float, default=0.0)
    monthly_egress_gb: Mapped[float] = mapped_column(Float, default=0.0)
    queue_downloading: Mapped[int] = mapped_column(Integer, default=0)
    queue_processing: Mapped[int] = mapped_column(Integer, default=0)
    queue_uploading: Mapped[int] = mapped_column(Integer, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # Runtime concurrency override; NULL ⇒ worker's env capacity. Rides heartbeat replies.
    desired_capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Receiver(Base):
    __tablename__ = "receivers"
    receiver_id: Mapped[str] = mapped_column(String, primary_key=True)
    version: Mapped[str] = mapped_column(String, default="")
    platform: Mapped[str] = mapped_column(String, default="linux")
    last_seen: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)
    disk_free_gb: Mapped[float] = mapped_column(Float, default=0.0)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class Batch(Base):
    __tablename__ = "batches"
    batch_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    bundle_ref: Mapped[str] = mapped_column(String)
    target_receiver_id: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="running")
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)
    # JSON-encoded dict of env overrides. Merged into the bundle's execution.env
    # at lease time (batch env > bundle env > worker os env).
    execution_env_json: Mapped[str] = mapped_column(Text, default="{}")
    # JSON-encoded {name: Credential} map. Included verbatim in every lease
    # item so workers can authenticate downloads without any orchestrator-side
    # credential registry.
    credentials_json: Mapped[str] = mapped_column(Text, default="{}")


class Granule(Base):
    __tablename__ = "granules"
    granule_id: Mapped[str] = mapped_column(String, primary_key=True)
    batch_id: Mapped[str] = mapped_column(String, ForeignKey("batches.batch_id"), index=True)
    state: Mapped[str] = mapped_column(String, index=True)
    inputs_json: Mapped[str] = mapped_column(Text)
    meta_json: Mapped[str] = mapped_column(Text, default="{}")
    leased_by: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)


Index("idx_granule_state_batch", Granule.state, Granule.batch_id)


class GranuleObject(Base):
    __tablename__ = "granule_objects"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    granule_id: Mapped[str] = mapped_column(String, ForeignKey("granules.granule_id"), index=True)
    worker_id: Mapped[str] = mapped_column(String, index=True)
    object_key: Mapped[str] = mapped_column(String)
    presigned_url: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String)
    size: Mapped[int] = mapped_column(Integer)
    uploaded_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)
    acked_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    acked_by: Mapped[str | None] = mapped_column(String, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)


class Event(Base):
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow, index=True)
    level: Mapped[str] = mapped_column(String, default="info")
    source: Mapped[str] = mapped_column(String)
    granule_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    message: Mapped[str] = mapped_column(Text)


class Bundle(Base):
    """Central bundle registry. Content-addressed blob at
    $SATHOP_BUNDLES_DIR/<sha256>.zip; workers fetch via
    GET /api/bundles/<name>/<version>/download."""

    __tablename__ = "bundles"
    name: Mapped[str] = mapped_column(String, primary_key=True)
    version: Mapped[str] = mapped_column(String, primary_key=True)
    sha256: Mapped[str] = mapped_column(String, index=True)
    size: Mapped[int] = mapped_column(Integer)
    manifest_json: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)


class SharedFile(Base):
    """Orchestrator-hosted shared file, referenced by bundles via the
    `shared_files: [name]` manifest field. Worker pulls + caches by sha256.
    Bytes live at $SATHOP_SHARED/<name> on orchestrator disk; DB row is the
    authoritative metadata (sha256, size, description)."""

    __tablename__ = "shared_files"
    name: Mapped[str] = mapped_column(String, primary_key=True)
    sha256: Mapped[str] = mapped_column(String)
    size: Mapped[int] = mapped_column(Integer)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)


class GranuleProgress(Base):
    """Bundle-reported checkpoint timeline, one row per reported step.
    batch_id is denormalized so batch-level queries don't have to join granules."""

    __tablename__ = "granule_progress"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    granule_id: Mapped[str] = mapped_column(String, ForeignKey("granules.granule_id"), index=True)
    batch_id: Mapped[str] = mapped_column(String, index=True)
    ts: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow, index=True)
    step: Mapped[str] = mapped_column(String)
    pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)


class GranuleStageTiming(Base):
    """Closed-stage durations: one row per granule per (download, process,
    upload) attempt. Inserted at the transition that closes each stage; failed
    attempts are not recorded (no incomplete rows). A retried granule produces
    multiple rows for the same stage — aggregations count attempts, not
    granules."""

    __tablename__ = "granule_stage_timing"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    granule_id: Mapped[str] = mapped_column(String, ForeignKey("granules.granule_id"), index=True)
    batch_id: Mapped[str] = mapped_column(String, index=True)
    stage: Mapped[str] = mapped_column(String)
    started_at: Mapped[datetime] = mapped_column(UtcDateTime())
    finished_at: Mapped[datetime] = mapped_column(UtcDateTime())
    duration_ms: Mapped[int] = mapped_column(Integer)


Index("idx_stage_timing_batch_stage", GranuleStageTiming.batch_id, GranuleStageTiming.stage)


_engine = None
_session_maker: async_sessionmaker[AsyncSession] | None = None


def _url() -> str:
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite+aiosqlite:///{settings.db_path.as_posix()}"


async def init_db() -> None:
    global _engine, _session_maker
    _engine = create_async_engine(_url(), echo=False, future=True)
    _session_maker = async_sessionmaker(_engine, expire_on_commit=False)
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_ensure_columns)


def _ensure_columns(sync_conn) -> None:
    """Add any columns declared on the model but missing on the live table.
    Only handles additive (new nullable) columns — drops and type changes need
    a real migration tool. Existing rows get NULL for the new column; reading
    code should treat NULL as the model default."""
    from sqlalchemy import inspect as sa_inspect
    from sqlalchemy import text

    insp = sa_inspect(sync_conn)
    for table_name, table in Base.metadata.tables.items():
        if table_name not in insp.get_table_names():
            continue
        existing = {c["name"] for c in insp.get_columns(table_name)}
        for col in table.columns:
            if col.name in existing:
                continue
            col_type = col.type.compile(sync_conn.dialect)
            sync_conn.execute(text(f'ALTER TABLE "{table_name}" ADD COLUMN "{col.name}" {col_type}'))


async def shutdown_db() -> None:
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None


async def session() -> AsyncIterator[AsyncSession]:
    assert _session_maker is not None, "init_db() not called"
    async with _session_maker() as s:
        yield s
