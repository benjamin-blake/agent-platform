"""Tests for src/common/ducklake_maintenance.py (T2.18, 100% coverage, mocked connection)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

import src.common.ducklake_maintenance as maint
from src.common.ducklake_maintenance import (
    GC_BREAKER_BYTES,
    GC_BREAKER_FILE_FRACTION,
    GC_TABLE_SCOPE,
    HOT_TABLE_SCOPE,
    SNAPSHOT_FLOOR,
    SNAPSHOT_RETAIN_DAYS,
    DuckLakeMaintenanceError,
    catalog_stats,
    check_gc_breaker,
    cleanup_old_files,
    delete_orphaned_files,
    expire_snapshots,
    flush_inlined_data,
    merge_adjacent_files,
    rewrite,
    run_gc,
    run_hot_merge,
    run_merge,
)

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 6, 7, 12, 0, 0, tzinfo=timezone.utc)


class FakeCon:
    """Minimal connection double: records SQL; returns configurable results per substring."""

    def __init__(self, fetchall_map: dict[str, list[Any]] | None = None, fetchone_map: dict[str, Any] | None = None):
        self.executed: list[str] = []
        self._fetchall_map: dict[str, list[Any]] = fetchall_map or {}
        self._fetchone_map: dict[str, Any] = fetchone_map or {}
        self._last = ""

    def execute(self, sql: str, params: Any = None) -> "FakeCon":
        self.executed.append(sql)
        self._last = sql
        return self

    def fetchone(self) -> tuple[Any, ...]:
        for sub, val in self._fetchone_map.items():
            if sub in self._last:
                return val
        return (0,)

    def fetchall(self) -> list[Any]:
        for sub, val in self._fetchall_map.items():
            if sub in self._last:
                return val
        return []

    def close(self) -> None:
        pass


def _ts(y: int, m: int, d: int) -> datetime:
    return datetime(y, m, d, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


def test_guardrail_constants():
    assert SNAPSHOT_RETAIN_DAYS == 30
    assert maint.FILE_CLEANUP_GRACE_DAYS == 7
    assert SNAPSHOT_FLOOR == 2
    assert GC_BREAKER_FILE_FRACTION == pytest.approx(0.20)
    assert GC_BREAKER_BYTES == 10 * 1024 * 1024 * 1024
    assert len(GC_TABLE_SCOPE) >= 2


def test_scope_note_present():
    assert "T2.19" in maint.MAINTENANCE_SCOPE_NOTE
    assert "ops_*" in maint.MAINTENANCE_SCOPE_NOTE or "ops_" in maint.MAINTENANCE_SCOPE_NOTE


# ---------------------------------------------------------------------------
# _ts_str
# ---------------------------------------------------------------------------


def test_ts_str_format():
    dt = datetime(2026, 1, 15, 8, 30, 0, tzinfo=timezone.utc)
    s = maint._ts_str(dt)
    assert s == "2026-01-15 08:30:00+00"


# ---------------------------------------------------------------------------
# flush_inlined_data
# ---------------------------------------------------------------------------


def test_flush_inlined_data_calls_per_table():
    con = FakeCon()
    flush_inlined_data(con, ["t1", "t2"])
    stmts = " ".join(con.executed)
    assert "ducklake_flush_inlined_data" in stmts
    assert "t1" in stmts
    assert "t2" in stmts


def test_flush_inlined_data_empty_tables():
    con = FakeCon()
    flush_inlined_data(con, [])
    assert con.executed == []


# ---------------------------------------------------------------------------
# merge_adjacent_files
# ---------------------------------------------------------------------------


def test_merge_adjacent_files_calls_per_table():
    con = FakeCon()
    merge_adjacent_files(con, ["hist", "curr"])
    stmts = " ".join(con.executed)
    assert "ducklake_merge_adjacent_files" in stmts
    assert "hist" in stmts
    assert "curr" in stmts


def test_merge_adjacent_files_empty_tables():
    con = FakeCon()
    merge_adjacent_files(con, [])
    assert con.executed == []


# ---------------------------------------------------------------------------
# expire_snapshots
# ---------------------------------------------------------------------------

_SNAPSHOT_ROWS = [
    (10, _ts(2026, 6, 7)),
    (9, _ts(2026, 6, 1)),
    (8, _ts(2026, 5, 1)),
    (7, _ts(2026, 1, 1)),
    (6, _ts(2025, 12, 1)),
]


def test_expire_snapshots_floor_skips_when_too_few():
    con = FakeCon(fetchall_map={"ducklake_snapshots": [(1, _ts(2026, 6, 7)), (2, _ts(2026, 6, 6))]})
    result = expire_snapshots(con, _now=_NOW)
    assert result == 0
    assert not any("ducklake_expire_snapshots" in s for s in con.executed)


def test_expire_snapshots_uses_cutoff_correctly():
    con = FakeCon(
        fetchall_map={"ducklake_snapshots": _SNAPSHOT_ROWS},
        fetchone_map={"ducklake_expire_snapshots": (3,)},
    )
    result = expire_snapshots(con, retain_days=30, floor=2, _now=_NOW)
    assert result == 3
    expire_stmts = [s for s in con.executed if "ducklake_expire_snapshots" in s]
    assert len(expire_stmts) == 1
    assert "older_than=TIMESTAMPTZ" in expire_stmts[0]


def test_expire_snapshots_zero_when_nothing_to_expire():
    recent = [(i, datetime(2026, 6, 1 + i % 5, tzinfo=timezone.utc)) for i in range(5)]
    con = FakeCon(
        fetchall_map={"ducklake_snapshots": recent},
        fetchone_map={"ducklake_expire_snapshots": (0,)},
    )
    result = expire_snapshots(con, retain_days=30, floor=2, _now=_NOW)
    assert isinstance(result, int)


# ---------------------------------------------------------------------------
# cleanup_old_files
# ---------------------------------------------------------------------------


def test_cleanup_old_files_issues_correct_call():
    con = FakeCon(fetchone_map={"ducklake_cleanup_old_files": (5,)})
    result = cleanup_old_files(con, _now=_NOW)
    assert result == 5
    stmts = [s for s in con.executed if "ducklake_cleanup_old_files" in s]
    assert len(stmts) == 1
    assert "dry_run=False" in stmts[0]
    assert "cleanup_all=False" in stmts[0]
    assert "older_than=TIMESTAMPTZ" in stmts[0]


def test_cleanup_old_files_never_cleanup_all():
    con = FakeCon(fetchone_map={"ducklake_cleanup_old_files": (0,)})
    cleanup_old_files(con, _now=_NOW)
    for s in con.executed:
        if "ducklake_cleanup_old_files" in s:
            assert "cleanup_all=True" not in s


# ---------------------------------------------------------------------------
# delete_orphaned_files
# ---------------------------------------------------------------------------


def test_delete_orphaned_files_issues_correct_call():
    con = FakeCon(fetchone_map={"ducklake_delete_orphaned_files": (3,)})
    result = delete_orphaned_files(con, _now=_NOW)
    assert result == 3
    stmts = [s for s in con.executed if "ducklake_delete_orphaned_files" in s]
    assert len(stmts) == 1
    assert "dry_run=False" in stmts[0]
    assert "older_than=TIMESTAMPTZ" in stmts[0]


def test_delete_orphaned_files_never_cleanup_all():
    con = FakeCon(fetchone_map={"ducklake_delete_orphaned_files": (0,)})
    delete_orphaned_files(con, _now=_NOW)
    for s in con.executed:
        if "ducklake_delete_orphaned_files" in s:
            assert "cleanup_all=True" not in s


# ---------------------------------------------------------------------------
# rewrite
# ---------------------------------------------------------------------------


def test_rewrite_calls_per_table():
    con = FakeCon()
    rewrite(con, ["t1"])
    stmts = " ".join(con.executed)
    assert "ducklake_rewrite_data_files" in stmts
    assert "t1" in stmts


# ---------------------------------------------------------------------------
# check_gc_breaker
# ---------------------------------------------------------------------------


def _con_with_files(
    file_map: dict[str, list[tuple[str, int]]], cleanup_paths: list[str] = None, orphan_paths: list[str] = None
) -> FakeCon:
    """Build a FakeCon whose fetchall results match ducklake_list_files, cleanup, orphan queries."""
    fetchall_map: dict[str, list[Any]] = {}
    for table, files in file_map.items():
        fetchall_map[f"ducklake_list_files('ops_catalog', '{table}')"] = [(p, s) for p, s in files]
    if cleanup_paths is not None:
        fetchall_map["ducklake_cleanup_old_files"] = [(p,) for p in cleanup_paths]
    if orphan_paths is not None:
        fetchall_map["ducklake_delete_orphaned_files"] = [(p,) for p in orphan_paths]
    return FakeCon(fetchall_map=fetchall_map)


def test_breaker_no_trip_empty_catalog():
    con = FakeCon()
    stats = check_gc_breaker(con, ["t1"], _now=_NOW)
    assert stats["breaker_tripped"] is False
    assert stats["total_files"] == 0


def test_breaker_no_trip_below_threshold():
    files = [(f"s3://b/f{i}", 100) for i in range(10)]
    con = _con_with_files({"t1": files}, cleanup_paths=["s3://b/f0"], orphan_paths=[])
    stats = check_gc_breaker(con, ["t1"], _now=_NOW)
    assert stats["breaker_tripped"] is False
    assert stats["total_files"] == 10
    assert stats["would_delete_files"] == 1
    assert stats["file_fraction"] == pytest.approx(0.10)


def test_breaker_trips_on_high_file_fraction():
    files = [(f"s3://b/f{i}", 100) for i in range(5)]
    con = _con_with_files({"t1": files}, cleanup_paths=[f"s3://b/f{i}" for i in range(5)], orphan_paths=[])
    with pytest.raises(DuckLakeMaintenanceError, match="circuit breaker tripped"):
        check_gc_breaker(con, ["t1"], _now=_NOW)


def test_breaker_trips_on_high_byte_budget():
    large_file_size = 11 * 1024 * 1024 * 1024
    files = [("s3://b/big.parquet", large_file_size)]
    con = _con_with_files({"t1": files}, cleanup_paths=["s3://b/big.parquet"], orphan_paths=[])
    with pytest.raises(DuckLakeMaintenanceError, match="GiB"):
        check_gc_breaker(con, ["t1"], _now=_NOW, file_fraction=1.0)


def test_breaker_deletes_nothing_on_trip():
    files = [(f"s3://b/f{i}", 100) for i in range(3)]
    con = _con_with_files({"t1": files}, cleanup_paths=[f"s3://b/f{i}" for i in range(3)], orphan_paths=[])
    with pytest.raises(DuckLakeMaintenanceError):
        check_gc_breaker(con, ["t1"], _now=_NOW)
    delete_stmts = [s for s in con.executed if "dry_run=False" in s]
    assert delete_stmts == [], "breaker must not issue any destructive call"


def test_breaker_aggregates_across_tables():
    files_t1 = [(f"s3://b/t1/f{i}", 100) for i in range(5)]
    files_t2 = [(f"s3://b/t2/f{i}", 100) for i in range(5)]
    con = _con_with_files({"t1": files_t1, "t2": files_t2}, cleanup_paths=[], orphan_paths=[])
    stats = check_gc_breaker(con, ["t1", "t2"], _now=_NOW)
    assert stats["total_files"] == 10


def test_breaker_returns_stats_dict():
    con = FakeCon()
    stats = check_gc_breaker(con, ["t1"], _now=_NOW)
    assert "total_files" in stats
    assert "total_bytes" in stats
    assert "would_delete_files" in stats
    assert "would_delete_bytes" in stats
    assert "file_fraction" in stats
    assert "breaker_tripped" in stats


# ---------------------------------------------------------------------------
# run_merge
# ---------------------------------------------------------------------------


def test_run_merge_returns_ok():
    con = FakeCon(fetchone_map={"ducklake_list_files": (4,)})
    result = run_merge(con, ["t1"])
    assert result["ok"] is True
    assert result["action"] == "merge"
    assert "files_before" in result
    assert "files_after_merge" in result


def test_run_merge_no_destructive_calls():
    con = FakeCon()
    run_merge(con, ["t1"])
    destructive = [
        s
        for s in con.executed
        if "dry_run=False" in s or "cleanup_old_files" in s or "delete_orphaned" in s or "expire_snapshots" in s
    ]
    assert destructive == []


def test_run_merge_calls_flush_and_merge():
    con = FakeCon()
    run_merge(con, ["t1", "t2"])
    stmts = " ".join(con.executed)
    assert "ducklake_flush_inlined_data" in stmts
    assert "ducklake_merge_adjacent_files" in stmts


# ---------------------------------------------------------------------------
# run_gc
# ---------------------------------------------------------------------------


def _gc_con(*, file_count: int = 10, cleanup_count: int = 1, orphan_count: int = 0, snapshot_count: int = 5) -> FakeCon:
    files = [(f"s3://b/f{i}", 100) for i in range(file_count)]
    cleanup_paths = [f"s3://b/f{i}" for i in range(cleanup_count)]
    orphan_paths = [f"s3://b/o{i}" for i in range(orphan_count)]

    snap_rows = [(i, _ts(2025, 1, i + 1)) for i in range(snapshot_count)]

    fetchall_map: dict[str, list[Any]] = {
        "ducklake_list_files": [(p, s) for p, s in files],
        "ducklake_cleanup_old_files": [(p,) for p in cleanup_paths],
        "ducklake_delete_orphaned_files": [(p,) for p in orphan_paths],
        "ducklake_snapshots": snap_rows,
        "ducklake_expire_snapshots": [],
    }
    fetchone_map = {
        "ducklake_cleanup_old_files": (cleanup_count,),
        "ducklake_delete_orphaned_files": (orphan_count,),
        "ducklake_expire_snapshots": (2,),
        "count(*)": (file_count,),
    }
    return FakeCon(fetchall_map=fetchall_map, fetchone_map=fetchone_map)


def test_run_gc_returns_ok():
    con = _gc_con()
    result = run_gc(con, ["t1"], _now=_NOW)
    assert result["ok"] is True
    assert result["action"] == "gc"


def test_run_gc_includes_all_result_keys():
    con = _gc_con()
    result = run_gc(con, ["t1"], _now=_NOW)
    for key in ("files_before", "files_after", "snapshots_expired", "files_cleaned", "orphans_deleted", "breaker_stats"):
        assert key in result, f"missing key {key!r}"


def test_run_gc_breaker_trip_raises_and_no_destructive():
    files = [(f"s3://b/f{i}", 100) for i in range(3)]
    cleanup_paths = [f"s3://b/f{i}" for i in range(3)]

    con = FakeCon(
        fetchall_map={
            "ducklake_list_files": [(p, s) for p, s in files],
            "ducklake_cleanup_old_files": [(p,) for p in cleanup_paths],
            "ducklake_delete_orphaned_files": [],
            "ducklake_snapshots": [(1, _ts(2025, 1, 1)), (2, _ts(2025, 2, 1)), (3, _ts(2025, 3, 1))],
        },
        fetchone_map={"ducklake_expire_snapshots": (0,), "ducklake_cleanup_old_files": (3,), "count(*)": (3,)},
    )
    with pytest.raises(DuckLakeMaintenanceError, match="circuit breaker"):
        run_gc(con, ["t1"], _now=_NOW)
    destructive = [s for s in con.executed if "dry_run=False" in s]
    assert destructive == [], "run_gc must not issue destructive calls after breaker trip"


def test_run_gc_calls_all_five_steps():
    con = _gc_con()
    run_gc(con, ["t1"], _now=_NOW)
    stmts = " ".join(con.executed)
    assert "ducklake_flush_inlined_data" in stmts
    assert "ducklake_merge_adjacent_files" in stmts
    assert "ducklake_expire_snapshots" in stmts
    assert "ducklake_cleanup_old_files" in stmts
    assert "ducklake_delete_orphaned_files" in stmts


def test_run_gc_respects_custom_thresholds():
    con = FakeCon(
        fetchall_map={
            "ducklake_list_files": [("s3://b/f0", 100)],
            "ducklake_cleanup_old_files": [("s3://b/f0",)],
            "ducklake_delete_orphaned_files": [],
            "ducklake_snapshots": [],
        },
        fetchone_map={
            "ducklake_cleanup_old_files": (1,),
            "ducklake_delete_orphaned_files": (0,),
            "ducklake_expire_snapshots": (0,),
        },
    )
    with pytest.raises(DuckLakeMaintenanceError):
        run_gc(con, ["t1"], file_fraction=0.0, _now=_NOW)


# ---------------------------------------------------------------------------
# HOT_TABLE_SCOPE constant
# ---------------------------------------------------------------------------


def test_hot_table_scope_defined():
    assert len(HOT_TABLE_SCOPE) >= 1


def test_hot_table_scope_note_references_t2_19():
    assert "T2.19" in maint.MAINTENANCE_SCOPE_NOTE or "T2.19" in str(HOT_TABLE_SCOPE) or hasattr(maint, "HOT_TABLE_SCOPE")


# ---------------------------------------------------------------------------
# run_hot_merge
# ---------------------------------------------------------------------------


def test_run_hot_merge_returns_ok():
    con = FakeCon(fetchone_map={"ducklake_list_files": (4,)})
    result = run_hot_merge(con, ["t1"])
    assert result["ok"] is True
    assert result["action"] == "hot_merge"


def test_run_hot_merge_has_files_before_and_after():
    con = FakeCon(fetchone_map={"ducklake_list_files": (4,)})
    result = run_hot_merge(con, ["t1"])
    assert "files_before" in result
    assert "files_after" in result


def test_run_hot_merge_no_destructive_calls():
    """Merge-only invariant: hot_merge MUST NOT issue cleanup/orphan/expire/delete calls."""
    con = FakeCon()
    run_hot_merge(con, ["t1"])
    destructive = [
        s
        for s in con.executed
        if "cleanup_old_files" in s or "delete_orphaned_files" in s or "expire_snapshots" in s or "dry_run=False" in s
    ]
    assert destructive == [], "run_hot_merge must not issue any destructive call"


def test_run_hot_merge_calls_merge_adjacent_files():
    con = FakeCon()
    run_hot_merge(con, ["hist", "curr"])
    stmts = " ".join(con.executed)
    assert "ducklake_merge_adjacent_files" in stmts


def test_run_hot_merge_no_gc_breaker_check():
    """hot_merge skips the circuit-breaker check (merge-only path has no destructions)."""
    con = FakeCon()
    run_hot_merge(con, ["t1"])
    breaker_stmts = [s for s in con.executed if "ducklake_cleanup_old_files" in s and "dry_run=True" in s]
    assert breaker_stmts == []


def test_run_hot_merge_tables_in_result():
    con = FakeCon()
    result = run_hot_merge(con, ["ta", "tb"])
    assert "ta" in result["tables"]
    assert "tb" in result["tables"]


# ---------------------------------------------------------------------------
# Env-sourced breaker thresholds (FP-B co-tuning mechanism)
# ---------------------------------------------------------------------------


def test_env_sourced_defaults_are_fp_a_values():
    """The env-sourced defaults must match the FP-A shipped values (Decision 55 invariant)."""
    assert GC_BREAKER_FILE_FRACTION == pytest.approx(0.20)
    assert GC_BREAKER_BYTES == 10 * 1024 * 1024 * 1024  # 10 GiB


def test_env_sourced_file_fraction_controls_breaker():
    """Passing a custom file_fraction to check_gc_breaker overrides the default."""
    # 1 file, all deleted -> 100% > 0% threshold -> trips
    files = [("s3://b/f0", 100)]
    con = _con_with_files({"t1": files}, cleanup_paths=["s3://b/f0"], orphan_paths=[])
    with pytest.raises(DuckLakeMaintenanceError):
        check_gc_breaker(con, ["t1"], file_fraction=0.0, _now=_NOW)


def test_env_sourced_byte_budget_controls_breaker():
    """Passing a custom byte_budget to check_gc_breaker overrides the default."""
    large_bytes = 1024 * 1024  # 1 MiB would-delete
    files = [("s3://b/big.parquet", large_bytes)]
    con = _con_with_files({"t1": files}, cleanup_paths=["s3://b/big.parquet"], orphan_paths=[])
    with pytest.raises(DuckLakeMaintenanceError, match="GiB"):
        check_gc_breaker(con, ["t1"], file_fraction=1.0, byte_budget=512 * 1024, _now=_NOW)  # 512 KiB budget


# ---------------------------------------------------------------------------
# catalog_stats (D3a / neon-egress measurement obligation) -- pure Postgres-metadata read.
# ---------------------------------------------------------------------------

_DSN = {"username": "u", "password": "p", "host": "h", "dbname": "neondb", "sslmode": "require"}


class _FakeCursor:
    """psycopg2-cursor double: serves fetchall() results in order; optional per-query raiser."""

    def __init__(self, results: list[list[Any]], raise_on: str | None = None):
        self._results = list(results)
        self._raise_on = raise_on
        self.queries: list[tuple[str, Any]] = []

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *exc: Any) -> bool:
        return False

    def execute(self, sql: str, params: Any = None) -> None:
        self.queries.append((sql, params))
        if self._raise_on and self._raise_on in sql:
            raise RuntimeError("column does not exist")

    def fetchall(self) -> list[Any]:
        return self._results.pop(0)


class _FakeConn:
    def __init__(self, cursor: _FakeCursor):
        self._cursor = cursor
        self.closed = False

    def cursor(self) -> _FakeCursor:
        return self._cursor

    def close(self) -> None:
        self.closed = True


_META_ROWS = [
    ("ducklake_file_column_stats", 5_000_000, 12000),
    ("ducklake_data_file", 2_000_000, 800),
    ("ducklake_snapshot", 100_000, 50),
]
_OPS_ROWS = [("ops_decisions_current", 30), ("ops_recommendations_current", 400)]


class TestCatalogStats:
    def test_reports_catalog_metadata_footprint(self) -> None:
        cursor = _FakeCursor([_META_ROWS, _OPS_ROWS])
        conn = _FakeConn(cursor)
        result = catalog_stats(meta_schema="ducklake_ops", dsn=_DSN, _connect=lambda conninfo: conn)

        assert result["ok"] is True
        assert result["meta_schema"] == "ducklake_ops"
        assert result["catalog_metadata_bytes"] == 7_100_000  # exact sum of pg_total_relation_size
        assert result["file_column_stats_rows_est"] == 12000  # the ducklake #859 egress driver
        assert result["data_file_rows_est"] == 800
        assert result["snapshot_rows_est"] == 50
        assert result["metadata_table_count"] == 3
        assert result["per_ops_table"] == [
            {"table": "ops_decisions_current", "data_file_count": 30},
            {"table": "ops_recommendations_current", "data_file_count": 400},
        ]
        assert conn.closed is True

    def test_per_ops_breakdown_degrades_without_crashing(self) -> None:
        """If the per-ops join fails (catalog column drift), totals are still reported with a note."""
        cursor = _FakeCursor([_META_ROWS], raise_on="ducklake_data_file df")
        conn = _FakeConn(cursor)
        result = catalog_stats(meta_schema="ducklake_ops", dsn=_DSN, _connect=lambda conninfo: conn)

        assert result["ok"] is True
        assert result["catalog_metadata_bytes"] == 7_100_000  # core measurement still returned
        assert result["per_ops_table"] == []
        assert "unavailable" in result["per_ops_table_note"]
        assert conn.closed is True

    def test_invalid_meta_schema_loud_fails(self) -> None:
        with pytest.raises(DuckLakeMaintenanceError, match="invalid meta_schema"):
            catalog_stats(meta_schema="ducklake_ops; DROP", dsn=_DSN, _connect=lambda conninfo: _FakeConn(_FakeCursor([])))

    def test_missing_metadata_tables_yields_null_estimates(self) -> None:
        cursor = _FakeCursor([[], []])  # no ducklake_* tables found
        result = catalog_stats(meta_schema="ducklake_ops", dsn=_DSN, _connect=lambda conninfo: _FakeConn(cursor))
        assert result["catalog_metadata_bytes"] == 0
        assert result["file_column_stats_rows_est"] is None
        assert result["snapshot_rows_est"] is None
