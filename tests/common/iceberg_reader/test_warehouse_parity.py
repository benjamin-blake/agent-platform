"""Warehouse-parity integration concern of src/common/iceberg_reader.py (rec-2709 Wave 11).

Row-for-row parity: DuckDB reader vs Athena _current view on a pinned snapshot for each ops
table. NO module-level heavy-dep marker: every test is @pytest.mark.integration, and the fast
tier runs pytest with `-m "not integration"`, so they are DESELECTED (not run). The lazy boto3 in
_fetch_athena_current is only reached by an integration test that has already skipped.

Split from tests/test_iceberg_reader.py (VERBATIM move).
"""

from __future__ import annotations

import functools

import pytest


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
