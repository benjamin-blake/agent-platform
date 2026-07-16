"""DuckDBIcebergReader (pyiceberg-on-Iceberg) unit-test concern of src/common/iceberg_reader.py
(rec-2709 Wave 11). All I/O mocked; builds real pyarrow tables.

HEAVY-DEP MARKER MODULE: carries a module-level `import pyarrow as pa` -- the real, load-bearing
import the arrow helpers use (pa.table(...)) AND the fast-tier collectability marker (pyarrow is
excluded from requirements-fast.txt, so --collect-only fails and the fast tier proactively defers
this module, exactly as the monolith's module-level pyarrow import did).

Split from tests/test_iceberg_reader.py (VERBATIM move).
"""

from __future__ import annotations

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
