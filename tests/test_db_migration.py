"""_ensure_columns reconciles legacy schemas: adds new model columns and drops
obsolete ones. Regression for the lifecycle redesign removing Worker.enabled —
the leftover NOT NULL `enabled` on existing DBs made every new-worker INSERT
fail (register 500), since the new model omits that column."""

from __future__ import annotations

import sqlite3

from sqlalchemy import create_engine, insert, inspect, text

from sathop.orchestrator.db import Base, Worker, _ensure_columns


def test_ensure_columns_drops_obsolete_not_null_column(tmp_path):
    db = tmp_path / "legacy.db"
    # Pre-redesign workers table: NOT NULL `enabled` with no server default —
    # exactly how SQLAlchemy's client-side default=True compiled the DDL.
    raw = sqlite3.connect(str(db))
    raw.execute("CREATE TABLE workers (worker_id TEXT PRIMARY KEY, version TEXT, enabled BOOLEAN NOT NULL)")
    raw.commit()
    raw.close()

    engine = create_engine(f"sqlite:///{db}")
    try:
        with engine.begin() as conn:
            Base.metadata.create_all(conn)  # creates sibling tables; workers already exists
            _ensure_columns(conn)
            cols = {c["name"] for c in inspect(conn).get_columns("workers")}

        assert "enabled" not in cols, "obsolete NOT NULL column must be dropped"
        assert "removed_at" in cols, "additive migration must still run"

        # A fresh registration INSERT (model has no `enabled`) now succeeds.
        with engine.begin() as conn:
            conn.execute(insert(Worker).values(worker_id="w1", version="0.6.6", capacity=4))
            assert conn.execute(text("SELECT count(*) FROM workers")).scalar() == 1
    finally:
        engine.dispose()
