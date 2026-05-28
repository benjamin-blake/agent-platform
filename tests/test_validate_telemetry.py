"""Tests for scripts/validate_telemetry.py -- mocked Athena interactions."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from scripts.telemetry_schemas import (
    TELEMETRY_TABLE_NAMES,
    get_all_columns,
    get_required_columns,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_athena_client():
    """Return a mock Athena client with controllable query responses."""
    client = MagicMock()
    client.start_query_execution.return_value = {"QueryExecutionId": "test-qid-001"}
    client.get_query_execution.return_value = {"QueryExecution": {"Status": {"State": "SUCCEEDED"}}}
    return client


def _make_query_results(headers: list[str], rows: list[list[str]]) -> dict:
    """Build a mock get_query_results response."""
    header_row = {"Data": [{"VarCharValue": h} for h in headers]}
    data_rows = [{"Data": [{"VarCharValue": v} for v in row]} for row in rows]
    return {"ResultSet": {"Rows": [header_row] + data_rows}}


# ---------------------------------------------------------------------------
# TestSchemaHelpers (Step 1 acceptance)
# ---------------------------------------------------------------------------


class TestSchemaHelpers:
    """Test get_all_columns and get_required_columns helpers."""

    def test_get_all_columns_returns_list(self):
        cols = get_all_columns("telemetry_sessions")
        assert isinstance(cols, list)
        assert len(cols) > 0
        assert "session_id" in cols

    def test_get_all_columns_ordered(self):
        cols = get_all_columns("telemetry_sessions")
        # session_id should be first (it's the first field in the dataclass)
        assert cols[0] == "session_id"

    def test_get_all_columns_all_tables(self):
        for table in TELEMETRY_TABLE_NAMES:
            cols = get_all_columns(table)
            assert len(cols) > 0, f"Table {table} returned no columns"

    def test_get_all_columns_unknown_table(self, caplog):
        cols = get_all_columns("nonexistent_table")
        assert cols == []
        assert "unknown table" in caplog.text

    def test_get_required_columns_returns_list(self):
        cols = get_required_columns("telemetry_sessions")
        assert isinstance(cols, list)
        assert "session_id" in cols
        assert "workflow" in cols

    def test_get_required_columns_subset_of_all(self):
        for table in TELEMETRY_TABLE_NAMES:
            required = set(get_required_columns(table))
            all_cols = set(get_all_columns(table))
            assert required.issubset(all_cols)

    def test_get_required_columns_unknown_table(self, caplog):
        cols = get_required_columns("nonexistent_table")
        assert cols == []
        assert "unknown table" in caplog.text


# ---------------------------------------------------------------------------
# TestSchemaIntegrity (Layer 1)
# ---------------------------------------------------------------------------


class TestSchemaIntegrity:
    """Test check_schema_integrity with mocked Athena."""

    def test_dry_run_no_athena(self):
        from scripts.validate_telemetry import check_schema_integrity

        result = check_schema_integrity(client=None)
        assert len(result) == 7
        for table, data in result.items():
            assert data["athena_columns"] is None
            assert data["match"] is None
            assert data["python_count"] > 0

    def test_exact_match(self, mock_athena_client):
        from scripts.validate_telemetry import check_schema_integrity

        python_cols = get_all_columns("telemetry_sessions")
        # Mock SHOW COLUMNS to return exactly the Python columns
        mock_athena_client.get_query_results.return_value = _make_query_results(["column"], [[col] for col in python_cols])

        result = check_schema_integrity(client=mock_athena_client, tables=["telemetry_sessions"])
        assert result["telemetry_sessions"]["match"] is True
        assert result["telemetry_sessions"]["missing_in_athena"] == []
        assert result["telemetry_sessions"]["extra_in_athena"] == []

    def test_missing_columns(self, mock_athena_client):
        from scripts.validate_telemetry import check_schema_integrity

        python_cols = get_all_columns("telemetry_sessions")
        # Return only a subset
        mock_athena_client.get_query_results.return_value = _make_query_results(["column"], [[col] for col in python_cols[:5]])

        result = check_schema_integrity(client=mock_athena_client, tables=["telemetry_sessions"])
        assert result["telemetry_sessions"]["match"] is False
        assert len(result["telemetry_sessions"]["missing_in_athena"]) > 0

    def test_extra_columns(self, mock_athena_client):
        from scripts.validate_telemetry import check_schema_integrity

        python_cols = get_all_columns("telemetry_sessions")
        extra = python_cols + ["extra_col_1", "extra_col_2"]
        mock_athena_client.get_query_results.return_value = _make_query_results(["column"], [[col] for col in extra])

        result = check_schema_integrity(client=mock_athena_client, tables=["telemetry_sessions"])
        assert result["telemetry_sessions"]["match"] is False
        assert "extra_col_1" in result["telemetry_sessions"]["extra_in_athena"]


# ---------------------------------------------------------------------------
# TestPopulationCoverage (Layer 2)
# ---------------------------------------------------------------------------


class TestPopulationCoverage:
    """Test check_population_coverage with mocked Athena."""

    def test_full_population(self, mock_athena_client):
        from scripts.validate_telemetry import check_population_coverage

        all_cols = get_all_columns("telemetry_sessions")
        # Build response: total_rows=100, all columns have 100 non-null
        headers = ["total_rows"] + [f"{col}_count" for col in all_cols]
        values = ["100"] + ["100"] * len(all_cols)
        mock_athena_client.get_query_results.return_value = _make_query_results(headers, [values])

        result = check_population_coverage(client=mock_athena_client, tables=["telemetry_sessions"])
        table_data = result["telemetry_sessions"]
        assert table_data["total_rows"] == 100
        assert table_data["verdict"] == "PASS"
        # All required columns should be PASS
        for col, data in table_data["columns"].items():
            if data["required"]:
                assert data["status"] == "PASS"

    def test_empty_table(self, mock_athena_client):
        from scripts.validate_telemetry import check_population_coverage

        all_cols = get_all_columns("telemetry_sessions")
        headers = ["total_rows"] + [f"{col}_count" for col in all_cols]
        values = ["0"] + ["0"] * len(all_cols)
        mock_athena_client.get_query_results.return_value = _make_query_results(headers, [values])

        result = check_population_coverage(client=mock_athena_client, tables=["telemetry_sessions"])
        table_data = result["telemetry_sessions"]
        assert table_data["total_rows"] == 0
        assert table_data["verdict"] == "FAIL"

    def test_partial_population(self, mock_athena_client):
        from scripts.validate_telemetry import check_population_coverage

        all_cols = get_all_columns("telemetry_sessions")
        headers = ["total_rows"] + [f"{col}_count" for col in all_cols]
        # Most columns populated, but one required column is 0
        values = ["100"]
        for col in all_cols:
            if col == "session_id":
                values.append("0")  # This required column is empty
            else:
                values.append("100")
        mock_athena_client.get_query_results.return_value = _make_query_results(headers, [values])

        result = check_population_coverage(client=mock_athena_client, tables=["telemetry_sessions"])
        table_data = result["telemetry_sessions"]
        assert table_data["verdict"] == "FAIL"
        assert table_data["columns"]["session_id"]["status"] == "FAIL"

    def test_query_failure_returns_fail(self, mock_athena_client):
        from scripts.validate_telemetry import check_population_coverage

        # Simulate query failure: get_query_results returns no data rows
        mock_athena_client.get_query_results.return_value = {"ResultSet": {"Rows": []}}

        result = check_population_coverage(client=mock_athena_client, tables=["telemetry_sessions"])
        assert result["telemetry_sessions"]["verdict"] == "FAIL"


# ---------------------------------------------------------------------------
# TestFKIntegrity (Layer 3)
# ---------------------------------------------------------------------------


class TestFKIntegrity:
    """Test check_fk_integrity with mocked Athena."""

    def test_no_orphans(self, mock_athena_client):
        from scripts.validate_telemetry import check_fk_integrity

        mock_athena_client.get_query_results.return_value = _make_query_results(["orphan_count"], [["0"]])

        result = check_fk_integrity(client=mock_athena_client)
        assert len(result) >= 4
        for rel, data in result.items():
            assert data["status"] == "PASS"
            assert data["orphan_count"] == 0

    def test_with_orphans(self, mock_athena_client):
        from scripts.validate_telemetry import check_fk_integrity

        mock_athena_client.get_query_results.return_value = _make_query_results(["orphan_count"], [["5"]])

        result = check_fk_integrity(client=mock_athena_client)
        for rel, data in result.items():
            assert data["status"] == "WARN"
            assert data["orphan_count"] == 5


# ---------------------------------------------------------------------------
# TestViewCheck
# ---------------------------------------------------------------------------


class TestViewCheck:
    """Test check_views with mocked Athena."""

    def test_views_with_rows(self, mock_athena_client):
        from scripts.validate_telemetry import check_views

        mock_athena_client.get_query_results.return_value = _make_query_results(["row_count"], [["42"]])

        result = check_views(client=mock_athena_client)
        assert len(result) == 7
        for view, data in result.items():
            assert data["status"] == "PASS"
            assert data["row_count"] == 42

    def test_views_empty(self, mock_athena_client):
        from scripts.validate_telemetry import check_views

        mock_athena_client.get_query_results.return_value = _make_query_results(["row_count"], [["0"]])

        result = check_views(client=mock_athena_client)
        for view, data in result.items():
            assert data["status"] == "WARN"
            assert data["row_count"] == 0


# ---------------------------------------------------------------------------
# TestDryRun
# ---------------------------------------------------------------------------


class TestDryRun:
    """Test that dry-run mode does not call Athena."""

    @patch("scripts.validate_telemetry._get_athena_client")
    def test_dry_run_no_athena_calls(self, mock_get_client, tmp_path):
        from scripts.validate_telemetry import main

        output = tmp_path / "report.json"
        exit_code = main(["--dry-run", "--output", str(output)])
        assert exit_code == 0
        mock_get_client.assert_not_called()
        assert output.exists()

    @patch("scripts.validate_telemetry._get_athena_client")
    def test_dry_run_report_has_schema_drift(self, mock_get_client, tmp_path):
        import json

        from scripts.validate_telemetry import main

        output = tmp_path / "report.json"
        main(["--dry-run", "--output", str(output)])
        report = json.loads(output.read_text())
        assert "schema_drift" in report
        assert len(report["schema_drift"]) == 7


# ---------------------------------------------------------------------------
# TestReportGeneration
# ---------------------------------------------------------------------------


class TestReportGeneration:
    """Test JSON report structure."""

    @patch("scripts.validate_telemetry._get_athena_client")
    @patch("scripts.validate_telemetry._run_athena_query")
    def test_full_report_structure(self, mock_query, mock_client, tmp_path):
        import json

        from scripts.validate_telemetry import main

        # Mock all queries to return reasonable data
        all_cols = get_all_columns("telemetry_sessions")
        headers = ["total_rows"] + [f"{col}_count" for col in all_cols]
        values = ["10"] + ["10"] * len(all_cols)

        mock_query.return_value = [dict(zip(headers, values))]
        mock_client.return_value = MagicMock()

        output = tmp_path / "report.json"
        main(["--profile", "test", "--output", str(output)])
        report = json.loads(output.read_text())

        assert "schema_drift" in report
        assert "tables" in report
        assert "fk_checks" in report
        assert "views" in report
        assert "timestamp" in report


# ---------------------------------------------------------------------------
# TestExitCode
# ---------------------------------------------------------------------------


class TestExitCode:
    """Test exit code logic."""

    def test_exit_0_when_all_pass(self):
        from scripts.validate_telemetry import _determine_exit_code

        population = {
            "telemetry_sessions": {
                "columns": {
                    "session_id": {"required": True, "status": "PASS"},
                    "branch": {"required": False, "status": "OK"},
                }
            }
        }
        assert _determine_exit_code(population) == 0

    def test_exit_1_when_required_fails(self):
        from scripts.validate_telemetry import _determine_exit_code

        population = {
            "telemetry_sessions": {
                "columns": {
                    "session_id": {"required": True, "status": "FAIL"},
                    "branch": {"required": False, "status": "OK"},
                }
            }
        }
        assert _determine_exit_code(population) == 1

    def test_exit_0_when_only_optional_warns(self):
        from scripts.validate_telemetry import _determine_exit_code

        population = {
            "telemetry_sessions": {
                "columns": {
                    "session_id": {"required": True, "status": "PASS"},
                    "branch": {"required": False, "status": "WARN"},
                }
            }
        }
        assert _determine_exit_code(population) == 0
