"""SQLite schema + async engine. Orchestrator owns all authoritative state."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    TypeDecorator,
    event,
)
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
    # 6 个 worker-side 阶段计数。命名跟 worker.stages 快照一一对应。
    # 全部 nullable 以便 _ensure_columns 给老 DB 加列时旧行能保持 NULL；
    # 读端 `or 0` 兜底。
    queue_pending_download: Mapped[int | None] = mapped_column(Integer, default=0, nullable=True)
    queue_downloading: Mapped[int] = mapped_column(Integer, default=0)
    queue_pending_processing: Mapped[int | None] = mapped_column(Integer, default=0, nullable=True)
    queue_processing: Mapped[int] = mapped_column(Integer, default=0)
    # Upload semaphore wait counter (added v0.4.3). Nullable so _ensure_columns
    # can ALTER TABLE on existing DBs and old rows read as NULL.
    queue_pending_upload: Mapped[int | None] = mapped_column(Integer, default=0, nullable=True)
    queue_uploading: Mapped[int] = mapped_column(Integer, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # Worker self-reports True while it's gating off leases (disk pressure today).
    # Display-only — actual lease gating happens worker-side.
    paused: Mapped[bool] = mapped_column(Boolean, default=False)
    # Runtime concurrency override; NULL ⇒ worker's env capacity. Rides heartbeat replies.
    desired_capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Self-signed root CA (PEM) the worker uploaded at register time; aggregated
    # into /api/receivers/ca-bundle so receivers can pin trust without skip_verify.
    # NULL for workers without a self-signed front (publicly-trusted or HTTP).
    ca_pem: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Operator-clicked "重启" timestamp; consumed (cleared) on the next heartbeat
    # which then returns restart_requested=True to the worker. NULL ⇒ no pending
    # restart. One-shot — a re-click after the heartbeat consumed it sets a new ts.
    restart_requested_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    # Operator-set persistent pause flag — distinct from `paused` (which the
    # worker self-reports as the aggregate "not accepting leases for any
    # reason"). True ⇒ heartbeat reply tells the worker to stop accepting new
    # leases until the operator clears it. SQL column is still named
    # `pause_requested` for back-compat with existing DBs (no rename
    # migration); the Python attribute is `operator_paused` to make the
    # WHO-set-this-pause direction obvious at the call sites.
    # Nullable so _ensure_columns can ALTER TABLE on existing DBs; readers
    # coerce NULL → False.
    operator_paused: Mapped[bool | None] = mapped_column(
        "pause_requested", Boolean, default=False, nullable=True
    )
    # Operator-clicked "立即清理缓存" timestamp; one-shot, mirrors restart_requested_at.
    gc_requested_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)


class Receiver(Base):
    __tablename__ = "receivers"
    receiver_id: Mapped[str] = mapped_column(String, primary_key=True)
    version: Mapped[str] = mapped_column(String, default="")
    platform: Mapped[str] = mapped_column(String, default="linux")
    last_seen: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)
    disk_free_gb: Mapped[float] = mapped_column(Float, default=0.0)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # Latest heartbeat samples (overwritten each beat). Nullable so receivers
    # running an older protocol still register cleanly via _ensure_columns.
    queue_pulling: Mapped[int | None] = mapped_column(Integer, default=0, nullable=True)
    recent_pull_bps: Mapped[int | None] = mapped_column(Integer, default=0, nullable=True)
    # See Worker.restart_requested_at.
    restart_requested_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)


class Batch(Base):
    __tablename__ = "batches"
    batch_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    bundle_ref: Mapped[str] = mapped_column(String)
    target_receiver_id: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="running")
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)
    # Dict of env overrides. Merged into the bundle's execution.env at lease
    # time (batch env > bundle env > worker os env). Column kept as
    # `execution_env_json` for back-compat with existing DBs; Python attr drops
    # the suffix because the value is a dict, not a JSON string.
    execution_env: Mapped[dict] = mapped_column("execution_env_json", JSON, default=dict)
    # {name: Credential.model_dump()} map. Included verbatim in every lease item
    # so workers can authenticate downloads without any orchestrator-side
    # credential registry. Column kept as `credentials_json` for back-compat.
    credentials: Mapped[dict] = mapped_column("credentials_json", JSON, default=dict)


class Granule(Base):
    __tablename__ = "granules"
    granule_id: Mapped[str] = mapped_column(String, primary_key=True)
    batch_id: Mapped[str] = mapped_column(String, ForeignKey("batches.batch_id"), index=True)
    state: Mapped[str] = mapped_column(String, index=True)
    # List of InputSpec.model_dump() dicts; dict of per-granule meta key/values.
    # Columns kept as `inputs_json` / `meta_json` for back-compat with existing
    # DBs; Python attrs drop the suffix because the values are list/dict.
    inputs: Mapped[list] = mapped_column("inputs_json", JSON)
    meta: Mapped[dict] = mapped_column("meta_json", JSON, default=dict)
    leased_by: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Last-attempt bundle subprocess output tails. Populated by ProcessingFailed event;
    # cleared by the orchestrator when a granule transitions to UPLOADED so old
    # tails don't linger past the success that overrode them. Nullable so
    # _ensure_columns can ALTER TABLE ADD on existing DBs cleanly.
    stdout_tail: Mapped[str | None] = mapped_column(Text, nullable=True)
    stderr_tail: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    # Receiver pull-attempt failure counter; objects past max_pull_failures stop
    # being offered (otherwise a permanently-broken URL spins receivers forever).
    # Nullable for forward-compat: rows pre-dating this column read as NULL,
    # which we coalesce to 0 in the pull/ack handlers.
    failed_pulls: Mapped[int | None] = mapped_column(Integer, default=0, nullable=True)


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
    # Full parsed manifest dict (the same shape `shared/bundle_manifest.py`
    # produces). Column kept as `manifest_json` for back-compat.
    manifest: Mapped[dict] = mapped_column("manifest_json", JSON)
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


def _set_sqlite_pragmas(dbapi_connection, connection_record) -> None:
    dbapi_connection.execute("PRAGMA journal_mode=WAL")
    dbapi_connection.execute("PRAGMA synchronous=NORMAL")
    dbapi_connection.execute("PRAGMA busy_timeout=5000")


async def init_db() -> None:
    global _engine, _session_maker
    _engine = create_async_engine(_url(), echo=False, future=True)
    event.listen(_engine.sync_engine, "connect", _set_sqlite_pragmas)
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

    log = logging.getLogger("sathop.orchestrator.db")
    insp = sa_inspect(sync_conn)
    for table_name, table in Base.metadata.tables.items():
        if table_name not in insp.get_table_names():
            continue
        existing = {c["name"] for c in insp.get_columns(table_name)}
        for col in table.columns:
            if col.name in existing:
                continue
            col_type = col.type.compile(sync_conn.dialect)
            try:
                sync_conn.execute(text(f'ALTER TABLE "{table_name}" ADD COLUMN "{col.name}" {col_type}'))
            except Exception as e:
                # Surface table/column/type so the operator can pinpoint which
                # additive migration failed instead of a bare DB error spinning
                # the container in a crash loop.
                log.exception(
                    "migration failed: ALTER TABLE %s ADD COLUMN %s %s", table_name, col.name, col_type
                )
                raise RuntimeError(
                    f"failed to add column {col.name!r} ({col_type}) to table {table_name!r}: {e}"
                ) from e


async def shutdown_db() -> None:
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None


def get_session_maker() -> async_sessionmaker[AsyncSession]:
    """Return the live session maker; raise if init_db() has not run.
    Used by background sweepers and the FastAPI session() dependency — the
    explicit raise survives `python -O` (unlike `assert`)."""
    if _session_maker is None:
        raise RuntimeError("init_db() not called")
    return _session_maker


async def session() -> AsyncIterator[AsyncSession]:
    async with get_session_maker()() as s:
        yield s
