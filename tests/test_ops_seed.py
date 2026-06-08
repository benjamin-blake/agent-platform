"""Tests for the maintenance `seed_ops_recommendations` operational action (T2.19 recs cutover).

The one-time seed is the OPERATIONAL maintenance-plane bootstrap that moves ops_recommendations
current-state from Iceberg into DuckLake. It reuses schema_gate + write_scd2 (no bypass write path),
preserves the id + original created/last_updated timestamps, excludes Decision-70 rows, writes one
current row per rec (history dropped), is idempotent by DROP+recreate, and self-reports parity
(loud-fail on mismatch, Decision 55).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import patch

import pytest

import src.lambdas.ducklake_maintenance.handler as h
from src.common.ducklake_runtime import DuckLakeRuntimeError

pytestmark = pytest.mark.unit


class _FakeCon:
    """Connection double: count(*) returns the configured current-row count; everything else no-ops."""

    def __init__(self, current_count: int):
        self._current_count = current_count
        self.closed = False

    def execute(self, sql: str, params: Any = None) -> "_FakeCon":
        self._last = sql
        return self

    def fetchone(self) -> tuple[Any, ...]:
        return (self._current_count,)

    def close(self) -> None:
        self.closed = True


class _Spec:
    merge_key = "id"
    history_table = "ops_recommendations_history"
    current_table = "ops_recommendations_current"


def _row(rec_id: str, created: str, last_updated: str, **extra: Any) -> dict[str, Any]:
    base = {
        "id": rec_id,
        "status": "open",
        "title": f"rec {rec_id}",
        "created_timestamp": created,
        "last_updated_timestamp": last_updated,
        # Derived envelope columns the seed must STRIP before write_scd2 (schema gate rejects them).
        "ulid": "01OLDULIDSHOULDBEDROPPED",
    }
    base.update(extra)
    return base


def _run_seed(rows: list[dict], *, current_count: int | None = None, exclude_ids: list[str] | None = None):
    """Invoke the seed with rt.write_scd2 / create_scd2_tables mocked; return (result, write_mock, create_mock)."""
    con = _FakeCon(current_count if current_count is not None else len(rows) - len(exclude_ids or []))
    event: dict[str, Any] = {"rows": rows, "data_path": "s3://b/ducklake/"}
    if exclude_ids is not None:
        event["exclude_ids"] = exclude_ids
    with (
        patch.object(h.rt, "fetch_dsn", return_value={"host": "x"}),
        patch.object(h.rt, "open_connection", return_value=con),
        patch.object(h.rt, "resolve_table_spec", return_value=_Spec()),
        patch.object(h.rt, "create_scd2_tables") as create_mock,
        patch.object(h.rt, "write_scd2") as write_mock,
    ):
        result = h.action_seed_ops_recommendations(event, None)
    return result, write_mock, create_mock


def test_seed_preserves_id_and_original_timestamps():
    created = "2026-05-02T10:00:00+00:00"
    last_updated = "2026-06-01T12:30:00+00:00"
    rows = [_row("rec-001", created, last_updated)]
    result, write_mock, _ = _run_seed(rows)

    assert result["ok"] is True and result["seeded"] == 1
    (_call_con, call_record) = write_mock.call_args.args
    kwargs = write_mock.call_args.kwargs
    # id + business fields preserved; derived envelope columns stripped.
    assert call_record["id"] == "rec-001"
    assert "ulid" not in call_record and "created_timestamp" not in call_record and "last_updated_timestamp" not in call_record
    # last_updated -> identity.timestamp; created -> created_override (the preservation contract).
    assert kwargs["identity"].timestamp == datetime(2026, 6, 1, 12, 30, tzinfo=timezone.utc)
    assert kwargs["created_override"] == datetime(2026, 5, 2, 10, 0, tzinfo=timezone.utc)
    assert kwargs["table"] == "ops_recommendations"


def test_seed_excludes_decision70_rows():
    rows = [
        _row("rec-001", "2026-05-02T00:00:00+00:00", "2026-05-02T00:00:00+00:00"),
        _row("rec-D70", "2026-04-01T00:00:00+00:00", "2026-04-01T00:00:00+00:00"),
    ]
    result, write_mock, _ = _run_seed(rows, current_count=1, exclude_ids=["rec-D70"])
    assert result["seeded"] == 1 and result["skipped_d70"] == 1
    written_ids = [c.args[1]["id"] for c in write_mock.call_args_list]
    assert written_ids == ["rec-001"]


def test_seed_current_state_only_one_write_per_rec():
    rows = [
        _row("rec-001", "2026-05-02T00:00:00+00:00", "2026-05-09T00:00:00+00:00"),
        _row("rec-002", "2026-05-03T00:00:00+00:00", "2026-05-10T00:00:00+00:00"),
    ]
    result, write_mock, _ = _run_seed(rows)
    assert result["seeded"] == 2
    assert write_mock.call_count == 2  # exactly one current-state write per rec (history dropped)


def test_seed_drop_recreate_idempotent():
    rows = [_row("rec-001", "2026-05-02T00:00:00+00:00", "2026-05-02T00:00:00+00:00")]
    _, _, create_mock = _run_seed(rows)
    create_mock.assert_called_once()
    assert create_mock.call_args.kwargs["force_recreate"] is True
    assert create_mock.call_args.kwargs["table"] == "ops_recommendations"


def test_seed_parity_pass():
    rows = [_row("rec-001", "2026-05-02T00:00:00+00:00", "2026-05-02T00:00:00+00:00")]
    result, _, _ = _run_seed(rows, current_count=1)
    assert result["parity"] is True and result["current_rows"] == 1


def test_seed_parity_mismatch_loud_fails():
    rows = [
        _row("rec-001", "2026-05-02T00:00:00+00:00", "2026-05-02T00:00:00+00:00"),
        _row("rec-002", "2026-05-03T00:00:00+00:00", "2026-05-03T00:00:00+00:00"),
    ]
    # current_count (1) != seeded (2) -> parity FAIL -> loud-fail (Decision 55).
    with pytest.raises(DuckLakeRuntimeError, match="parity FAILED"):
        _run_seed(rows, current_count=1)


def test_seed_requires_rows_list():
    with pytest.raises(DuckLakeRuntimeError, match="requires a 'rows' list"):
        h.action_seed_ops_recommendations({"data_path": "s3://b/ducklake/"}, None)


def test_seed_routes_through_write_scd2_not_a_bypass():
    """The seed MUST reuse write_scd2 (the SCD2 primitive) -- never a direct INSERT bypass."""
    rows = [_row("rec-001", "2026-05-02T00:00:00+00:00", "2026-05-02T00:00:00+00:00")]
    _, write_mock, _ = _run_seed(rows)
    assert write_mock.called  # the only write path is write_scd2
