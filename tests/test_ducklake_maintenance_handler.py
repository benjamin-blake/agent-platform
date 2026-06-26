"""Tests for src/lambdas/ducklake_maintenance/handler.py (T2.18, 100% coverage, mocked)."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

import src.lambdas.ducklake_maintenance.handler as h
from src.common.ducklake_maintenance import DuckLakeMaintenanceError
from src.common.ducklake_runtime import DuckLakeRuntimeError, VersionMismatchError

pytestmark = pytest.mark.unit


class FakeCon:
    """Minimal connection double for handler dispatch tests."""

    def __init__(self, fetchall=None, fetchone_map=None):
        self.closed = False
        self._fetchall = fetchall or []
        self._fetchone_map = fetchone_map or {}
        self._last = ""

    def execute(self, sql: str, params: Any = None) -> "FakeCon":
        self._last = sql
        return self

    def fetchone(self) -> tuple[Any, ...]:
        for sub, val in self._fetchone_map.items():
            if sub in self._last:
                return val
        return (0,)

    def fetchall(self) -> list[Any]:
        return self._fetchall

    def close(self) -> None:
        self.closed = True


def _response_body(r: dict[str, Any]) -> dict[str, Any]:
    return json.loads(r["body"])


# ---------------------------------------------------------------------------
# _parse_event / _response
# ---------------------------------------------------------------------------


def test_parse_event_body_string():
    assert h._parse_event({"body": json.dumps({"action": "merge"})}) == {"action": "merge"}


def test_parse_event_body_dict():
    assert h._parse_event({"body": {"action": "gc"}}) == {"action": "gc"}


def test_parse_event_body_empty_string():
    assert h._parse_event({"body": ""}) == {}


def test_parse_event_direct_dict():
    assert h._parse_event({"action": "merge"}) == {"action": "merge"}


def test_parse_event_non_dict():
    assert h._parse_event("nonsense") == {}


def test_response_envelope():
    r = h._response(200, {"ok": True})
    assert r["statusCode"] == 200
    assert json.loads(r["body"])["ok"] is True
    assert r["headers"]["Content-Type"] == "application/json"


# ---------------------------------------------------------------------------
# handler dispatch
# ---------------------------------------------------------------------------


def test_handler_unknown_action():
    r = h.handler({"action": "nope"})
    assert r["statusCode"] == 400
    body = _response_body(r)
    assert "unknown action" in body["error"]
    assert "actions" in body


def test_handler_missing_action():
    r = h.handler({})
    assert r["statusCode"] == 400


def test_handler_lists_known_actions():
    r = h.handler({"action": "bad"})
    body = _response_body(r)
    assert "merge" in body["actions"]
    assert "gc" in body["actions"]
    assert "breaker_probe" in body["actions"]
    assert "hot_merge" in body["actions"]


# ---------------------------------------------------------------------------
# action_merge
# ---------------------------------------------------------------------------


def _merge_con() -> FakeCon:
    return FakeCon(
        fetchall=[],
        fetchone_map={"ducklake_list_files": (4,), "count(*)": (4,)},
    )


def test_action_merge_ok():
    con = _merge_con()
    result = h.action_merge({}, con)
    assert result["ok"] is True
    assert result["action"] == "merge"
    assert "files_before" in result
    assert "files_after_merge" in result
    assert "elapsed_ms" in result


def test_action_merge_force_recreate_calls_create_tables():
    con = _merge_con()
    with patch.object(h.rt, "create_scd2_tables") as mock_create:
        h.action_merge({"force_recreate_tables": True}, con)
        mock_create.assert_called_once_with(con, force_recreate=True)


def test_action_merge_no_force_skips_create_tables():
    con = _merge_con()
    with patch.object(h.rt, "create_scd2_tables") as mock_create:
        h.action_merge({}, con)
        mock_create.assert_not_called()


def test_action_merge_emits_metrics():
    con = _merge_con()
    with patch.object(h, "_emit_maintenance_metric") as mock_emit:
        h.action_merge({}, con)
        metric_names = [call.args[0] for call in mock_emit.call_args_list]
        assert "MergeDurationMs" in metric_names
        assert "FilesBeforeMerge" in metric_names
        assert "FilesAfterMerge" in metric_names


# ---------------------------------------------------------------------------
# action_gc
# ---------------------------------------------------------------------------


def _gc_con() -> FakeCon:
    return FakeCon(
        fetchall=[],
        fetchone_map={
            "ducklake_list_files": (5,),
            "ducklake_cleanup_old_files": (1,),
            "ducklake_delete_orphaned_files": (0,),
            "ducklake_expire_snapshots": (2,),
            "count(*)": (5,),
        },
    )


def test_action_gc_ok():
    con = _gc_con()
    with patch.object(h.maint, "run_gc") as mock_gc:
        mock_gc.return_value = {
            "ok": True,
            "action": "gc",
            "tables": ["t1"],
            "files_before": 5,
            "files_after": 4,
            "snapshots_expired": 2,
            "files_cleaned": 1,
            "orphans_deleted": 0,
            "breaker_stats": {"breaker_tripped": False, "total_files": 5},
        }
        result = h.action_gc({}, con)
    assert result["ok"] is True
    assert result["action"] == "gc"


def test_action_gc_force_file_fraction():
    con = _gc_con()
    with patch.object(h.maint, "run_gc") as mock_gc:
        mock_gc.return_value = {
            "ok": True,
            "action": "gc",
            "tables": [],
            "files_before": 0,
            "files_after": 0,
            "snapshots_expired": 0,
            "files_cleaned": 0,
            "orphans_deleted": 0,
            "breaker_stats": {},
        }
        h.action_gc({"force_file_fraction": 0.5}, con)
        _, kwargs = mock_gc.call_args
        assert kwargs["file_fraction"] == 0.5


def test_action_gc_force_byte_budget():
    con = _gc_con()
    with patch.object(h.maint, "run_gc") as mock_gc:
        mock_gc.return_value = {
            "ok": True,
            "action": "gc",
            "tables": [],
            "files_before": 0,
            "files_after": 0,
            "snapshots_expired": 0,
            "files_cleaned": 0,
            "orphans_deleted": 0,
            "breaker_stats": {},
        }
        h.action_gc({"force_byte_budget": 1024}, con)
        _, kwargs = mock_gc.call_args
        assert kwargs["byte_budget"] == 1024


def test_action_gc_emits_metrics():
    con = _gc_con()
    with patch.object(h.maint, "run_gc") as mock_gc:
        mock_gc.return_value = {
            "ok": True,
            "action": "gc",
            "tables": [],
            "files_before": 3,
            "files_after": 2,
            "snapshots_expired": 1,
            "files_cleaned": 1,
            "orphans_deleted": 0,
            "breaker_stats": {},
        }
        with patch.object(h, "_emit_maintenance_metric") as mock_emit:
            h.action_gc({}, con)
            metric_names = [call.args[0] for call in mock_emit.call_args_list]
            assert "GcDurationMs" in metric_names
            assert "FilesBeforeGc" in metric_names
            assert "FilesAfterGc" in metric_names
            assert "MaintenanceBreakerTrip" in metric_names


# ---------------------------------------------------------------------------
# action_breaker_probe
# ---------------------------------------------------------------------------


def test_action_breaker_probe_raises_when_files_present():
    con = FakeCon()
    with patch.object(h.maint, "check_gc_breaker", side_effect=DuckLakeMaintenanceError("tripped")):
        with pytest.raises(DuckLakeMaintenanceError):
            h.action_breaker_probe({}, con)


def test_action_breaker_probe_returns_ok_when_no_deletable_files():
    con = FakeCon()
    with patch.object(h.maint, "check_gc_breaker", return_value={"breaker_tripped": False}):
        result = h.action_breaker_probe({}, con)
    assert result["breaker_tripped"] is False


def test_action_breaker_probe_does_not_emit_metric_directly():
    """H1 fix: action_breaker_probe must NOT emit MaintenanceBreakerTrip itself.
    The handler's outer DuckLakeMaintenanceError catch is the single emit point.
    """
    con = FakeCon()
    with patch.object(h.maint, "check_gc_breaker", side_effect=DuckLakeMaintenanceError("trip")):
        with patch.object(h, "_emit_maintenance_metric") as mock_emit:
            with pytest.raises(DuckLakeMaintenanceError):
                h.action_breaker_probe({}, con)
        assert mock_emit.call_count == 0, "action_breaker_probe must not emit metrics -- handler outer catch does it"


def test_handler_breaker_probe_emits_metric_exactly_once():
    """H1 fix: full handler path for breaker_probe should emit MaintenanceBreakerTrip exactly once."""
    with patch.object(h, "_open_connection") as mock_open:
        mock_con = MagicMock()
        mock_open.return_value = mock_con
        with patch.object(h.maint, "check_gc_breaker", side_effect=DuckLakeMaintenanceError("tripped")):
            with patch.object(h, "_emit_maintenance_metric") as mock_emit:
                r = h.handler({"action": "breaker_probe"})
    assert r["statusCode"] == 500
    trip_emits = [c for c in mock_emit.call_args_list if c.args[0] == "MaintenanceBreakerTrip"]
    assert len(trip_emits) == 1, f"MaintenanceBreakerTrip must be emitted exactly once, got {len(trip_emits)}"


# ---------------------------------------------------------------------------
# handler error mapping (loud-fail -> 4xx/5xx)
# ---------------------------------------------------------------------------


def test_handler_maintenance_error_maps_to_500():
    raiser = MagicMock(side_effect=DuckLakeMaintenanceError("breaker"))
    with patch.object(h, "_open_connection") as mock_open:
        mock_con = MagicMock()
        mock_open.return_value = mock_con
        with patch.dict(h._ACTIONS, {"merge": raiser}):
            with patch.object(h, "_emit_maintenance_metric"):
                r = h.handler({"action": "merge"})
    assert r["statusCode"] == 500
    body = _response_body(r)
    assert body["ok"] is False
    assert body["error_type"] == "breaker"
    assert body["breaker_tripped"] is True


def test_handler_version_mismatch_maps_to_500():
    raiser = MagicMock(side_effect=VersionMismatchError("bad version"))
    with patch.object(h, "_open_connection") as mock_open:
        mock_con = MagicMock()
        mock_open.return_value = mock_con
        with patch.dict(h._ACTIONS, {"merge": raiser}):
            r = h.handler({"action": "merge"})
    assert r["statusCode"] == 500
    body = _response_body(r)
    assert body["error_type"] == "version_mismatch"


def test_handler_runtime_error_maps_to_500():
    raiser = MagicMock(side_effect=DuckLakeRuntimeError("runtime fail"))
    with patch.object(h, "_open_connection") as mock_open:
        mock_con = MagicMock()
        mock_open.return_value = mock_con
        with patch.dict(h._ACTIONS, {"merge": raiser}):
            r = h.handler({"action": "merge"})
    assert r["statusCode"] == 500
    body = _response_body(r)
    assert body["error_type"] == "runtime"


def test_handler_connection_closed_on_success():
    with patch.object(h, "_open_connection") as mock_open:
        mock_con = MagicMock()
        mock_open.return_value = mock_con
        good = MagicMock(return_value={"ok": True, "action": "merge", "tables": [], "files_after_merge": 0, "elapsed_ms": 1.0})
        with patch.dict(h._ACTIONS, {"merge": good}):
            with patch.object(h, "_emit_maintenance_metric"):
                h.handler({"action": "merge"})
        mock_con.close.assert_called_once()


def test_handler_connection_closed_on_error():
    raiser = MagicMock(side_effect=DuckLakeMaintenanceError("trip"))
    with patch.object(h, "_open_connection") as mock_open:
        mock_con = MagicMock()
        mock_open.return_value = mock_con
        with patch.dict(h._ACTIONS, {"merge": raiser}):
            with patch.object(h, "_emit_maintenance_metric"):
                h.handler({"action": "merge"})
        mock_con.close.assert_called_once()


def test_handler_breaker_probe_via_handler_returns_500():
    raiser = MagicMock(side_effect=DuckLakeMaintenanceError("tripped"))
    with patch.object(h, "_open_connection") as mock_open:
        mock_con = MagicMock()
        mock_open.return_value = mock_con
        with patch.dict(h._ACTIONS, {"breaker_probe": raiser}):
            with patch.object(h, "_emit_maintenance_metric"):
                r = h.handler({"action": "breaker_probe"})
    assert r["statusCode"] == 500
    body = _response_body(r)
    assert body["breaker_tripped"] is True


# ---------------------------------------------------------------------------
# action_hot_merge
# ---------------------------------------------------------------------------


def _hot_merge_con() -> FakeCon:
    return FakeCon(
        fetchall=[],
        fetchone_map={"ducklake_list_files": (3,), "count(*)": (3,)},
    )


def test_action_hot_merge_ok():
    con = _hot_merge_con()
    with patch.object(h.maint, "run_hot_merge") as mock_hot:
        mock_hot.return_value = {
            "ok": True,
            "action": "hot_merge",
            "tables": ["t1"],
            "files_before": 3,
            "files_after": 2,
        }
        result = h.action_hot_merge({}, con)
    assert result["ok"] is True
    assert result["action"] == "hot_merge"
    assert "elapsed_ms" in result


def test_action_hot_merge_no_destructive_dispatch():
    """action_hot_merge must not call run_gc or any destructive function."""
    con = _hot_merge_con()
    with patch.object(h.maint, "run_hot_merge") as mock_hot:
        mock_hot.return_value = {
            "ok": True,
            "action": "hot_merge",
            "tables": [],
            "files_before": 0,
            "files_after": 0,
        }
        with patch.object(h.maint, "run_gc") as mock_gc:
            h.action_hot_merge({}, con)
    mock_gc.assert_not_called()


def test_action_hot_merge_emits_metrics():
    con = _hot_merge_con()
    with patch.object(h.maint, "run_hot_merge") as mock_hot:
        mock_hot.return_value = {
            "ok": True,
            "action": "hot_merge",
            "tables": [],
            "files_before": 3,
            "files_after": 2,
        }
        with patch.object(h, "_emit_maintenance_metric") as mock_emit:
            h.action_hot_merge({}, con)
    metric_names = [c.args[0] for c in mock_emit.call_args_list]
    assert "HotMergeDurationMs" in metric_names
    assert "FilesBeforeHotMerge" in metric_names
    assert "FilesAfterHotMerge" in metric_names


def test_action_hot_merge_force_recreate():
    con = _hot_merge_con()
    _ret = {"ok": True, "action": "hot_merge", "tables": [], "files_before": 0, "files_after": 0}
    with patch.object(h.maint, "run_hot_merge", return_value=_ret):
        with patch.object(h.rt, "create_scd2_tables") as mock_create:
            h.action_hot_merge({"force_recreate_tables": True}, con)
    mock_create.assert_called_once()


def test_handler_hot_merge_dispatch():
    with patch.object(h, "_open_connection") as mock_open:
        mock_con = MagicMock()
        mock_open.return_value = mock_con
        _ret = {"ok": True, "action": "hot_merge", "tables": [], "files_before": 0, "files_after": 0, "elapsed_ms": 1.0}
        good = MagicMock(return_value=_ret)
        with patch.dict(h._ACTIONS, {"hot_merge": good}):
            with patch.object(h, "_emit_maintenance_metric"):
                r = h.handler({"action": "hot_merge"})
    assert r["statusCode"] == 200


# ---------------------------------------------------------------------------
# Env-sourced breaker thresholds pass-through to run_gc
# ---------------------------------------------------------------------------


def test_env_gc_breaker_file_fraction_passed_to_run_gc(monkeypatch):
    """GC_BREAKER_FILE_FRACTION env var flows through the handler into run_gc."""
    monkeypatch.setenv("GC_BREAKER_FILE_FRACTION", "0.35")
    import importlib

    importlib.reload(h)

    con = _gc_con()
    with patch.object(h.maint, "run_gc") as mock_gc:
        mock_gc.return_value = {
            "ok": True,
            "action": "gc",
            "tables": [],
            "files_before": 0,
            "files_after": 0,
            "snapshots_expired": 0,
            "files_cleaned": 0,
            "orphans_deleted": 0,
            "breaker_stats": {},
        }
        h.action_gc({}, con)
        _, kwargs = mock_gc.call_args
    assert kwargs["file_fraction"] == pytest.approx(0.35)
    # Restore
    monkeypatch.delenv("GC_BREAKER_FILE_FRACTION", raising=False)
    importlib.reload(h)


def test_env_gc_breaker_bytes_passed_to_run_gc(monkeypatch):
    """GC_BREAKER_BYTES env var flows through the handler into run_gc."""
    monkeypatch.setenv("GC_BREAKER_BYTES", "5368709120")
    import importlib

    importlib.reload(h)

    con = _gc_con()
    with patch.object(h.maint, "run_gc") as mock_gc:
        mock_gc.return_value = {
            "ok": True,
            "action": "gc",
            "tables": [],
            "files_before": 0,
            "files_after": 0,
            "snapshots_expired": 0,
            "files_cleaned": 0,
            "orphans_deleted": 0,
            "breaker_stats": {},
        }
        h.action_gc({}, con)
        _, kwargs = mock_gc.call_args
    assert kwargs["byte_budget"] == 5368709120
    # Restore
    monkeypatch.delenv("GC_BREAKER_BYTES", raising=False)
    importlib.reload(h)


# ---------------------------------------------------------------------------
# T2.19 operational actions: catalog_reinit / seed / restore_drill + connectionless dispatch
# ---------------------------------------------------------------------------

_FULL_DSN = {"username": "u", "password": "p", "host": "hostx", "dbname": "neondb", "sslmode": "require"}


def test_handler_lists_new_operational_actions():
    body = _response_body(h.handler({"action": "bad"}))
    for action in ("catalog_reinit", "restore_drill"):
        assert action in body["actions"]
    # seed_ops_recommendations was removed at the 2026-06-09 recs sign-off (closed boundary).
    assert "seed_ops_recommendations" not in body["actions"]


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


def test_handler_connectionless_action_skips_open_connection():
    with (
        patch.object(h, "_open_connection") as open_mock,
        patch.dict(h._ACTIONS, {"catalog_reinit": MagicMock(return_value={"ok": True})}),
    ):
        r = h.handler({"action": "catalog_reinit", "data_path": "s3://b/ducklake/"})
    assert r["statusCode"] == 200
    open_mock.assert_not_called()


def test_handler_catalog_dr_error_maps_to_500():
    raiser = MagicMock(side_effect=h.catalog_dr.CatalogDrError("restore boom"))
    with patch.dict(h._ACTIONS, {"restore_drill": raiser}):
        r = h.handler({"action": "restore_drill"})
    assert r["statusCode"] == 500
    assert _response_body(r)["error_type"] == "catalog_dr"


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


def test_action_merge_ops_handler_does_not_open_smoke_connection():
    """Handler must NOT call _open_connection for merge_ops (action is connectionless)."""
    with (
        patch.object(h, "_open_connection") as open_mock,
        patch.dict(
            h._ACTIONS,
            {
                "merge_ops": MagicMock(
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
            },
        ),
    ):
        r = h.handler({"action": "merge_ops", "data_path": "s3://b/ducklake/", "meta_schema": "ducklake_ops"})
    assert r["statusCode"] == 200
    open_mock.assert_not_called()


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
    """The handler must NOT pre-open the smoke connection for catalog_stats (metadata-only, ATTACH-free)."""
    with (
        patch.object(h, "_open_connection") as open_mock,
        patch.object(h.rt, "fetch_dsn", return_value=_FULL_DSN),
        patch.object(h.maint, "catalog_stats", return_value={"ok": True, "catalog_metadata_bytes": 0}),
        patch.object(h, "_emit_maintenance_metric"),
    ):
        r = h.handler({"action": "catalog_stats", "meta_schema": "ducklake_ops"})
    assert r["statusCode"] == 200
    open_mock.assert_not_called()


def test_handler_catalog_stats_listed_in_actions():
    """catalog_stats must appear in the actions list returned on an unknown action."""
    body = _response_body(h.handler({"action": "bad"}))
    assert "catalog_stats" in body["actions"]


# ---------------------------------------------------------------------------
# action_clone_catalog (OQ.12 canary rehearsal -- Neon native branch, Decision 100)
# ---------------------------------------------------------------------------

_BRANCH_HOST = "br-fake-abc.us-east-2.aws.neon.tech"


def _clone_catalog_branch_patches(*, schemata_rows=None, open_raises=None):
    """Return a stack of patches for action_clone_catalog Neon-branch tests."""

    class _FakeCon:
        def execute(self, sql):
            return self

        def fetchall(self):
            if open_raises:
                raise open_raises
            return schemata_rows if schemata_rows is not None else [("public",)]

        def close(self):
            pass

    con_mock = _FakeCon()

    if open_raises:

        def _open_raises(*, dsn=None, data_path=None, meta_schema=None, extension_directory=None):
            raise open_raises

        open_patch = patch.object(h.rt, "open_connection", side_effect=_open_raises)
    else:
        open_patch = patch.object(h.rt, "open_connection", return_value=con_mock)

    return (
        patch.object(h.rt, "fetch_dsn", return_value=_FULL_DSN),
        open_patch,
    )


_PROD_DATA_PATH = "s3://b/ducklake/"


def test_action_clone_catalog_happy_path():
    """Happy path: branch_host + data_path in event, ATTACH succeeds, returns ok."""
    p = _clone_catalog_branch_patches()
    with p[0], p[1] as open_mock:
        result = h.action_clone_catalog(
            {"action": "clone_catalog", "branch_host": _BRANCH_HOST, "data_path": _PROD_DATA_PATH}, None
        )
    assert result["ok"] is True
    assert result["cloned"] is True
    assert result["meta_schema"] == "ducklake_ops"
    assert result["branch_host"] == _BRANCH_HOST
    call_kwargs = open_mock.call_args[1]
    assert call_kwargs["dsn"]["host"] == _BRANCH_HOST
    assert call_kwargs["dsn"]["dbname"] == _FULL_DSN["dbname"]
    assert call_kwargs["meta_schema"] == "ducklake_ops"
    assert call_kwargs["data_path"] == _PROD_DATA_PATH


def test_action_clone_catalog_branch_dsn_inherits_prod_credentials():
    """branch_dsn must use prod role/password/dbname with only host substituted."""
    p = _clone_catalog_branch_patches()
    with p[0], p[1] as open_mock:
        h.action_clone_catalog({"action": "clone_catalog", "branch_host": _BRANCH_HOST, "data_path": _PROD_DATA_PATH}, None)
    call_dsn = open_mock.call_args[1]["dsn"]
    assert call_dsn["host"] == _BRANCH_HOST
    assert call_dsn["dbname"] == _FULL_DSN["dbname"]
    assert call_dsn["username"] == _FULL_DSN["username"]
    assert call_dsn["password"] == _FULL_DSN["password"]  # pragma: allowlist secret -- fake fixture


def test_action_clone_catalog_missing_branch_host_loud_fails():
    """Missing branch_host in event raises CatalogDrError (Decision 55 loud-fail)."""
    with patch.object(h.rt, "fetch_dsn", return_value=_FULL_DSN):
        with pytest.raises(h.catalog_dr.CatalogDrError, match="branch_host is required"):
            h.action_clone_catalog({"action": "clone_catalog", "data_path": _PROD_DATA_PATH}, None)


def test_action_clone_catalog_missing_data_path_loud_fails():
    """Missing data_path in event raises CatalogDrError (Decision 55 loud-fail)."""
    with patch.object(h.rt, "fetch_dsn", return_value=_FULL_DSN):
        with pytest.raises(h.catalog_dr.CatalogDrError, match="data_path is required"):
            h.action_clone_catalog({"action": "clone_catalog", "branch_host": _BRANCH_HOST}, None)


def test_action_clone_catalog_invalid_data_path_loud_fails():
    """Non-s3:// data_path raises CatalogDrError (Decision 55 loud-fail)."""
    with patch.object(h.rt, "fetch_dsn", return_value=_FULL_DSN):
        with pytest.raises(h.catalog_dr.CatalogDrError, match="data_path is required"):
            h.action_clone_catalog({"action": "clone_catalog", "branch_host": _BRANCH_HOST, "data_path": "/local/path"}, None)


def test_action_clone_catalog_empty_schemata_loud_fails():
    """Empty information_schema.schemata result raises CatalogDrError (Decision 55)."""
    p = _clone_catalog_branch_patches(schemata_rows=[])
    with p[0], p[1]:
        with pytest.raises(h.catalog_dr.CatalogDrError, match="empty information_schema.schemata"):
            h.action_clone_catalog(
                {"action": "clone_catalog", "branch_host": _BRANCH_HOST, "data_path": _PROD_DATA_PATH}, None
            )


def test_action_clone_catalog_attach_failure_loud_fails():
    """open_connection raising DuckLakeRuntimeError propagates (Decision 55 loud-fail)."""
    p = _clone_catalog_branch_patches(open_raises=h.rt.DuckLakeRuntimeError("ATTACH fail"))
    with p[0], p[1]:
        with pytest.raises(h.rt.DuckLakeRuntimeError, match="ATTACH fail"):
            h.action_clone_catalog(
                {"action": "clone_catalog", "branch_host": _BRANCH_HOST, "data_path": _PROD_DATA_PATH}, None
            )


def test_action_clone_catalog_no_pg_dump_no_pg_restore():
    """Surface-retirement: pg_dump, pg_restore, CREATE DATABASE, DROP DATABASE must never be called."""
    pg_dump_calls = []
    pg_restore_calls = []
    p = _clone_catalog_branch_patches()
    with (
        p[0],
        p[1],
        patch.object(h.catalog_dr, "build_pg_dump_cmd", side_effect=lambda *a, **kw: pg_dump_calls.append(1) or []),
        patch.object(h.catalog_dr, "run_pg_restore", side_effect=lambda *a, **kw: pg_restore_calls.append(1)),
    ):
        h.action_clone_catalog({"action": "clone_catalog", "branch_host": _BRANCH_HOST, "data_path": _PROD_DATA_PATH}, None)
    assert pg_dump_calls == [], "build_pg_dump_cmd must not be called on the clone path (Decision 100)"
    assert pg_restore_calls == [], "run_pg_restore must not be called on the clone path (Decision 100)"


def test_action_clone_catalog_is_connectionless():
    """clone_catalog must appear in _CONNECTIONLESS_ACTIONS (handler skips open_connection call)."""
    assert "clone_catalog" in h._CONNECTIONLESS_ACTIONS


def test_action_clone_catalog_listed_in_actions():
    """clone_catalog must appear in _ACTIONS and in the handler's action list response."""
    assert "clone_catalog" in h._ACTIONS
    body = _response_body(h.handler({"action": "bad"}))
    assert "clone_catalog" in body["actions"]
