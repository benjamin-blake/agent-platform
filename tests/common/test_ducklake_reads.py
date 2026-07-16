"""MIRROR for src/common/ducklake_reads.py (rec-2709 Wave 7).

Split out of the former tests/test_ducklake_runtime.py monolith: read_current (smoke + ops-table
projection/filter, including the structural key_column filter with the NamedReadCon test double),
read_history, assert_read_only_sql (the closed-boundary read-only verb guard), named_read (the
NAMED_READS registry dispatch), and query_current -- plus the append_only read_current/
query_current loud-fail guards.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.common import ducklake_runtime as rt
from tests.fixtures.ducklake_fakes import FakeCon

pytestmark = pytest.mark.unit


class NamedReadCon:
    def __init__(self, rows=None, cols=("id",)):
        self.executed: list[tuple[str, list | None]] = []
        self._rows = rows or []
        self.description = [(c,) for c in cols]

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        return self

    def fetchall(self):
        return self._rows


def test_read_current_all():
    rows = [("01A", "rec-1", "p", datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 1, 1, tzinfo=timezone.utc))]
    con = FakeCon(read_rows=rows)
    out = rt.read_current(con)
    assert out[0]["rec_id"] == "rec-1"
    assert out[0]["ulid"] == "01A"


def test_read_current_by_rec_id():
    con = FakeCon(read_rows=[])
    rt.read_current(con, rec_id="rec-1")
    sql = con.executed[-1][0]
    assert "WHERE rec_id = ?" in sql
    assert con.executed[-1][1] == ["rec-1"]


def test_read_current_with_limit():
    con = FakeCon(read_rows=[])
    rt.read_current(con, limit=5)
    assert "LIMIT 5" in con.executed[-1][0]


def test_read_current_ops_table_projects_and_filters():
    """read_current(table=...) selects the ops column set and filters on the merge key."""
    rows = [("01U", "rec-1", "open")]

    class _Cur:
        description = [("ulid",), ("id",), ("status",)]

        def __init__(self):
            self.sql = ""
            self.params = None

        def execute(self, sql, params=None):
            self.sql = sql
            self.params = params
            return self

        def fetchall(self):
            return rows

    con = _Cur()
    out = rt.read_current(con, table="ops_recommendations", key="rec-1", limit=10)
    assert "ops_recommendations_current" in con.sql
    assert "WHERE id = ?" in con.sql and "LIMIT 10" in con.sql
    assert con.params == ["rec-1"]
    assert out == [{"ulid": "01U", "id": "rec-1", "status": "open"}]


def test_read_history_orders_newest_first():
    class _Cur:
        description = [("ulid",)]

        def __init__(self):
            self.sql = ""

        def execute(self, sql, params=None):
            self.sql = sql
            return self

        def fetchall(self):
            return [("01B",), ("01A",)]

    con = _Cur()
    out = rt.read_history(con, table="ops_decisions", key="dec-1")
    assert "ops_decisions_history" in con.sql
    assert "ORDER BY last_updated_timestamp DESC" in con.sql
    assert out == [{"ulid": "01B"}, {"ulid": "01A"}]


def test_query_current_substitutes_tbl():
    class _Cur:
        description = [("violation",)]

        def __init__(self):
            self.sql = ""

        def execute(self, sql, params=None):
            self.sql = sql
            return self

        def fetchall(self):
            return [(0,)]

    con = _Cur()
    out = rt.query_current(con, table="ops_recommendations", sql="SELECT COUNT(*) violation FROM {tbl}")
    assert "ops_catalog.ops_recommendations_current" in con.sql
    assert out == [{"violation": 0}]


def test_assert_read_only_sql_allows_select_and_with():
    rt.assert_read_only_sql("SELECT 1 FROM {tbl}")
    rt.assert_read_only_sql("  with x as (select 1) select * from x")  # case-insensitive, leading ws


@pytest.mark.parametrize(
    "bad",
    [
        "DROP TABLE ops_catalog.ops_recommendations_current",
        "DELETE FROM {tbl}",
        "ALTER TABLE {tbl} ADD COLUMN x INT",
        "UPDATE {tbl} SET status='x'",
        "INSERT INTO {tbl} VALUES (1)",
    ],
)
def test_assert_read_only_sql_rejects_writes(bad):
    with pytest.raises(rt.SchemaGateError, match="read-only boundary"):
        rt.assert_read_only_sql(bad)


def test_assert_read_only_sql_rejects_multistatement():
    with pytest.raises(rt.SchemaGateError, match="multi-statement"):
        rt.assert_read_only_sql("SELECT 1; DROP TABLE x")


def test_query_current_enforces_read_only():
    class _Cur:
        description = [("v",)]

        def execute(self, sql, params=None):
            return self

        def fetchall(self):
            return [(0,)]

    with pytest.raises(rt.SchemaGateError, match="read-only boundary"):
        rt.query_current(_Cur(), table="ops_recommendations", sql="DROP TABLE {tbl}")


def test_named_read_executes_registry_sql():
    con = NamedReadCon(rows=[("rec-1",)])
    rows = rt.named_read(con, verb="rec_by_id", params={"id": "rec-1"})
    assert rows == [{"id": "rec-1"}]
    sql, params = con.executed[0]
    assert "ops_catalog.ops_recommendations_current" in sql
    assert "{tbl}" not in sql
    assert params == ["rec-1"]


def test_named_read_unknown_verb_loud_fails():
    with pytest.raises(rt.DuckLakeRuntimeError, match="unknown read verb"):
        rt.named_read(NamedReadCon(), verb="drop_everything", params={})


def test_named_read_param_mismatch_loud_fails():
    with pytest.raises(rt.DuckLakeRuntimeError, match="requires params"):
        rt.named_read(NamedReadCon(), verb="rec_by_id", params={})
    with pytest.raises(rt.DuckLakeRuntimeError, match="requires params"):
        rt.named_read(NamedReadCon(), verb="open_recs", params={"sneaky": "x"})


def test_named_read_registry_verbs_are_select_only():
    for entry in rt.NAMED_READS.values():
        rt.assert_read_only_sql(entry.sql)


def test_read_current_rejects_unknown_filter_column():
    con = NamedReadCon()
    with pytest.raises(rt.DuckLakeRuntimeError, match="unknown filter column"):
        rt.read_current(con, table="ops_recommendations", key="open", key_column="not_a_column")


def test_read_current_binds_named_column():
    con = NamedReadCon(rows=[], cols=("id", "status"))
    rt.read_current(con, table="ops_recommendations", key="open", key_column="status")
    sql, params = con.executed[0]
    assert "WHERE status = ?" in sql
    assert params == ["open"]


def test_read_current_append_only_raises():
    """read_current loud-fails for append_only tables (no current write-through projection, Decision 55)."""
    con = FakeCon()
    with pytest.raises(rt.DuckLakeRuntimeError, match="append_only"):
        rt.read_current(con, table="ops_smoke_events")


def test_query_current_append_only_raises():
    """query_current loud-fails for append_only tables (no current write-through projection)."""
    con = FakeCon()
    with pytest.raises(rt.DuckLakeRuntimeError, match="append_only"):
        rt.query_current(con, table="ops_smoke_events", sql="SELECT {tbl}.ulid FROM {tbl}")
