"""MIRROR for src/common/ducklake_tables.py (rec-2709 Wave 7).

Split out of the former tests/test_ducklake_runtime.py monolith: create_scd2_tables (partition
application, force-recreate drop-first, the ops-DDL real-types check, and the append_only
single-table variants) and reconcile_table_columns (append_only history-only ALTER).
"""

from __future__ import annotations

import pytest

from src.common import ducklake_runtime as rt
from tests.fixtures.ducklake_fakes import FakeCon

pytestmark = pytest.mark.unit


def test_create_scd2_tables_applies_partitions():
    con = FakeCon()
    rt.create_scd2_tables(con)
    sqls = [s for s, _ in con.executed]
    assert any("SET PARTITIONED BY (day(created_timestamp))" in s for s in sqls)
    assert any("SET PARTITIONED BY (bucket(8, rec_id))" in s for s in sqls)
    assert not any(s.startswith("DROP TABLE") for s in sqls)


def test_create_scd2_tables_force_recreate_drops_first():
    con = FakeCon()
    rt.create_scd2_tables(con, force_recreate=True)
    sqls = [s for s, _ in con.executed]
    drops = [i for i, s in enumerate(sqls) if s.startswith("DROP TABLE")]
    creates = [i for i, s in enumerate(sqls) if s.startswith("CREATE TABLE")]
    assert len(drops) == 2
    assert min(drops) < min(creates)  # drops precede creates


def test_create_scd2_tables_ops_ddl_has_real_types(monkeypatch):
    con = FakeCon()
    rt.create_scd2_tables(con, table="ops_decisions", force_recreate=True)
    ddl = [sql for sql, _ in con.executed if sql.startswith("CREATE TABLE")]
    assert any("ops_decisions_history" in s for s in ddl)
    assert any("related_decisions BIGINT[]" in s for s in ddl)
    assert any("decision_id BIGINT" in s for s in ddl)
    # partition ALTERs applied before first write
    alters = [sql for sql, _ in con.executed if "SET PARTITIONED BY" in sql]
    assert any("bucket(8, id)" in s for s in alters)


def test_create_scd2_tables_append_only_single_table():
    """create_scd2_tables for an append_only table creates only the history table."""
    con = FakeCon()
    rt.create_scd2_tables(con, table="ops_smoke_events")
    sql_stmts = [sql for sql, _ in con.executed]
    creates = [s for s in sql_stmts if s.startswith("CREATE TABLE")]
    alters = [s for s in sql_stmts if "SET PARTITIONED BY" in s]
    assert len(creates) == 1
    assert "ops_smoke_events_history" in creates[0]
    assert len(alters) == 1
    assert "ops_smoke_events_history" in alters[0]
    assert not any("ops_smoke_events_current" in s for s in sql_stmts)


def test_create_scd2_tables_append_only_force_recreate_single_drop():
    """force_recreate on an append_only table drops only the history table."""
    con = FakeCon()
    rt.create_scd2_tables(con, table="ops_smoke_events", force_recreate=True)
    sql_stmts = [sql for sql, _ in con.executed]
    drops = [s for s in sql_stmts if s.startswith("DROP TABLE")]
    assert len(drops) == 1
    assert "ops_smoke_events_history" in drops[0]
    assert not any("ops_smoke_events_current" in s for s in sql_stmts)


def test_reconcile_table_columns_append_only_history_only():
    """reconcile_table_columns for append_only tables issues ALTER TABLE only on history; added_current is empty."""
    con = FakeCon()
    result = rt.reconcile_table_columns(con, table="ops_smoke_events")
    alters = [sql for sql, _ in con.executed if sql.startswith("ALTER TABLE") and "ADD COLUMN" in sql]
    assert all("_history" in sql for sql in alters), f"All ALTERs must target history table; got: {alters}"
    assert not any("_current" in sql for sql in alters), "No ALTER should target a current table"
    assert result["added_current"] == [], "added_current must be empty for append_only tables"
