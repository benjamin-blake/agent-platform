import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from scripts.data_quality_runner import (
    Check,
    CheckResult,
    RunResult,
    _compile_column_test,
    _execute_check,
    _print_results,
    _save_latest_result,
    load_checks,
    main,
    run_checks,
)


@pytest.fixture
def sample_yaml(tmp_path):
    d = tmp_path / "config" / "data_quality"
    d.mkdir(parents=True)
    f = d / "test.yaml"
    content = {
        "database": "test_db",
        "athena_workgroup": "test_wg",
        "tables": {
            "table1": {
                "view_suffix": "_v",
                "row_count": {"min": 10, "severity": "error"},
                "recency": {"column": "ts", "error_after_hours": 24},
                "columns": {
                    "col1": {
                        "tests": [
                            "not_null",
                            "unique",
                            {"accepted_values": {"values": ["A", "B"], "severity": "warn"}},
                            {"relationships": {"to_table": "table2", "to_column": "id"}},
                            {"expression": {"sql": "col1 > 0", "description": "must be positive"}},
                            {"not_null": {"severity": "warn"}},
                            {"unique": {"severity": "error"}},
                        ]
                    }
                },
            }
        },
    }
    f.write_text(yaml.dump(content))
    return f


def test_check_dataclass():
    c = Check("t", "c", "type", "SELECT 1", "desc", "error")
    assert c.table == "t"
    assert c.column == "c"


def test_check_enforced_default():
    c = Check("t", "c", "type", "SELECT 1", "desc", "error")
    assert c.enforced is True


def test_check_enforced_false():
    c = Check("t", "c", "type", "SELECT 1", "desc", "error", enforced=False)
    assert c.enforced is False


def test_run_result_properties():
    c = Check("t", "c", "type", "SELECT 1", "desc", "error")
    results = [
        CheckResult(c, "PASS"),
        CheckResult(c, "FAIL"),
        CheckResult(c, "WARN"),
        CheckResult(c, "ERROR"),
        CheckResult(c, "SKIP"),
    ]
    rr = RunResult(results=results, verdict="FAIL", duration_seconds=10.0)
    assert rr.passed == 1
    assert rr.failed == 1
    assert rr.warned == 1
    assert rr.errored == 1
    assert rr.skipped == 1


def test_load_checks(sample_yaml):
    checks, metadata = load_checks(sample_yaml)
    assert metadata["database"] == "test_db"
    assert len(checks) == 9
    # Verify recency check
    recency_check = [c for c in checks if c.test_type == "recency"][0]
    assert "date_diff" in recency_check.sql


def test_load_checks_with_filter(sample_yaml):
    checks, _ = load_checks(sample_yaml, table_filter="table1")
    assert len(checks) == 9
    checks, _ = load_checks(sample_yaml, table_filter="nonexistent")
    assert len(checks) == 0


def test_compile_column_test_invalid():
    assert _compile_column_test("db.t", "t", "c", "unknown") is None
    assert _compile_column_test("db.t", "t", "c", {"unknown": {}}) is None


def test_execute_check_success():
    client = MagicMock()
    client.start_query_execution.return_value = {"QueryExecutionId": "q123"}
    client.get_query_execution.return_value = {"QueryExecution": {"Status": {"State": "SUCCEEDED"}}}
    client.get_query_results.return_value = {
        "ResultSet": {"Rows": [{"Data": [{"VarCharValue": "violation"}]}, {"Data": [{"VarCharValue": "0"}]}]}
    }

    check = Check("t", "c", "not_null", "SELECT...", "desc", "error")
    res = _execute_check(check, client, "wg", "db")
    assert res.verdict == "PASS"


def test_execute_check_failure():
    client = MagicMock()
    client.start_query_execution.return_value = {"QueryExecutionId": "q123"}
    client.get_query_execution.return_value = {"QueryExecution": {"Status": {"State": "SUCCEEDED"}}}
    client.get_query_results.return_value = {
        "ResultSet": {"Rows": [{"Data": [{"VarCharValue": "violation"}]}, {"Data": [{"VarCharValue": "5"}]}]}
    }

    check = Check("t", "c", "not_null", "SELECT...", "desc", "error")
    res = _execute_check(check, client, "wg", "db")
    assert res.verdict == "FAIL"
    assert res.violation_count == 5


def test_execute_check_enforced_false_error_severity_returns_unenforced_fail():
    """enforced=False + severity=error violations emit UNENFORCED_FAIL, not FAIL or WARN."""
    client = MagicMock()
    client.start_query_execution.return_value = {"QueryExecutionId": "q123"}
    client.get_query_execution.return_value = {"QueryExecution": {"Status": {"State": "SUCCEEDED"}}}
    client.get_query_results.return_value = {
        "ResultSet": {"Rows": [{"Data": [{"VarCharValue": "violation"}]}, {"Data": [{"VarCharValue": "5"}]}]}
    }

    check = Check("t", "c", "not_null", "SELECT...", "desc", "error", enforced=False)
    res = _execute_check(check, client, "wg", "db")
    assert res.verdict == "UNENFORCED_FAIL"
    assert res.violation_count == 5


def test_execute_check_enforced_false_warn_severity_returns_warn():
    """enforced=False + severity=warn violations remain WARN (purely informational)."""
    client = MagicMock()
    client.start_query_execution.return_value = {"QueryExecutionId": "q123"}
    client.get_query_execution.return_value = {"QueryExecution": {"Status": {"State": "SUCCEEDED"}}}
    client.get_query_results.return_value = {
        "ResultSet": {"Rows": [{"Data": [{"VarCharValue": "violation"}]}, {"Data": [{"VarCharValue": "3"}]}]}
    }

    check = Check("t", "c", "accepted_values", "SELECT...", "desc", "warn", enforced=False)
    res = _execute_check(check, client, "wg", "db")
    assert res.verdict == "WARN"
    assert res.violation_count == 3


def test_execute_check_enforced_true_error_severity_returns_fail():
    """enforced=True + severity=error violations emit FAIL (blocking)."""
    client = MagicMock()
    client.start_query_execution.return_value = {"QueryExecutionId": "q123"}
    client.get_query_execution.return_value = {"QueryExecution": {"Status": {"State": "SUCCEEDED"}}}
    client.get_query_results.return_value = {
        "ResultSet": {"Rows": [{"Data": [{"VarCharValue": "violation"}]}, {"Data": [{"VarCharValue": "2"}]}]}
    }

    check = Check("t", "c", "not_null", "SELECT...", "desc", "error", enforced=True)
    res = _execute_check(check, client, "wg", "db")
    assert res.verdict == "FAIL"
    assert res.violation_count == 2


def test_execute_check_start_error():
    client = MagicMock()
    client.start_query_execution.side_effect = Exception("boom")
    check = Check("t", "c", "not_null", "SELECT...", "desc", "error")
    res = _execute_check(check, client, "wg", "db")
    assert res.verdict == "ERROR"
    assert "boom" in res.detail


def test_execute_check_poll_and_succeed():
    client = MagicMock()
    client.start_query_execution.return_value = {"QueryExecutionId": "q123"}
    client.get_query_execution.side_effect = [
        {"QueryExecution": {"Status": {"State": "RUNNING"}}},
        {"QueryExecution": {"Status": {"State": "SUCCEEDED"}}},
    ]
    client.get_query_results.return_value = {
        "ResultSet": {"Rows": [{"Data": [{"VarCharValue": "v"}]}, {"Data": [{"VarCharValue": "0"}]}]}
    }

    with patch("time.sleep"):
        check = Check("t", "c", "not_null", "SELECT...", "desc", "error")
        res = _execute_check(check, client, "wg", "db")
        assert res.verdict == "PASS"


def test_execute_check_cancelled():
    client = MagicMock()
    client.start_query_execution.return_value = {"QueryExecutionId": "q123"}
    client.get_query_execution.return_value = {
        "QueryExecution": {"Status": {"State": "CANCELLED", "StateChangeReason": "user stop"}}
    }

    check = Check("t", "c", "not_null", "SELECT...", "desc", "error")
    res = _execute_check(check, client, "wg", "db")
    assert res.verdict == "ERROR"


def test_execute_check_timeout():
    client = MagicMock()
    client.start_query_execution.return_value = {"QueryExecutionId": "q123"}
    client.get_query_execution.return_value = {"QueryExecution": {"Status": {"State": "RUNNING"}}}

    with patch("scripts.data_quality_runner._MAX_POLL", 0.1), patch("time.sleep"):
        check = Check("t", "c", "not_null", "SELECT...", "desc", "error")
        res = _execute_check(check, client, "wg", "db")
        assert res.verdict == "ERROR"
        assert "timed out" in res.detail


def test_execute_check_poll_error():
    """Covers lines 363-364: Poll error."""
    client = MagicMock()
    client.start_query_execution.return_value = {"QueryExecutionId": "q123"}
    client.get_query_execution.side_effect = Exception("poll fail")
    check = Check("t", "c", "not_null", "SELECT...", "desc", "error")
    res = _execute_check(check, client, "wg", "db")
    assert res.verdict == "ERROR"
    assert "Poll error" in res.detail


def test_execute_check_read_results_error():
    """Covers lines 386-388: Read results error."""
    client = MagicMock()
    client.start_query_execution.return_value = {"QueryExecutionId": "q123"}
    client.get_query_execution.return_value = {"QueryExecution": {"Status": {"State": "SUCCEEDED"}}}
    client.get_query_results.side_effect = Exception("read fail")
    check = Check("t", "c", "not_null", "SELECT...", "desc", "error")
    res = _execute_check(check, client, "wg", "db")
    assert res.verdict == "ERROR"
    assert "Failed to read results" in res.detail


def test_execute_check_empty_results():
    """Covers line 386: violation_count = 0 when no data rows."""
    client = MagicMock()
    client.start_query_execution.return_value = {"QueryExecutionId": "q123"}
    client.get_query_execution.return_value = {"QueryExecution": {"Status": {"State": "SUCCEEDED"}}}
    client.get_query_results.return_value = {
        "ResultSet": {"Rows": [{"Data": [{"VarCharValue": "violation"}]}]}  # Only header
    }

    check = Check("t", "c", "not_null", "SELECT...", "desc", "error")
    res = _execute_check(check, client, "wg", "db")
    assert res.verdict == "PASS"
    assert res.violation_count == 0


def test_print_results_with_issues(capsys):
    """Covers lines 518-524: Print results issues loop."""
    check = Check(table="T", column="C", test_type="not_null", sql="S", description="N1", severity="error")
    results = [CheckResult(check=check, verdict="FAIL", violation_count=10, detail="10 violations")]
    rr = RunResult(results=results, verdict="FAIL", duration_seconds=1.2)
    _print_results(rr)
    captured = capsys.readouterr().out
    assert "[FAIL] N1" in captured
    assert "10 violations" in captured


def test_main_no_matching_filters():
    """Covers lines 589-590: No checks match filters."""
    with patch("scripts.data_quality_runner._DQ_DIR") as mock_dq_dir:
        mock_dq_dir.glob.return_value = [Path("test.yaml")]
        with patch("scripts.data_quality_runner.load_checks", return_value=([], {"database": "db"})):
            with patch("sys.argv", ["runner.py", "--table", "non_existent"]):
                assert main() == 0


def test_run_checks_dry_run():
    checks = [Check("t", "c", "type", "sql", "desc")]
    res = run_checks(checks, "wg", "db", dry_run=True)
    assert res.verdict == "SKIP"


def test_run_checks_with_issues():
    with patch("boto3.Session") as mock_session:
        mock_athena = MagicMock()
        mock_session.return_value.client.return_value = mock_athena
        with patch("scripts.data_quality_runner._execute_check") as mock_exec:
            mock_exec.side_effect = [
                CheckResult(Check("t", "c", "type", "sql", "desc"), "PASS"),
                CheckResult(Check("t", "c", "type", "sql", "desc"), "FAIL"),
                CheckResult(Check("t", "c", "type", "sql", "desc"), "ERROR"),
            ]
            checks = [Check("t", "c", "type", "sql", "desc")] * 3
            res = run_checks(checks, "wg", "db")
            assert res.verdict == "FAIL"


def test_run_checks_profile_arg():
    """profile_name arg takes precedence over all env vars."""
    with patch("boto3.Session") as mock_session:
        mock_session.return_value.client.return_value = MagicMock()
        with patch("scripts.data_quality_runner._execute_check") as mock_exec:
            mock_exec.return_value = CheckResult(Check("t", "c", "type", "sql", "desc"), "PASS")
            run_checks([Check("t", "c", "type", "sql", "desc")], "wg", "db", profile_name="my-profile")
    mock_session.assert_called_once_with(profile_name="my-profile")


def test_run_checks_profile_aws_env(monkeypatch):
    """Falls back to AWS_PROFILE env when profile_name is None."""
    monkeypatch.setenv("AWS_PROFILE", "env-profile")
    monkeypatch.delenv("AWS_DEFAULT_PROFILE", raising=False)
    with patch("boto3.Session") as mock_session:
        mock_session.return_value.client.return_value = MagicMock()
        with patch("scripts.data_quality_runner._execute_check") as mock_exec:
            mock_exec.return_value = CheckResult(Check("t", "c", "type", "sql", "desc"), "PASS")
            run_checks([Check("t", "c", "type", "sql", "desc")], "wg", "db")
    mock_session.assert_called_once_with(profile_name="env-profile")


def test_run_checks_profile_default_env(monkeypatch):
    """Falls back to AWS_DEFAULT_PROFILE when AWS_PROFILE is unset."""
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    monkeypatch.setenv("AWS_DEFAULT_PROFILE", "default-profile")
    with patch("boto3.Session") as mock_session:
        mock_session.return_value.client.return_value = MagicMock()
        with patch("scripts.data_quality_runner._execute_check") as mock_exec:
            mock_exec.return_value = CheckResult(Check("t", "c", "type", "sql", "desc"), "PASS")
            run_checks([Check("t", "c", "type", "sql", "desc")], "wg", "db")
    mock_session.assert_called_once_with(profile_name="default-profile")


def test_run_checks_profile_hard_default(monkeypatch):
    """Defaults to company-aws-profile when no env vars or arg are set."""
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    monkeypatch.delenv("AWS_DEFAULT_PROFILE", raising=False)
    with patch("boto3.Session") as mock_session:
        mock_session.return_value.client.return_value = MagicMock()
        with patch("scripts.data_quality_runner._execute_check") as mock_exec:
            mock_exec.return_value = CheckResult(Check("t", "c", "type", "sql", "desc"), "PASS")
            run_checks([Check("t", "c", "type", "sql", "desc")], "wg", "db")
    mock_session.assert_called_once_with(profile_name="company-aws-profile")


def test_print_results_json(capsys):
    c = Check("t", "c", "type", "sql", "desc")
    results = [CheckResult(c, "PASS")]
    rr = RunResult(results=results, verdict="PASS", duration_seconds=1.2)
    _print_results(rr, as_json=True)
    captured = capsys.readouterr().out
    data = json.loads(captured)
    assert data["verdict"] == "PASS"


def test_save_latest_result(tmp_path):
    with patch("scripts.data_quality_runner._ROOT", tmp_path):
        c = Check("t", "c", "type", "sql", "desc")
        rr = RunResult(results=[CheckResult(c, "PASS")], verdict="PASS", duration_seconds=1.2)
        _save_latest_result(rr)
        assert (tmp_path / "logs" / "debug" / "dq-latest.json").exists()


@patch("scripts.data_quality_runner._DQ_DIR")
@patch("scripts.data_quality_runner.load_checks")
@patch("scripts.data_quality_runner.run_checks")
def test_main_full(mock_run, mock_load, mock_dq_dir):
    mock_dq_dir.glob.return_value = [Path("test.yaml")]
    mock_load.return_value = ([Check("t", "c", "type", "sql", "desc")], {"database": "db", "athena_workgroup": "wg"})
    mock_run.return_value = RunResult(verdict="PASS")
    with patch("sys.argv", ["runner.py"]):
        assert main() == 0


@patch("scripts.data_quality_runner._DQ_DIR")
def test_main_no_files(mock_dq_dir):
    mock_dq_dir.glob.return_value = []
    with patch("sys.argv", ["runner.py"]):
        assert main() == 1


@patch("scripts.data_quality_runner.load_tombstones", return_value=[])
@patch("scripts.data_quality_runner._DQ_DIR")
@patch("scripts.data_quality_runner.load_checks")
def test_main_severity_error(mock_load, mock_dq_dir, _mock_tombstones):
    mock_dq_dir.glob.return_value = [Path("test.yaml")]
    checks = [
        Check("t", "c", "type", "sql", "desc", "error"),
        Check("t", "c", "type", "sql", "desc", "warn"),
    ]
    mock_load.return_value = (checks, {"database": "db", "athena_workgroup": "wg"})
    with patch("sys.argv", ["runner.py", "--severity", "error", "--dry-run"]):
        with patch("builtins.print") as mock_print:
            main()
            # Only error check printed (2 lines: desc and sql)
            assert mock_print.call_count == 2


@patch("scripts.data_quality_runner._DQ_DIR")
@patch("scripts.data_quality_runner.load_checks")
def test_main_severity_warn(mock_load, mock_dq_dir):
    mock_dq_dir.glob.return_value = [Path("test.yaml")]
    checks = [
        Check("t", "c", "type", "sql", "desc", "error"),
        Check("t", "c", "type", "sql", "desc", "warn"),
    ]
    mock_load.return_value = (checks, {"database": "db", "athena_workgroup": "wg"})
    with patch("sys.argv", ["runner.py", "--severity", "warn", "--dry-run"]):
        with patch("builtins.print") as mock_print:
            main()
            assert mock_print.call_count == 2


@patch("scripts.data_quality_runner._DQ_DIR")
@patch("scripts.data_quality_runner.load_checks")
def test_main_json(mock_load, mock_dq_dir):
    mock_dq_dir.glob.return_value = [Path("test.yaml")]
    mock_load.return_value = ([Check("t", "c", "type", "sql", "desc")], {"database": "db", "athena_workgroup": "wg"})
    with patch("scripts.data_quality_runner.run_checks") as mock_run:
        mock_run.return_value = RunResult(verdict="PASS")
        with patch("sys.argv", ["runner.py", "--json"]):
            with patch("builtins.print") as mock_print:
                main()
                # Check that print was called with JSON (one of the calls should be the JSON string)
                assert any("verdict" in str(args[0]) for args, kwargs in mock_print.call_args_list)


def test_run_checks_no_boto3():
    with patch.dict("sys.modules", {"boto3": None}):
        checks = [Check("t", "c", "type", "sql", "desc")]
        res = run_checks(checks, "wg", "db")
        assert res.verdict == "SKIP"


def test_main_cli_file_path():
    """Covers line 564: CLI --file argument path."""
    with patch("scripts.data_quality_runner.load_checks", return_value=([], {"database": "db"})) as mock_load:
        with patch("sys.argv", ["runner.py", "--file", "custom.yaml"]):
            main()
        mock_load.assert_called_once()
        assert "custom.yaml" in str(mock_load.call_args[0][0])


def test_run_checks_empty_list_returns_error():
    """Gap 1: run_checks with an empty check list must return verdict=ERROR, not PASS."""
    with patch("boto3.Session") as mock_session:
        mock_session.return_value.client.return_value = MagicMock()
        res = run_checks([], "wg", "db")
    assert res.verdict == "ERROR"
    assert len(res.results) == 0


def test_save_latest_result_zero_results_no_write(tmp_path):
    """Guard: _save_latest_result must not write when no checks were attempted."""
    with patch("scripts.data_quality_runner._ROOT", tmp_path):
        rr = RunResult(results=[], verdict="PASS", duration_seconds=0.0)
        _save_latest_result(rr)
    assert not (tmp_path / "logs" / "debug" / "dq-latest.json").exists()


def test_load_checks_enforced_from_yaml(tmp_path):
    """Loader reads enforced: false from dict-form YAML; bare-string defaults to True."""
    d = tmp_path / "config" / "data_quality"
    d.mkdir(parents=True)
    f = d / "test.yaml"
    content = {
        "database": "db",
        "athena_workgroup": "wg",
        "tables": {
            "tbl": {
                "row_count": {"min": 1, "enforced": False},
                "recency": {"column": "ts", "error_after_hours": 24, "enforced": True},
                "columns": {
                    "col": {
                        "tests": [
                            "not_null",
                            {"accepted_values": {"values": ["A"], "enforced": False}},
                            {"not_null": {"enforced": False}},
                        ]
                    }
                },
            }
        },
    }
    f.write_text(yaml.dump(content))
    checks, _ = load_checks(f)

    row_count_check = next(c for c in checks if c.test_type == "row_count")
    recency_check = next(c for c in checks if c.test_type == "recency")
    bare_not_null = next(c for c in checks if c.test_type == "not_null" and c.enforced is True)
    accepted_check = next(c for c in checks if c.test_type == "accepted_values")
    dict_not_null = next(c for c in checks if c.test_type == "not_null" and c.enforced is False)

    assert row_count_check.enforced is False
    assert recency_check.enforced is True
    assert bare_not_null.enforced is True
    assert accepted_check.enforced is False
    assert dict_not_null.enforced is False


def test_save_latest_result_checks_array(tmp_path):
    """_save_latest_result writes checks array with correct schema: table, column, test, verdict."""
    with patch("scripts.data_quality_runner._ROOT", tmp_path):
        c_table = Check("tbl", None, "row_count", "sql", "desc")
        c_col = Check("tbl", "col", "not_null", "sql", "desc")
        results = [
            CheckResult(c_table, "PASS"),
            CheckResult(c_col, "FAIL"),
        ]
        rr = RunResult(results=results, verdict="FAIL", duration_seconds=1.0)
        _save_latest_result(rr)

    data = json.loads((tmp_path / "logs" / "debug" / "dq-latest.json").read_text())
    assert "checks" in data
    assert len(data["checks"]) == 2

    table_entry = next(e for e in data["checks"] if e["test"] == "row_count")
    assert table_entry["table"] == "tbl"
    assert table_entry["column"] is None
    assert table_entry["verdict"] == "PASS"

    col_entry = next(e for e in data["checks"] if e["test"] == "not_null")
    assert col_entry["table"] == "tbl"
    assert col_entry["column"] == "col"
    assert col_entry["verdict"] == "FAIL"


def test_run_checks_enforced_false_advisory():
    """enforced=False FAIL does not produce FAIL aggregate; enforced=True FAIL does."""
    enforced_check = Check("t", "c", "not_null", "sql", "desc", enforced=True)
    unenforced_check = Check("t", "c", "unique", "sql", "desc", enforced=False)

    with patch("boto3.Session") as mock_session:
        mock_session.return_value.client.return_value = MagicMock()
        with patch("scripts.data_quality_runner._execute_check") as mock_exec:
            mock_exec.side_effect = [
                CheckResult(unenforced_check, "FAIL"),
            ]
            res = run_checks([unenforced_check], "wg", "db")
    assert res.verdict == "PASS"

    with patch("boto3.Session") as mock_session:
        mock_session.return_value.client.return_value = MagicMock()
        with patch("scripts.data_quality_runner._execute_check") as mock_exec:
            mock_exec.side_effect = [
                CheckResult(enforced_check, "FAIL"),
            ]
            res = run_checks([enforced_check], "wg", "db")
    assert res.verdict == "FAIL"


def test_check_exclude_before_default():
    c = Check("t", "c", "type", "SELECT 1", "desc")
    assert c.exclude_before is None


def test_load_checks_reads_exclude_before(tmp_path):
    d = tmp_path / "config" / "data_quality"
    d.mkdir(parents=True)
    f = d / "test.yaml"
    content = {
        "database": "db",
        "athena_workgroup": "wg",
        "tables": {
            "tbl": {
                "columns": {
                    "col": {
                        "tests": [
                            {"not_null": {"enforced": False, "exclude_before": "2026-01-01"}},
                        ]
                    }
                }
            }
        },
    }
    f.write_text(yaml.dump(content))
    checks, _ = load_checks(f)
    assert len(checks) == 1
    assert checks[0].exclude_before == "2026-01-01"


def test_compile_not_null_with_exclude_before():
    check = _compile_column_test(
        "db.tbl",
        "tbl",
        "col",
        {"not_null": {"enforced": False, "exclude_before": "2026-01-01"}},
    )
    assert check is not None
    assert "AND created_timestamp >= DATE('2026-01-01')" in check.sql
    assert check.exclude_before == "2026-01-01"


def test_compile_accepted_values_with_exclude_before():
    check = _compile_column_test(
        "db.tbl",
        "tbl",
        "col",
        {"accepted_values": {"values": ["A", "B"], "enforced": False, "exclude_before": "2026-01-01"}},
    )
    assert check is not None
    assert "NOT IN ('A', 'B')" in check.sql
    assert "AND created_timestamp >= DATE('2026-01-01')" in check.sql


def test_compile_unique_with_exclude_before():
    check = _compile_column_test(
        "db.tbl",
        "tbl",
        "col",
        {"unique": {"enforced": False, "exclude_before": "2026-01-01"}},
    )
    assert check is not None
    where_pos = check.sql.index("WHERE created_timestamp")
    group_pos = check.sql.index("GROUP BY")
    assert where_pos < group_pos
    assert "DATE('2026-01-01')" in check.sql


def test_compile_accepted_values_list_form():
    check = _compile_column_test("db.tbl", "tbl", "col", {"accepted_values": ["A", "B", "C"]})
    assert check is not None
    assert "NOT IN ('A', 'B', 'C')" in check.sql
    assert check.enforced is True
    assert check.severity == "error"


def test_compile_relationships_non_dict_returns_none():
    assert _compile_column_test("db.tbl", "tbl", "col", {"relationships": ["invalid"]}) is None


def test_compile_expression_non_dict_returns_none():
    assert _compile_column_test("db.tbl", "tbl", "col", {"expression": "not_a_dict"}) is None


@patch("scripts.data_quality_runner._DQ_DIR")
@patch("scripts.data_quality_runner.load_checks")
def test_main_conflicting_workgroup_returns_1(mock_load, mock_dq_dir):
    mock_dq_dir.glob.return_value = [Path("a.yaml"), Path("b.yaml")]
    mock_load.side_effect = [
        ([Check("t", "c", "type", "sql", "desc")], {"database": "db", "athena_workgroup": "wg-a"}),
        ([Check("t", "c", "type", "sql", "desc")], {"database": "db", "athena_workgroup": "wg-b"}),
    ]
    with patch("sys.argv", ["runner.py"]):
        assert main() == 1


def test_row_count_ignores_exclude_before_in_sql(tmp_path):
    d = tmp_path / "config" / "data_quality"
    d.mkdir(parents=True)
    f = d / "test.yaml"
    content = {
        "database": "db",
        "athena_workgroup": "wg",
        "tables": {
            "tbl": {
                "row_count": {"min": 1, "enforced": True, "exclude_before": "2026-01-01"},
            }
        },
    }
    f.write_text(yaml.dump(content))
    checks, _ = load_checks(f)
    rc = next(c for c in checks if c.test_type == "row_count")
    assert "created_timestamp" not in rc.sql
    assert rc.exclude_before == "2026-01-01"


def test_run_result_unenforced_fail_property():
    """RunResult.unenforced_fail counts only UNENFORCED_FAIL verdicts."""
    c = Check("t", "c", "type", "SELECT 1", "desc", "error", enforced=False)
    results = [
        CheckResult(c, "UNENFORCED_FAIL"),
        CheckResult(c, "UNENFORCED_FAIL"),
        CheckResult(c, "FAIL"),
        CheckResult(c, "PASS"),
    ]
    rr = RunResult(results=results, verdict="FAIL", duration_seconds=1.0)
    assert rr.unenforced_fail == 2
    assert rr.failed == 1
    assert rr.passed == 1


def test_graduation_guard_unenforced_fail_is_not_pass():
    """UNENFORCED_FAIL is not PASS -- graduation guard condition (verdict != 'PASS') is satisfied."""
    c = Check("ops_recommendations", "file", "not_null", "sql", "desc", "error", enforced=False)
    result = CheckResult(check=c, verdict="UNENFORCED_FAIL")
    assert result.verdict != "PASS"


def test_graduation_guard_unenforced_fail_not_in_passed_count():
    """UNENFORCED_FAIL checks are excluded from passed count -- graduation readiness requires PASS."""
    c = Check("ops_recommendations", "file", "not_null", "sql", "desc", "error", enforced=False)
    rr = RunResult(results=[CheckResult(c, "UNENFORCED_FAIL")], verdict="PASS")
    assert rr.passed == 0
    assert rr.unenforced_fail == 1


def test_graduation_guard_unenforced_fail_recorded_in_latest_json(tmp_path):
    """_save_latest_result records UNENFORCED_FAIL per-check -- graduation guard reads this to block flip."""
    with patch("scripts.data_quality_runner._ROOT", tmp_path):
        c = Check("ops_recommendations", "file", "not_null", "sql", "desc", "error", enforced=False)
        rr = RunResult(results=[CheckResult(c, "UNENFORCED_FAIL")], verdict="PASS")
        _save_latest_result(rr)

    data = json.loads((tmp_path / "logs" / "debug" / "dq-latest.json").read_text())
    file_check = next(ch for ch in data["checks"] if ch["column"] == "file")
    assert file_check["verdict"] == "UNENFORCED_FAIL"
    assert file_check["verdict"] != "PASS"


def test_save_latest_result_includes_unenforced_fail_count(tmp_path):
    """dq-latest.json aggregate includes unenforced_fail key; failed excludes unenforced."""
    with patch("scripts.data_quality_runner._ROOT", tmp_path):
        c_enforced = Check("t", "c1", "not_null", "sql", "desc", "error", enforced=True)
        c_unenforced = Check("t", "c2", "not_null", "sql", "desc", "error", enforced=False)
        results = [
            CheckResult(c_enforced, "FAIL"),
            CheckResult(c_unenforced, "UNENFORCED_FAIL"),
            CheckResult(c_enforced, "PASS"),
        ]
        rr = RunResult(results=results, verdict="FAIL", duration_seconds=1.0)
        _save_latest_result(rr)

    data = json.loads((tmp_path / "logs" / "debug" / "dq-latest.json").read_text())
    assert "unenforced_fail" in data
    assert data["unenforced_fail"] == 1
    assert data["failed"] == 1  # only enforced FAIL
    assert data["passed"] == 1


def test_print_results_json_includes_unenforced_fail(capsys):
    """JSON output from _print_results includes unenforced_fail field."""
    c = Check("t", "c", "not_null", "sql", "desc", "error", enforced=False)
    results = [CheckResult(c, "UNENFORCED_FAIL")]
    rr = RunResult(results=results, verdict="PASS", duration_seconds=1.0)
    _print_results(rr, as_json=True)
    data = json.loads(capsys.readouterr().out)
    assert "unenforced_fail" in data
    assert data["unenforced_fail"] == 1
    assert data["failed"] == 0
