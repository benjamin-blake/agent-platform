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
