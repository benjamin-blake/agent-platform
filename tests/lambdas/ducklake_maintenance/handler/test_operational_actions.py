"""T2.19 operational actions concern (catalog_reinit / restore_drill / connectionless-skip /
merge_ops / catalog_stats) for src/lambdas/ducklake_maintenance/handler.py (100% coverage, mocked).

Split from the former tests/test_ducklake_maintenance_handler.py monolith (rec-2709 Wave 8).
Functions copied VERBATIM; _restore_drill_patches stays LOCAL to this module.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import src.lambdas.ducklake_maintenance.handler as h
from src.common.ducklake_runtime import DuckLakeRuntimeError
from tests.fixtures.ducklake_maintenance_handler import _FULL_DSN, _response_body

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# T2.19 operational actions: catalog_reinit / seed / restore_drill + connectionless dispatch
# ---------------------------------------------------------------------------


def test_catalog_reinit_drops_then_reattaches():
    con = MagicMock()
    with (
        patch.object(h, "_drop_meta_schema", return_value=True) as drop_mock,
        patch.object(h.rt, "fetch_dsn", return_value=_FULL_DSN),
        patch.object(h.rt, "open_connection", return_value=con) as open_mock,
    ):
        result = h.action_catalog_reinit(
            {
                "action": "catalog_reinit",
                "data_path": "s3://b/ducklake/",
                "meta_schema": "ducklake_ops",
                "confirm": "ducklake_ops",
            },
            None,
        )
    assert result["ok"] is True and result["reinitialized"] is True
    drop_mock.assert_called_once_with("ducklake_ops", recreate=True)
    assert open_mock.call_args.kwargs["data_path"] == "s3://b/ducklake/"
    assert open_mock.call_args.kwargs["meta_schema"] == "ducklake_ops"
    con.close.assert_called_once()


def test_catalog_reinit_requires_s3_data_path():
    with pytest.raises(DuckLakeRuntimeError, match="data_path"):
        h.action_catalog_reinit({"action": "catalog_reinit"}, None)


def test_catalog_reinit_rejects_bad_meta_schema():
    with pytest.raises(DuckLakeRuntimeError, match="invalid SQL identifier"):
        h.action_catalog_reinit(
            {"data_path": "s3://b/ducklake/", "meta_schema": "bad-name;DROP", "confirm": "bad-name;DROP"}, None
        )


def test_catalog_reinit_requires_explicit_meta_schema():
    """Destructive-action guard (Decision 84): a no-arg invoke must never target the live catalog."""
    with pytest.raises(DuckLakeRuntimeError, match="EXPLICIT 'meta_schema'"):
        h.action_catalog_reinit({"data_path": "s3://b/ducklake/"}, None)


def test_catalog_reinit_requires_matching_confirm():
    with pytest.raises(DuckLakeRuntimeError, match="confirm="):
        h.action_catalog_reinit({"data_path": "s3://b/ducklake/", "meta_schema": "ducklake_smoke"}, None)


def _restore_drill_patches(read_rows):
    return (
        patch.object(h, "_drop_meta_schema", return_value=True),
        patch.object(h.rt, "fetch_dsn", return_value=_FULL_DSN),
        patch.object(h.rt, "open_connection", return_value=MagicMock()),
        patch.object(h.rt, "create_scd2_tables"),
        patch.object(h.rt, "write_scd2"),
        patch.object(h.rt, "read_current", return_value=read_rows),
        patch.object(h, "subprocess_run", return_value=type("R", (), {"returncode": 0, "stderr": ""})()),
        patch.object(h.catalog_dr, "run_pg_restore"),
    )


def test_restore_drill_ok():
    p = _restore_drill_patches([{"rec_id": "drill-probe", "payload": "restore-drill"}])
    with p[0], p[1], p[2], p[3], p[4], p[5], p[6], p[7]:
        result = h.action_restore_drill({"action": "restore_drill"}, None)
    assert result["ok"] is True and result["restored"] is True


def test_restore_drill_probe_lost_loud_fails():
    p = _restore_drill_patches([])  # read-your-write finds nothing after restore
    with p[0], p[1], p[2], p[3], p[4], p[5], p[6], p[7]:
        with pytest.raises(h.catalog_dr.CatalogDrError, match="read-your-write FAILED"):
            h.action_restore_drill({"action": "restore_drill"}, None)


def test_restore_drill_pg_dump_failure_loud_fails():
    with (
        patch.object(h, "_drop_meta_schema", return_value=True),
        patch.object(h.rt, "fetch_dsn", return_value=_FULL_DSN),
        patch.object(h.rt, "open_connection", return_value=MagicMock()),
        patch.object(h.rt, "create_scd2_tables"),
        patch.object(h.rt, "write_scd2"),
        patch.object(h, "subprocess_run", return_value=type("R", (), {"returncode": 1, "stderr": "boom"})()),
    ):
        with pytest.raises(h.catalog_dr.CatalogDrError, match="pg_dump exited 1"):
            h.action_restore_drill({"action": "restore_drill"}, None)


def test_handler_dispatches_catalog_reinit_without_a_connection_arg():
    """The handler never pre-opens a connection -- every action receives con=None (T2.18 c9 split)."""
    action_mock = MagicMock(return_value={"ok": True})
    with patch.dict(h._ACTIONS, {"catalog_reinit": action_mock}):
        r = h.handler({"action": "catalog_reinit", "data_path": "s3://b/ducklake/"})
    assert r["statusCode"] == 200
    assert action_mock.call_args.args[1] is None


# ---------------------------------------------------------------------------
# action_merge_ops (T2.18 Phase-4 production ops_* merge cadence)
# ---------------------------------------------------------------------------


def test_action_merge_ops_requires_data_path():
    """Loud-fail when data_path is missing."""
    with pytest.raises(DuckLakeRuntimeError, match="data_path"):
        h.action_merge_ops({}, None)


def test_action_merge_ops_requires_s3_data_path():
    """Loud-fail when data_path is not an s3:// URI."""
    with pytest.raises(DuckLakeRuntimeError, match="data_path"):
        h.action_merge_ops({"data_path": "/local/path"}, None)


def test_action_merge_ops_requires_meta_schema():
    """Loud-fail when meta_schema is missing."""
    with pytest.raises(DuckLakeRuntimeError, match="meta_schema"):
        h.action_merge_ops({"data_path": "s3://b/ducklake/"}, None)


def test_action_merge_ops_no_tables_discovered():
    """Loud-fail when information_schema returns no ops_* table pairs."""
    con = MagicMock()
    con.execute.return_value.fetchall.return_value = []
    with (
        patch.object(h.rt, "fetch_dsn", return_value=_FULL_DSN),
        patch.object(h.rt, "open_connection", return_value=con),
    ):
        with pytest.raises(DuckLakeRuntimeError, match="no ops_"):
            h.action_merge_ops({"data_path": "s3://b/ducklake/", "meta_schema": "ducklake_ops"}, None)
    con.close.assert_called_once()


def test_action_merge_ops_discovers_and_merges_tables():
    """Discovery query triggers merge_adjacent_files for each discovered table."""
    expected_tables = [
        "ops_decisions_current",
        "ops_decisions_history",
        "ops_recommendations_current",
        "ops_recommendations_history",
    ]
    con = MagicMock()
    con.execute.return_value.fetchall.return_value = [(t,) for t in expected_tables]

    with (
        patch.object(h.rt, "fetch_dsn", return_value=_FULL_DSN),
        patch.object(h.rt, "open_connection", return_value=con),
        patch.object(h.maint, "_count_files", return_value=10),
        patch.object(h.maint, "merge_adjacent_files") as mock_merge,
        patch.object(h, "_emit_maintenance_metric"),
    ):
        result = h.action_merge_ops({"data_path": "s3://b/ducklake/", "meta_schema": "ducklake_ops"}, None)

    assert result["ok"] is True
    assert result["action"] == "merge_ops"
    assert sorted(result["tables"]) == expected_tables
    assert mock_merge.call_count == len(expected_tables)
    assert len(result["per_table"]) == len(expected_tables)
    assert "files_before" in result
    assert "files_after" in result
    assert "elapsed_ms" in result
    con.close.assert_called_once()


def test_action_merge_ops_covers_ops_recommendations_and_ops_decisions():
    """Both ops_recommendations AND ops_decisions pairs must be merged, not just one."""
    discovered = [
        "ops_decisions_current",
        "ops_decisions_history",
        "ops_recommendations_current",
        "ops_recommendations_history",
    ]
    con = MagicMock()
    con.execute.return_value.fetchall.return_value = [(t,) for t in discovered]

    merged: list[str] = []

    def capture_merge(c, tables, *, catalog=None, schema=None):
        merged.extend(tables)

    with (
        patch.object(h.rt, "fetch_dsn", return_value=_FULL_DSN),
        patch.object(h.rt, "open_connection", return_value=con),
        patch.object(h.maint, "_count_files", return_value=5),
        patch.object(h.maint, "merge_adjacent_files", side_effect=capture_merge),
        patch.object(h, "_emit_maintenance_metric"),
    ):
        h.action_merge_ops({"data_path": "s3://b/ducklake/", "meta_schema": "ducklake_ops"}, None)

    assert any("ops_recommendations" in t for t in merged), "ops_recommendations tables not merged"
    assert any("ops_decisions" in t for t in merged), "ops_decisions tables not merged"


def test_action_merge_ops_emits_metrics():
    """MergeOps* metrics are emitted after a successful merge."""
    con = MagicMock()
    con.execute.return_value.fetchall.return_value = [
        ("ops_recommendations_history",),
        ("ops_recommendations_current",),
    ]

    with (
        patch.object(h.rt, "fetch_dsn", return_value=_FULL_DSN),
        patch.object(h.rt, "open_connection", return_value=con),
        patch.object(h.maint, "_count_files", return_value=3),
        patch.object(h.maint, "merge_adjacent_files"),
        patch.object(h, "_emit_maintenance_metric") as mock_emit,
    ):
        h.action_merge_ops({"data_path": "s3://b/ducklake/", "meta_schema": "ducklake_ops"}, None)

    metric_names = [c.args[0] for c in mock_emit.call_args_list]
    assert "MergeOpsDurationMs" in metric_names
    assert "MergeOpsFilesBeforeTotal" in metric_names
    assert "MergeOpsFilesAfterTotal" in metric_names
    assert "MergeOpsTablesCount" in metric_names


def test_action_merge_ops_handler_receives_no_connection():
    """Handler dispatches merge_ops with con=None -- the action opens its own connection."""
    action_mock = MagicMock(
        return_value={
            "ok": True,
            "action": "merge_ops",
            "tables": [],
            "files_before": 0,
            "files_after": 0,
            "elapsed_ms": 1.0,
            "per_table": [],
        }
    )
    with patch.dict(h._ACTIONS, {"merge_ops": action_mock}):
        r = h.handler({"action": "merge_ops", "data_path": "s3://b/ducklake/", "meta_schema": "ducklake_ops"})
    assert r["statusCode"] == 200
    assert action_mock.call_args.args[1] is None


def test_action_merge_ops_no_destructive_primitives():
    """merge_ops must not dispatch expire_snapshots, cleanup_old_files, or delete_orphaned_files."""
    con = MagicMock()
    con.execute.return_value.fetchall.return_value = [
        ("ops_recommendations_history",),
        ("ops_recommendations_current",),
    ]

    with (
        patch.object(h.rt, "fetch_dsn", return_value=_FULL_DSN),
        patch.object(h.rt, "open_connection", return_value=con),
        patch.object(h.maint, "_count_files", return_value=5),
        patch.object(h.maint, "merge_adjacent_files"),
        patch.object(h.maint, "expire_snapshots") as mock_expire,
        patch.object(h.maint, "cleanup_old_files") as mock_cleanup,
        patch.object(h.maint, "delete_orphaned_files") as mock_orphan,
        patch.object(h, "_emit_maintenance_metric"),
    ):
        h.action_merge_ops({"data_path": "s3://b/ducklake/", "meta_schema": "ducklake_ops"}, None)

    mock_expire.assert_not_called()
    mock_cleanup.assert_not_called()
    mock_orphan.assert_not_called()


def test_handler_merge_ops_listed_in_actions():
    """merge_ops must appear in the actions list returned on unknown action."""
    body = _response_body(h.handler({"action": "bad"}))
    assert "merge_ops" in body["actions"]


# ---------------------------------------------------------------------------
# catalog_stats (D3a / neon-egress measurement obligation)
# ---------------------------------------------------------------------------


def test_action_catalog_stats_success():
    """catalog_stats dispatches to maint.catalog_stats with the event meta_schema; emits the size metric."""
    stats = {
        "ok": True,
        "meta_schema": "ducklake_ops",
        "catalog_metadata_bytes": 7_100_000,
        "snapshot_rows_est": 50,
        "data_file_rows_est": 800,
        "file_column_stats_rows_est": 12000,
        "metadata_table_count": 3,
        "metadata_tables": [],
        "per_ops_table": [{"table": "ops_recommendations_current", "data_file_count": 400}],
        "per_ops_table_note": "",
    }
    with (
        patch.object(h.rt, "fetch_dsn", return_value=_FULL_DSN),
        patch.object(h.maint, "catalog_stats", return_value=stats) as mock_stats,
        patch.object(h, "_emit_maintenance_metric") as mock_emit,
    ):
        result = h.action_catalog_stats({"meta_schema": "ducklake_ops"}, None)

    assert result["catalog_metadata_bytes"] == 7_100_000
    assert mock_stats.call_args.kwargs["meta_schema"] == "ducklake_ops"
    metric_names = [c.args[0] for c in mock_emit.call_args_list]
    assert "CatalogMetadataBytes" in metric_names
    assert "CatalogFileColumnStatsRows" in metric_names


def test_action_catalog_stats_requires_meta_schema():
    """No-arg invoke is refused -- catalog_stats needs an explicit meta_schema (no production default)."""
    with pytest.raises(DuckLakeRuntimeError, match="meta_schema"):
        h.action_catalog_stats({}, None)


def test_action_catalog_stats_is_connectionless_and_attach_free():
    """catalog_stats is metadata-only (ATTACH-free) -- the handler dispatches it with con=None."""
    with (
        patch.object(h.rt, "fetch_dsn", return_value=_FULL_DSN),
        patch.object(h.maint, "catalog_stats", return_value={"ok": True, "catalog_metadata_bytes": 0}),
        patch.object(h, "_emit_maintenance_metric"),
    ):
        r = h.handler({"action": "catalog_stats", "meta_schema": "ducklake_ops"})
    assert r["statusCode"] == 200


def test_handler_catalog_stats_listed_in_actions():
    """catalog_stats must appear in the actions list returned on an unknown action."""
    body = _response_body(h.handler({"action": "bad"}))
    assert "catalog_stats" in body["actions"]
