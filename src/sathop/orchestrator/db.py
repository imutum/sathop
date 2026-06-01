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
    select,
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
    paused: Mapped[bool] = mapped_column(Boolean, default=False)
    # Operator concurrency overrides; None = use the worker's env default.
    download_concurrency: Mapped[int | None] = mapped_column(Integer, nullable=True)
    process_concurrency: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Live applied concurrency reported by the worker heartbeat.
    live_download_concurrency: Mapped[int | None] = mapped_column(Integer, nullable=True)
    live_process_concurrency: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ca_pem: Mapped[str | None] = mapped_column(Text, nullable=True)
    # One-shot "update" signal (was "restart"). SQL column keeps old name for
    # back-compat with existing DBs; Python attr is the canonical name.
    update_requested_at: Mapped[datetime | None] = mapped_column(
        "restart_requested_at", UtcDateTime(), nullable=True
    )
    # Target version for a coordinated upgrade. Set alongside update_requested_at
    # when the operator picks a version (None = plain same-version restart). The
    # next heartbeat hands it to the worker, which stamps its own .pending-version
    # before draining so the entrypoint installs that release. Nullable so
    # _ensure_columns can ALTER existing DBs.
    update_to_version: Mapped[str | None] = mapped_column(String, nullable=True)
    # Operator-set persistent pause flag. SQL column keeps old name for back-compat.
    operator_paused: Mapped[bool | None] = mapped_column(
        "pause_requested", Boolean, default=False, nullable=True
    )
    gc_requested_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    removed_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)


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


class Rollout(Base):
    """A staged fleet upgrade (L2). One active rollout at a time; the background
    leader advances it canary→batch→fleet, gated purely by version-confirmed
    liveness (a wave completes when its frozen member cohort all report
    version==target; a wave that times out HALTs — per-node crash rollback is
    L1's job, the orchestrator never rolls a fleet back). State is wholly on this
    row so it survives multi-process Postgres + orch restart; the worker contract
    is untouched (each wave reuses the existing per-worker update one-shot)."""

    __tablename__ = "rollouts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String, default="worker")  # reserved for future receiver rollouts
    target_version: Mapped[str] = mapped_column(String)
    channel: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # display: channel resolved, None=concrete
    # pending → running → (done | halted → running… | aborted)
    phase: Mapped[str] = mapped_column(String, default="pending")
    wave_index: Mapped[int] = mapped_column(Integer, default=-1)  # -1 pending, 0 canary, 1 batch, 2 fleet
    wave_member_ids: Mapped[list] = mapped_column(JSON, default=list)  # frozen cohort for the current wave
    wave_started_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    wave_deadline_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    canary_count: Mapped[int] = mapped_column(Integer, default=1)
    batch_pct: Mapped[float] = mapped_column(Float, default=0.25)
    wave_timeout_sec: Mapped[int] = mapped_column(Integer, default=600)
    halt_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_by: Mapped[str | None] = mapped_column(String, nullable=True)
    started_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)


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
    # Persistent cumulative-delivered counter (= rows that reached state=deleted).
    # Replaces COUNTing deleted granules on the read path. Incremented once per
    # DeleteConfirmed (guarded against re-sends). Nullable so _ensure_columns can
    # ALTER existing DBs; read sites coalesce NULL->0.
    delivered_count: Mapped[int] = mapped_column(Integer, default=0, nullable=True)


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
# Serves the stuck query: WHERE state IN(...) AND updated_at < threshold.
Index("idx_granule_state_updated", Granule.state, Granule.updated_at)
# Covering partial index for the dashboard/metrics per-state GROUP BY
# (admin_readmodels.admin_overview + metrics._collect run
# `SELECT state, count(granule_id) WHERE state != 'deleted' GROUP BY state`).
# INCLUDE(granule_id) + the matching partial predicate lets Postgres answer it
# with an Index-Only Scan over just the live rows — no heap visit and no scan of
# the huge terminal `deleted` rows — dropping the query from a ~1.1s parallel seq
# scan of the 1.4GB heap to tens of ms (needs a current visibility map, i.e. a
# healthy autovacuum). SQLite ignores the postgresql_* kwargs and uses the
# sqlite_where partial. Mirrors the idx_granule_objects_pending pattern below.
Index(
    "idx_granule_state_live_cov",
    Granule.state,
    postgresql_include=["granule_id"],
    postgresql_where=Granule.state != "deleted",
    sqlite_where=Granule.state != "deleted",
)


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


# Partial index over only *pending* objects (not yet acked, not yet deleted).
# The exhausted-by-batch / pullable / deletable read paths all filter on this
# predicate, but acked+deleted rows accumulate unboundedly with delivered volume
# (600k+ on a long-running batch) — a full-table index would still walk them.
# Indexing only the handful of live objects turns those scans from O(delivered)
# into O(in-flight). SQLite picks it only once stats exist, so init runs
# `PRAGMA optimize` after ensuring indexes.
Index(
    "idx_granule_objects_pending",
    GranuleObject.granule_id,
    sqlite_where=GranuleObject.acked_at.is_(None) & GranuleObject.deleted_at.is_(None),
    postgresql_where=GranuleObject.acked_at.is_(None) & GranuleObject.deleted_at.is_(None),
)


class Event(Base):
    """Display-only audit feed. In Postgres (multi-process) mode events are
    written here transactionally with the transition that emits them (so a
    rolled-back txn discards its events) and read back via async SELECTs; in
    SQLite mode this table is unused and the feed lives in an in-memory deque
    (see event_store.py). granule_id/batch_id are plain nullable columns (NOT
    ForeignKeys) on purpose: an event outlives the granule/batch it references,
    and eviction is an explicit sweep, not a cascade — this also keeps the row
    free of flush-ordering constraints when staged alongside other ORM inserts."""

    __tablename__ = "events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow, index=True)
    level: Mapped[str] = mapped_column(String, default="info")
    source: Mapped[str] = mapped_column(String)
    granule_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    batch_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
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
# Kills system_delivery_rate's full scan: WHERE stage='deliver' AND finished_at>=cutoff.
Index("idx_stage_timing_stage_finished", GranuleStageTiming.stage, GranuleStageTiming.finished_at)


_engine = None
_session_maker: async_sessionmaker[AsyncSession] | None = None


def is_postgres() -> bool:
    """True when a Postgres URL is configured (multi-process mode); else SQLite
    (single-process MVP default)."""
    return settings.database_url.startswith(("postgresql", "postgres"))


def not_in_paused_batch():
    """SQL filter: Granule rows whose batch is NOT paused. Shared by the lease
    claim and the stuck-granule reads — a paused batch's held PENDING granules
    must be both unclaimable AND not flagged 'stuck' (they're intentionally held,
    not stalled). A plain read subquery over the tiny batches table; it locks
    nothing, so the claim's FOR UPDATE SKIP LOCKED still contends only on
    granule rows."""
    return Granule.batch_id.not_in(select(Batch.batch_id).where(Batch.status == "paused"))


def _url() -> str:
    if settings.database_url:
        return settings.database_url
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite+aiosqlite:///{settings.db_path.as_posix()}"


def _set_sqlite_pragmas(dbapi_connection, connection_record) -> None:
    dbapi_connection.execute("PRAGMA journal_mode=WAL")
    dbapi_connection.execute("PRAGMA synchronous=OFF")
    dbapi_connection.execute("PRAGMA busy_timeout=5000")
    dbapi_connection.execute("PRAGMA wal_autocheckpoint=1000")


# Arbitrary fixed key for the schema-init advisory lock (Postgres only): serialises
# the create/ensure_columns/ensure_indexes reconciliation across the N worker
# processes that all run lifespan on boot, so concurrent ALTER TABLEs can't race.
_SCHEMA_LOCK_KEY = 0x5A7409


def _engine_kwargs(pg: bool) -> dict:
    """create_async_engine kwargs. The SQLite (single-process MVP) path stays
    byte-identical; the Postgres (multi-process) path adds two CPU/contention
    levers that only matter once N processes hammer one server:
      • jit=off — PG16 defaults jit=on and LLVM-compiles the lease
        `FOR UPDATE SKIP LOCKED` subquery and the bulk `granule_id IN (...)`
        statements on every call; fired thousands/sec that is pure repeated
        planning CPU burned on the single bottleneck core. Off is the textbook
        OLTP setting and is the one lever that also helps the *un-batchable*
        lease/heartbeat handlers the batch endpoints can't touch.
      • a bounded, pre-pinged pool — keeps total backends well under PG's
        max_connections across the N orchestrator processes (each also holds a
        few raw asyncpg connections for LISTEN / NOTIFY-sender / leader);
        pool_pre_ping + pool_recycle survive a Postgres restart without handing
        out a dead connection. Defaults match SQLAlchemy's async pool but are
        pinned explicitly so the per-process backend budget is auditable."""
    kw: dict = {"echo": False, "future": True}
    if pg:
        kw["connect_args"] = {"server_settings": {"jit": "off"}}
        kw["pool_size"] = 5
        kw["max_overflow"] = 10
        kw["pool_pre_ping"] = True
        kw["pool_recycle"] = 1800
    return kw


async def init_db() -> None:
    global _engine, _session_maker
    pg = is_postgres()
    _engine = create_async_engine(_url(), **_engine_kwargs(pg))
    if not pg:
        event.listen(_engine.sync_engine, "connect", _set_sqlite_pragmas)
    _session_maker = async_sessionmaker(_engine, expire_on_commit=False)
    async with _engine.begin() as conn:
        if pg:
            # Hold a transaction-scoped advisory lock so only one process runs the
            # schema reconciliation at a time (released at txn end).
            await conn.exec_driver_sql(f"SELECT pg_advisory_xact_lock({_SCHEMA_LOCK_KEY})")
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_ensure_columns)
        await conn.run_sync(_ensure_indexes)
        await conn.run_sync(_drop_obsolete_tables)
        if pg:
            await conn.run_sync(_ensure_pg_table_tuning)
        if not pg:
            # Refresh planner stats so the partial idx_granule_objects_pending is
            # actually chosen — SQLite ignores an index with no sqlite_stat1 row.
            # `optimize` is the cheap changed-tables-only form. Postgres autovacuum
            # handles its own stats.
            await conn.exec_driver_sql("PRAGMA optimize")


def _ensure_columns(sync_conn) -> None:
    """Reconcile each model table with the live schema: ADD columns the model
    declares but the table lacks, and DROP columns the table still has but the
    model removed. The drop half matters because a leftover NOT NULL column
    (e.g. ``workers.enabled``, dropped in the lifecycle redesign) makes every
    INSERT that omits it fail — new workers could no longer register. Type
    changes still need a real migration tool; added columns are nullable, so
    reading code should treat NULL as the model default."""
    from sqlalchemy import inspect as sa_inspect
    from sqlalchemy import text

    log = logging.getLogger("sathop.orchestrator.db")
    insp = sa_inspect(sync_conn)
    for table_name, table in Base.metadata.tables.items():
        if table_name not in insp.get_table_names():
            continue
        existing = {c["name"] for c in insp.get_columns(table_name)}
        model_cols = {c.name for c in table.columns}
        for col in table.columns:
            if col.name in existing:
                continue
            col_type = col.type.compile(sync_conn.dialect)
            try:
                sync_conn.execute(text(f'ALTER TABLE "{table_name}" ADD COLUMN "{col.name}" {col_type}'))
                if table_name == "batches" and col.name == "delivered_count":
                    # One-shot backfill: the cumulative-delivered counter only
                    # exists from this column on, so seed it from the live deleted
                    # rows the first (and only) boot the column is created.
                    sync_conn.execute(
                        text(
                            "UPDATE batches SET delivered_count = (SELECT COUNT(*) FROM granules "
                            "WHERE granules.batch_id = batches.batch_id AND granules.state = 'deleted')"
                        )
                    )
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
        for name in existing - model_cols:
            try:
                sync_conn.execute(text(f'ALTER TABLE "{table_name}" DROP COLUMN "{name}"'))
                log.info("dropped obsolete column %s.%s", table_name, name)
            except Exception:
                # A leftover NOT NULL column still blocks inserts, but a failed
                # drop shouldn't crash-loop the orchestrator — surface it so the
                # operator can drop it by hand.
                log.exception("failed to drop obsolete column %s.%s", table_name, name)


def _ensure_indexes(sync_conn) -> None:
    """create_all only builds a table's indexes when it also CREATEs that table,
    so an index added to an already-existing table never materialises. Reconcile
    every declared index with checkfirst (idempotent) — the index-grain twin of
    _ensure_columns — so new indexes land on live DBs too, not just fresh ones."""
    log = logging.getLogger("sathop.orchestrator.db")
    for table in Base.metadata.tables.values():
        for index in table.indexes:
            try:
                index.create(sync_conn, checkfirst=True)
            except Exception:
                log.exception("failed to ensure index %s", index.name)


# Tables the model no longer declares but old DBs still carry. Listed
# explicitly (not "any table absent from metadata") because the orchestrator
# owns the whole DB and a typo'd __tablename__ must not silently drop live data.
#   granule_progress — progress went fully in-memory (see api/progress.py); the
#   table was inert but accumulated dead rows after delete_batch stopped touching it.
_OBSOLETE_TABLES = ("granule_progress",)


def _drop_obsolete_tables(sync_conn) -> None:
    """Drop whole tables the model retired, mirroring the column-drop half of
    `_ensure_columns` at the table grain. A leftover table is inert, so a failed
    drop is logged, not fatal."""
    from sqlalchemy import inspect as sa_inspect
    from sqlalchemy import text

    log = logging.getLogger("sathop.orchestrator.db")
    present = set(sa_inspect(sync_conn).get_table_names())
    for name in _OBSOLETE_TABLES:
        if name not in present:
            continue
        try:
            sync_conn.execute(text(f'DROP TABLE "{name}"'))
            log.info("dropped obsolete table %s", name)
        except Exception:
            log.exception("failed to drop obsolete table %s", name)


# Per-table storage + autovacuum tuning for the high-churn hot tables (Postgres
# only). This is the code-resident form of the emergency mitigation applied BY
# HAND during the 2026-06-01 meltdown and observed to stabilise dead tuples
# (batches ~53 / granules ~970 steady-state afterward): a long
# idle-in-transaction leader had pinned the xmin horizon, autovacuum could
# reclaim nothing, and the handful of red-hot `batches` rows (delivered_count++
# on every delivery) bloated into a tuple-chain deadlock storm. The hand-applied
# reloptions did NOT survive a redeploy / fresh-PG migration; pinning them here
# means every boot re-asserts them idempotently via `ALTER TABLE ... SET`.
#   - small, extremely hot rows (heartbeat telemetry, delivered_count, receiver
#     state): fillfactor leaves in-page room for HOT updates (these columns are
#     un-indexed -> HOT-eligible) and autovacuum fires on a tiny absolute count
#     instead of waiting for ~20% of the table to die.
#   - large high-churn tables: lower the scale factor so autovacuum keeps pace
#     with the state-transition UPDATE stream. NO fillfactor (the dominant UPDATE
#     touches the indexed `updated_at`, so the row can't go HOT, and rewriting a
#     multi-GB heap is not worth it) and cost_delay left at the PG default so a
#     big-table vacuum can't hog the shared box's cores away from the orch loop.
# Reloptions apply to FUTURE tuples only, so the pre-existing bloated tables
# still need a separately-scheduled one-time VACUUM FULL / pg_repack.
_PG_SMALL_HOT = (
    "fillfactor=70, autovacuum_vacuum_scale_factor=0.0, autovacuum_vacuum_threshold=100, "
    "autovacuum_analyze_scale_factor=0.0, autovacuum_analyze_threshold=100, autovacuum_vacuum_cost_delay=0"
)
_PG_BIG_HOT = (
    "autovacuum_vacuum_scale_factor=0.05, autovacuum_vacuum_threshold=5000, "
    "autovacuum_analyze_scale_factor=0.05, autovacuum_analyze_threshold=5000"
)
_PG_TABLE_TUNING = {
    "workers": _PG_SMALL_HOT,
    "batches": _PG_SMALL_HOT,
    "receivers": _PG_SMALL_HOT,
    "granules": _PG_BIG_HOT,
    "granule_objects": _PG_BIG_HOT,
}


def _ensure_pg_table_tuning(sync_conn) -> None:
    """Idempotently re-assert the per-table storage/autovacuum reloptions above.
    `ALTER TABLE ... SET (...)` is a catalog-only change (no table rewrite), runs
    under the boot schema advisory lock alongside the other reconciliation steps,
    and is safe to repeat on every boot. A failed SET is logged, not fatal — a
    missing reloption degrades to PG defaults, it doesn't break the orchestrator."""
    from sqlalchemy import inspect as sa_inspect
    from sqlalchemy import text

    log = logging.getLogger("sathop.orchestrator.db")
    present = set(sa_inspect(sync_conn).get_table_names())
    for table_name, opts in _PG_TABLE_TUNING.items():
        if table_name not in present:
            continue
        try:
            sync_conn.execute(text(f'ALTER TABLE "{table_name}" SET ({opts})'))
        except Exception:
            log.exception("failed to set storage tuning on %s", table_name)


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
