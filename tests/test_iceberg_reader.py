"""Tests for src/common/iceberg_reader.py.

Unit tests (mocked): pushdown args, SCD2 ROW_NUMBER dedup, priority-queue
correlated-subquery, snapshot pinning, empty-table graceful degradation.

Parity tests (integration, require warehouse credentials): DuckDB reader
vs Athena _current view row-for-row on a pinned snapshot for each ops table.
"""

from __future__ import annotations

import functools
from typing import Any
from unittest.mock import MagicMock, patch

import pyarrow as pa
import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_arrow_recs(*rows: dict) -> pa.Table:
    """Build a minimal ops_recommendations-shaped Arrow Table from dicts."""
    if not rows:
        schema = pa.schema(
            [
                pa.field("id", pa.string()),
                pa.field("status", pa.string()),
                pa.field("title", pa.string()),
                pa.field("last_updated_timestamp", pa.string()),
            ]
        )
        return pa.table(
            {"id": [], "status": [], "title": [], "last_updated_timestamp": []},
            schema=schema,
        )
    columns: dict[str, list] = {}
    for row in rows:
        for k, v in row.items():
            columns.setdefault(k, []).append(v)
    return pa.table(columns)


def _make_arrow_pq(*rows: dict) -> pa.Table:
    """Build a minimal ops_priority_queue-shaped Arrow Table."""
    if not rows:
        return pa.table(
            {"queue_run_id": [], "rec_id": [], "rank": [], "last_updated_timestamp": []},
        )
    columns: dict[str, list] = {}
    for row in rows:
        for k, v in row.items():
            columns.setdefault(k, []).append(v)
    return pa.table(columns)


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------


class TestDuckDBIcebergReader:
    """Unit tests for DuckDBIcebergReader (all I/O mocked)."""

    def _make_reader(self) -> Any:
        from src.common.iceberg_reader import DuckDBIcebergReader

        return DuckDBIcebergReader()

    def test_import_and_instantiate(self) -> None:
        """DuckDBIcebergReader and Reader protocol are importable."""
        from src.common.iceberg_reader import DuckDBIcebergReader, Reader  # noqa: F401

        r = DuckDBIcebergReader()
        assert r is not None

    def test_scan_args_pushdown(self) -> None:
        """current_state() passes row_filter and selected_fields into pyiceberg .scan()."""
        reader = self._make_reader()

        mock_scan = MagicMock()
        arrow_table = _make_arrow_recs(
            {"id": "rec-001", "status": "open", "title": "T1", "last_updated_timestamp": "2026-01-01T00:00:00Z"},
        )
        mock_scan.to_arrow.return_value = arrow_table

        mock_iceberg_table = MagicMock()
        mock_iceberg_table.scan.return_value = mock_scan

        mock_catalog = MagicMock()
        mock_catalog.load_table.return_value = mock_iceberg_table

        reader._catalog_instance = mock_catalog

        rows = reader.current_state(
            "ops_recommendations",
            row_filter="status = 'open'",
            selected_fields=("id", "status", "title"),
        )

        mock_iceberg_table.scan.assert_called_once_with(
            row_filter="status = 'open'",
            selected_fields=("id", "status", "title"),
        )
        assert len(rows) == 1
        assert rows[0]["id"] == "rec-001"

    def test_scan_args_snapshot_id_passed(self) -> None:
        """current_state() passes snapshot_id into pyiceberg .scan()."""
        reader = self._make_reader()

        mock_scan = MagicMock()
        mock_scan.to_arrow.return_value = _make_arrow_recs(
            {"id": "rec-001", "status": "open", "title": "T", "last_updated_timestamp": "2026-01-01T00:00:00Z"},
        )
        mock_iceberg_table = MagicMock()
        mock_iceberg_table.scan.return_value = mock_scan
        reader._catalog_instance = MagicMock()
        reader._catalog_instance.load_table.return_value = mock_iceberg_table

        reader.current_state("ops_recommendations", snapshot_id=999)

        call_kwargs = mock_iceberg_table.scan.call_args[1]
        assert call_kwargs.get("snapshot_id") == 999

    def test_current_state_scd2_keeps_latest_version(self) -> None:
        """current_state() applies ROW_NUMBER dedup: latest last_updated_timestamp wins."""
        reader = self._make_reader()

        arrow_table = _make_arrow_recs(
            {"id": "rec-001", "status": "open", "title": "V1", "last_updated_timestamp": "2026-01-01T00:00:00"},
            {"id": "rec-001", "status": "closed", "title": "V2", "last_updated_timestamp": "2026-06-01T00:00:00"},
            {"id": "rec-002", "status": "open", "title": "Only", "last_updated_timestamp": "2026-03-15T00:00:00"},
        )

        mock_scan = MagicMock()
        mock_scan.to_arrow.return_value = arrow_table
        mock_iceberg_table = MagicMock()
        mock_iceberg_table.scan.return_value = mock_scan
        reader._catalog_instance = MagicMock()
        reader._catalog_instance.load_table.return_value = mock_iceberg_table

        rows = reader.current_state("ops_recommendations")

        assert len(rows) == 2
        by_id = {r["id"]: r for r in rows}
        assert by_id["rec-001"]["title"] == "V2", "Should keep the latest version"
        assert by_id["rec-001"]["status"] == "closed"
        assert by_id["rec-002"]["title"] == "Only"

    def test_current_state_priority_queue_correlated_subquery(self) -> None:
        """current_state() for ops_priority_queue returns all entries from the latest run."""
        reader = self._make_reader()

        arrow_table = _make_arrow_pq(
            {"queue_run_id": "run-001", "rec_id": "rec-A", "rank": 1, "last_updated_timestamp": "2026-01-01T00:00:00"},
            {"queue_run_id": "run-001", "rec_id": "rec-B", "rank": 2, "last_updated_timestamp": "2026-01-01T00:00:00"},
            {"queue_run_id": "run-002", "rec_id": "rec-C", "rank": 1, "last_updated_timestamp": "2026-06-01T00:00:00"},
            {"queue_run_id": "run-002", "rec_id": "rec-D", "rank": 2, "last_updated_timestamp": "2026-06-01T00:00:00"},
        )

        mock_scan = MagicMock()
        mock_scan.to_arrow.return_value = arrow_table
        mock_iceberg_table = MagicMock()
        mock_iceberg_table.scan.return_value = mock_scan
        reader._catalog_instance = MagicMock()
        reader._catalog_instance.load_table.return_value = mock_iceberg_table

        rows = reader.current_state("ops_priority_queue")

        assert len(rows) == 2, "Should return only entries from the latest run (run-002)"
        rec_ids = {r["rec_id"] for r in rows}
        assert rec_ids == {"rec-C", "rec-D"}

    def test_current_state_priority_queue_does_not_use_row_number(self) -> None:
        """Decision 70: ops_priority_queue must NOT use ROW_NUMBER dedup."""
        from src.common.iceberg_reader import _CORRELATED_SUBQUERY_TABLES

        assert "ops_priority_queue" in _CORRELATED_SUBQUERY_TABLES

    def test_empty_table_returns_empty_list(self) -> None:
        """current_state() returns [] when the Arrow table has 0 rows."""
        reader = self._make_reader()

        mock_scan = MagicMock()
        mock_scan.to_arrow.return_value = _make_arrow_recs()
        mock_iceberg_table = MagicMock()
        mock_iceberg_table.scan.return_value = mock_scan
        reader._catalog_instance = MagicMock()
        reader._catalog_instance.load_table.return_value = mock_iceberg_table

        rows = reader.current_state("ops_recommendations")
        assert rows == []

    def test_latest_snapshot_returns_id(self) -> None:
        """latest_snapshot() returns the snapshot_id of the current snapshot."""
        reader = self._make_reader()

        mock_snap = MagicMock()
        mock_snap.snapshot_id = 12345
        mock_iceberg_table = MagicMock()
        mock_iceberg_table.current_snapshot.return_value = mock_snap
        reader._catalog_instance = MagicMock()
        reader._catalog_instance.load_table.return_value = mock_iceberg_table

        assert reader.latest_snapshot("ops_recommendations") == 12345

    def test_latest_snapshot_none_when_table_empty(self) -> None:
        """latest_snapshot() returns None when current_snapshot() is None."""
        reader = self._make_reader()

        mock_iceberg_table = MagicMock()
        mock_iceberg_table.current_snapshot.return_value = None
        reader._catalog_instance = MagicMock()
        reader._catalog_instance.load_table.return_value = mock_iceberg_table

        assert reader.latest_snapshot("ops_recommendations") is None

    def test_latest_snapshot_returns_none_on_exception(self) -> None:
        """latest_snapshot() returns None (never raises) on any catalog exception."""
        reader = self._make_reader()
        reader._catalog_instance = MagicMock()
        reader._catalog_instance.load_table.side_effect = RuntimeError("catalog down")

        assert reader.latest_snapshot("ops_recommendations") is None

    def test_query_runs_sql_on_current_state(self) -> None:
        """query() runs the provided SQL against the current-state view."""
        reader = self._make_reader()

        arrow_table = _make_arrow_recs(
            {"id": "rec-001", "status": "open", "title": "CI failure", "last_updated_timestamp": "2026-06-01T00:00:00"},
            {"id": "rec-001", "status": "open", "title": "CI failure v2", "last_updated_timestamp": "2026-06-02T00:00:00"},
            {"id": "rec-002", "status": "closed", "title": "Other", "last_updated_timestamp": "2026-01-01T00:00:00"},
        )
        mock_scan = MagicMock()
        mock_scan.to_arrow.return_value = arrow_table
        mock_iceberg_table = MagicMock()
        mock_iceberg_table.scan.return_value = mock_scan
        reader._catalog_instance = MagicMock()
        reader._catalog_instance.load_table.return_value = mock_iceberg_table

        rows = reader.query(
            "ops_recommendations",
            "SELECT id, title FROM {tbl} WHERE status = ?",
            params=("open",),
        )

        assert rows is not None
        assert len(rows) == 1
        assert rows[0]["id"] == "rec-001"
        assert rows[0]["title"] == "CI failure v2", "query() should operate on deduped current-state"

    def test_query_uses_correlated_subquery_for_priority_queue(self) -> None:
        """query() applies correlated-subquery dedup for ops_priority_queue tables (Decision 70)."""
        reader = self._make_reader()

        arrow_table = _make_arrow_pq(
            {"queue_run_id": "run-old", "rec_id": "rec-A", "rank": 1, "last_updated_timestamp": "2026-01-01T00:00:00"},
            {"queue_run_id": "run-new", "rec_id": "rec-B", "rank": 1, "last_updated_timestamp": "2026-06-01T00:00:00"},
        )

        mock_scan = MagicMock()
        mock_scan.to_arrow.return_value = arrow_table
        mock_iceberg_table = MagicMock()
        mock_iceberg_table.scan.return_value = mock_scan
        reader._catalog_instance = MagicMock()
        reader._catalog_instance.load_table.return_value = mock_iceberg_table

        rows = reader.query("ops_priority_queue", "SELECT rec_id FROM {tbl}")

        assert rows is not None
        assert len(rows) == 1
        assert rows[0]["rec_id"] == "rec-B", "Only entries from the latest queue_run_id should be returned"

    def test_query_returns_none_on_exception(self) -> None:
        """query() returns None (never raises) on any failure."""
        reader = self._make_reader()
        reader._catalog_instance = MagicMock()
        reader._catalog_instance.load_table.side_effect = RuntimeError("catalog down")

        result = reader.query("ops_recommendations", "SELECT * FROM {tbl}")
        assert result is None

    def test_query_empty_table_returns_empty_list(self) -> None:
        """query() returns [] (not None) when the underlying table is empty."""
        reader = self._make_reader()

        mock_scan = MagicMock()
        mock_scan.to_arrow.return_value = _make_arrow_recs()
        mock_iceberg_table = MagicMock()
        mock_iceberg_table.scan.return_value = mock_scan
        reader._catalog_instance = MagicMock()
        reader._catalog_instance.load_table.return_value = mock_iceberg_table

        result = reader.query("ops_recommendations", "SELECT * FROM {tbl}")
        assert result == []

    def test_catalog_uses_profile_when_resolved(self) -> None:
        """_catalog() passes client.profile-name and s3.profile-name when profile resolves."""
        from src.common.iceberg_reader import DuckDBIcebergReader

        with patch("scripts.aws_profile.resolve_aws_profile", return_value="agent_platform"):
            with patch("pyiceberg.catalog.glue.GlueCatalog") as mock_glue_cls:
                mock_glue_cls.return_value = MagicMock()
                reader = DuckDBIcebergReader()
                reader._catalog()

        call_kwargs = mock_glue_cls.call_args[1]
        assert call_kwargs.get("client.profile-name") == "agent_platform"
        assert call_kwargs.get("s3.profile-name") == "agent_platform"

    def test_catalog_omits_profile_when_none(self) -> None:
        """_catalog() does NOT pass profile-name when resolve_aws_profile returns None (CI OIDC)."""
        from src.common.iceberg_reader import DuckDBIcebergReader

        with patch("scripts.aws_profile.resolve_aws_profile", return_value=None):
            with patch("pyiceberg.catalog.glue.GlueCatalog") as mock_glue_cls:
                mock_glue_cls.return_value = MagicMock()
                reader = DuckDBIcebergReader()
                reader._catalog()

        call_kwargs = mock_glue_cls.call_args[1]
        assert "client.profile-name" not in call_kwargs
        assert "s3.profile-name" not in call_kwargs

    def test_snapshot_pinning_reproducible(self) -> None:
        """Two calls with the same snapshot_id return identical results."""
        reader = self._make_reader()

        arrow_table = _make_arrow_recs(
            {"id": "rec-001", "status": "open", "title": "Pinned", "last_updated_timestamp": "2026-01-01T00:00:00"},
        )
        mock_scan = MagicMock()
        mock_scan.to_arrow.return_value = arrow_table
        mock_iceberg_table = MagicMock()
        mock_iceberg_table.scan.return_value = mock_scan
        reader._catalog_instance = MagicMock()
        reader._catalog_instance.load_table.return_value = mock_iceberg_table

        result_a = reader.current_state("ops_recommendations", snapshot_id=42)
        result_b = reader.current_state("ops_recommendations", snapshot_id=42)
        assert result_a == result_b

    def test_current_state_rejects_invalid_column_name(self) -> None:
        """current_state() raises ValueError when partition_by or order_by is not a safe identifier."""
        reader = self._make_reader()
        reader._catalog_instance = MagicMock()

        with pytest.raises(ValueError, match="partition_by"):
            reader.current_state("ops_recommendations", partition_by="id; DROP TABLE x")

        with pytest.raises(ValueError, match="order_by"):
            reader.current_state("ops_recommendations", order_by="ts OR 1=1")


# ---------------------------------------------------------------------------
# Parity tests (integration, require real warehouse credentials)
# ---------------------------------------------------------------------------


@functools.lru_cache(maxsize=1)
def _has_warehouse_credentials() -> bool:
    """Return True if pyiceberg can reach the Glue catalog and S3 data lake."""
    try:
        from src.common.iceberg_reader import DuckDBIcebergReader

        reader = DuckDBIcebergReader()
        snap = reader.latest_snapshot("ops_recommendations")
        return snap is not None
    except Exception:  # noqa: BLE001
        return False


def _fetch_athena_current(table_view: str, profile: str = "agent_platform") -> list[dict]:
    """Fetch all rows from an Athena _current view for parity comparison."""
    import time

    import boto3

    session = boto3.Session(profile_name=profile)
    athena = session.client("athena", region_name="eu-west-2")

    eid = athena.start_query_execution(
        QueryString=f"SELECT * FROM agent_platform.{table_view}",
        WorkGroup="agent-platform-production",
    )["QueryExecutionId"]

    for _ in range(60):
        time.sleep(2)
        resp = athena.get_query_execution(QueryExecutionId=eid)
        state = resp["QueryExecution"]["Status"]["State"]
        if state in ("SUCCEEDED", "FAILED", "CANCELLED"):
            break

    assert state == "SUCCEEDED", f"Athena query failed: {state}"

    rows: list[dict] = []
    header: list[str] = []
    paginator = athena.get_paginator("get_query_results")
    is_first_page = True

    for page in paginator.paginate(QueryExecutionId=eid):
        page_rows = page.get("ResultSet", {}).get("Rows", [])
        for i, raw_row in enumerate(page_rows):
            data = [col.get("VarCharValue", "") for col in raw_row.get("Data", [])]
            if is_first_page and i == 0:
                header = data
                is_first_page = False
                continue
            if not header:
                continue
            row = dict(zip(header, data))
            row.pop("row_num", None)
            row.pop("_rn", None)
            rows.append(row)

    return rows


@pytest.mark.integration
class TestWarehouseParity:
    """Row-for-row parity: DuckDB reader vs Athena _current view on a pinned snapshot."""

    @pytest.fixture(autouse=True)
    def _skip_if_no_warehouse(self, _allow_network_for_integration: None) -> None:
        """Skip the class when warehouse credentials are unavailable.

        Requests _allow_network_for_integration so the probe's own S3/Glue call
        runs only after sockets are restored by that fixture.
        """
        if not _has_warehouse_credentials():
            pytest.skip("warehouse credentials not available")

    def _reader(self):
        from src.common.iceberg_reader import DuckDBIcebergReader

        return DuckDBIcebergReader()

    def test_parity_ops_recommendations(self) -> None:
        """DuckDB reader matches Athena ops_recommendations_current row-for-row."""
        reader = self._reader()
        snap_id = reader.latest_snapshot("ops_recommendations")
        assert snap_id is not None, "ops_recommendations must have a snapshot"

        duckdb_rows = reader.current_state("ops_recommendations", snapshot_id=snap_id)
        athena_rows = _fetch_athena_current("ops_recommendations_current")

        assert len(duckdb_rows) > 0, "Expected at least one recommendation in warehouse"
        assert len(duckdb_rows) == len(athena_rows), (
            f"Row count mismatch: DuckDB={len(duckdb_rows)}, Athena={len(athena_rows)}"
        )

        duckdb_by_id = {str(r.get("id", "")): r for r in duckdb_rows}
        for athena_row in athena_rows:
            rec_id = athena_row.get("id", "")
            assert rec_id in duckdb_by_id, f"rec {rec_id!r} in Athena but not in DuckDB"
            ddb_row = duckdb_by_id[rec_id]
            assert str(ddb_row.get("status", "")) == str(athena_row.get("status", "")), f"status mismatch for {rec_id}"
            assert str(ddb_row.get("title", "")) == str(athena_row.get("title", "")), f"title mismatch for {rec_id}"

    def test_parity_ops_decisions(self) -> None:
        """DuckDB reader matches Athena ops_decisions_current row-for-row."""
        reader = self._reader()
        snap_id = reader.latest_snapshot("ops_decisions")
        assert snap_id is not None

        duckdb_rows = reader.current_state("ops_decisions", snapshot_id=snap_id)
        athena_rows = _fetch_athena_current("ops_decisions_current")

        assert len(duckdb_rows) > 0, "Expected at least one decision in warehouse"
        assert len(duckdb_rows) == len(athena_rows), (
            f"Row count mismatch: DuckDB={len(duckdb_rows)}, Athena={len(athena_rows)}"
        )

        duckdb_by_id = {str(r.get("id", "")): r for r in duckdb_rows}
        for athena_row in athena_rows:
            dec_id = athena_row.get("id", "")
            assert dec_id in duckdb_by_id, f"decision {dec_id!r} in Athena but not in DuckDB"

    def test_parity_ops_priority_queue(self) -> None:
        """DuckDB reader matches Athena ops_priority_queue_current row-for-row."""
        reader = self._reader()
        snap_id = reader.latest_snapshot("ops_priority_queue")
        assert snap_id is not None

        duckdb_rows = reader.current_state("ops_priority_queue", snapshot_id=snap_id)
        athena_rows = _fetch_athena_current("ops_priority_queue_current")

        assert len(duckdb_rows) == len(athena_rows), (
            f"Row count mismatch: DuckDB={len(duckdb_rows)}, Athena={len(athena_rows)}"
        )

        duckdb_rec_ids = {str(r.get("rec_id", "")) for r in duckdb_rows}
        athena_rec_ids = {str(r.get("rec_id", "")) for r in athena_rows}
        assert duckdb_rec_ids == athena_rec_ids, "rec_id sets differ"


# ---------------------------------------------------------------------------
# T2.19: DuckLakeReader + make_reader factory + ops_storage_backend flag
# ---------------------------------------------------------------------------


class _FakeResp:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


def _patch_dl_invoke(monkeypatch, resp: _FakeResp, captured: dict):
    """Patch the DuckLakeReader SigV4 plumbing (boto3 + requests + profile) for a canned response."""
    import src.common.iceberg_reader as ir

    monkeypatch.setenv("DUCKLAKE_READER_URL", "https://reader.example/")

    class _Creds:
        access_key = "AK"
        secret_key = "SK"  # noqa: S105 -- fake fixture  # pragma: allowlist secret
        token = None

        def get_frozen_credentials(self):
            return self

    class _Session:
        def __init__(self, profile_name=None):
            pass

        def get_credentials(self):
            return _Creds()

    import boto3
    import requests
    from botocore.auth import SigV4Auth

    monkeypatch.setattr(boto3, "Session", _Session)
    monkeypatch.setattr(SigV4Auth, "add_auth", lambda self, req: None)
    monkeypatch.setattr("scripts.aws_profile.resolve_aws_profile", lambda *a, **k: None)

    def _post(url, data=None, headers=None, timeout=None):
        captured["url"] = url
        captured["body"] = data
        return resp

    monkeypatch.setattr(requests, "post", _post)
    return ir


def test_ops_storage_backend_default_and_flag(monkeypatch):
    import src.common.iceberg_reader as ir

    monkeypatch.delenv("OPS_STORAGE_BACKEND", raising=False)
    assert ir.ops_storage_backend() == "iceberg"
    monkeypatch.setenv("OPS_STORAGE_BACKEND", "DuckLake")
    assert ir.ops_storage_backend() == "ducklake"


def test_make_reader_selects_by_flag(monkeypatch):
    import src.common.iceberg_reader as ir

    monkeypatch.setenv("OPS_STORAGE_BACKEND", "ducklake")
    assert isinstance(ir.make_reader(), ir.DuckLakeReader)
    monkeypatch.setenv("OPS_STORAGE_BACKEND", "iceberg")
    assert isinstance(ir.make_reader(), ir.DuckDBIcebergReader)


def test_ducklake_reader_current_state_no_filter(monkeypatch):
    captured: dict = {}
    ir = _patch_dl_invoke(monkeypatch, _FakeResp(payload={"rows": [{"id": "rec-1"}]}), captured)
    rows = ir.DuckLakeReader().current_state("ops_recommendations")
    assert rows == [{"id": "rec-1"}]
    import json as _json

    assert _json.loads(captured["body"])["action"] == "read_ops_current"


def test_ducklake_reader_current_state_row_filter_uses_query_ops(monkeypatch):
    captured: dict = {}
    ir = _patch_dl_invoke(monkeypatch, _FakeResp(payload={"rows": []}), captured)
    ir.DuckLakeReader().current_state("ops_recommendations", row_filter="id = 'rec-1'")
    import json as _json

    body = _json.loads(captured["body"])
    assert body["action"] == "query_ops"
    assert "WHERE id = 'rec-1'" in body["sql"]


def test_ducklake_reader_query_returns_none_on_error(monkeypatch):
    captured: dict = {}
    ir = _patch_dl_invoke(monkeypatch, _FakeResp(status_code=500, text="boom"), captured)
    assert ir.DuckLakeReader().query("ops_recommendations", "SELECT 1 FROM {tbl}") is None


def test_ducklake_reader_latest_snapshot_is_none():
    import src.common.iceberg_reader as ir

    assert ir.DuckLakeReader().latest_snapshot("ops_recommendations") is None


def test_ducklake_reader_url_loud_fail_when_unset(monkeypatch):
    import src.common.iceberg_reader as ir

    monkeypatch.delenv("DUCKLAKE_READER_URL", raising=False)
    monkeypatch.setattr("subprocess.run", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError()))
    with pytest.raises(RuntimeError, match="DUCKLAKE_READER_URL not set"):
        ir.DuckLakeReader()._reader_url()
