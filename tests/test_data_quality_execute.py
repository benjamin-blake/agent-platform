from unittest.mock import MagicMock, patch

from scripts.data_quality_execute import _execute_check, _execute_check_ducklake, _is_reader_unavailable, run_checks
from scripts.data_quality_models import Check, CheckResult, RunResult


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

    with patch("scripts.data_quality_execute._MAX_POLL", 0.1), patch("time.sleep"):
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


def test_run_checks_dry_run():
    checks = [Check("t", "c", "type", "sql", "desc")]
    res = run_checks(checks, "wg", "db", dry_run=True)
    assert res.verdict == "SKIP"


def test_run_checks_with_issues():
    with patch("boto3.Session") as mock_session:
        mock_athena = MagicMock()
        mock_session.return_value.client.return_value = mock_athena
        with patch("scripts.data_quality_execute._execute_check") as mock_exec:
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
        with patch("scripts.data_quality_execute._execute_check") as mock_exec:
            mock_exec.return_value = CheckResult(Check("t", "c", "type", "sql", "desc"), "PASS")
            run_checks([Check("t", "c", "type", "sql", "desc")], "wg", "db", profile_name="my-profile")
    mock_session.assert_called_once_with(profile_name="my-profile")


def test_run_checks_profile_aws_env(monkeypatch):
    """Falls back to AWS_PROFILE env when profile_name is None."""
    monkeypatch.setenv("AWS_PROFILE", "env-profile")
    monkeypatch.delenv("AWS_DEFAULT_PROFILE", raising=False)
    with patch("boto3.Session") as mock_session:
        mock_session.return_value.client.return_value = MagicMock()
        with patch("scripts.data_quality_execute._execute_check") as mock_exec:
            mock_exec.return_value = CheckResult(Check("t", "c", "type", "sql", "desc"), "PASS")
            run_checks([Check("t", "c", "type", "sql", "desc")], "wg", "db")
    mock_session.assert_called_once_with(profile_name="env-profile")


def test_run_checks_profile_default_env(monkeypatch):
    """Falls back to AWS_DEFAULT_PROFILE when AWS_PROFILE is unset."""
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    monkeypatch.setenv("AWS_DEFAULT_PROFILE", "default-profile")
    with patch("boto3.Session") as mock_session:
        mock_session.return_value.client.return_value = MagicMock()
        with patch("scripts.data_quality_execute._execute_check") as mock_exec:
            mock_exec.return_value = CheckResult(Check("t", "c", "type", "sql", "desc"), "PASS")
            run_checks([Check("t", "c", "type", "sql", "desc")], "wg", "db")
    mock_session.assert_called_once_with(profile_name="default-profile")


def test_run_checks_profile_hard_default(monkeypatch):
    """Defaults to agent_platform when no env vars or arg are set."""
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    monkeypatch.delenv("AWS_DEFAULT_PROFILE", raising=False)
    with patch("boto3.Session") as mock_session:
        mock_session.return_value.client.return_value = MagicMock()
        with patch("scripts.data_quality_execute._execute_check") as mock_exec:
            mock_exec.return_value = CheckResult(Check("t", "c", "type", "sql", "desc"), "PASS")
            run_checks([Check("t", "c", "type", "sql", "desc")], "wg", "db")
    mock_session.assert_called_once_with(profile_name="agent_platform")


def test_apply_backend_routing_rewrites_all_migrated_tables():
    """All _DUCKLAKE_OPS_TABLES checks route to the reader; non-migrated tables stay on Athena."""
    import scripts.data_quality_runner as dq

    recs = Check(
        "ops_recommendations",
        "file",
        "not_null",
        "SELECT COUNT(*) AS violation FROM agent_platform.ops_recommendations_current WHERE file IS NULL",
        "recs file not null",
        "error",
    )
    decisions = Check(
        "ops_decisions",
        "status",
        "not_null",
        "SELECT COUNT(*) AS violation FROM agent_platform.ops_decisions_current WHERE status IS NULL",
        "dec status",
        "error",
    )
    deferred = Check(
        "ops_session_log",
        "session_id",
        "not_null",
        "SELECT COUNT(*) AS violation FROM agent_platform.ops_session_log_current WHERE session_id IS NULL",
        "session log id",
        "error",
    )
    dq.apply_backend_routing([recs, decisions, deferred], "agent_platform")
    assert recs.backend == "ducklake"
    assert "{tbl}" in recs.sql
    assert "ops_recommendations_current" not in recs.sql
    # ops_decisions is migrated too (Decision 84 I-1) -- routed to the reader.
    assert decisions.backend == "ducklake"
    assert "{tbl}" in decisions.sql
    # ops_session_log stays on Athena until its T2.26 disposition.
    assert deferred.backend == "athena"
    assert "ops_session_log_current" in deferred.sql


def test_apply_backend_routing_ignores_env_flag(monkeypatch):
    """The OPS_STORAGE_BACKEND env flag is retired: routing applies regardless of its value."""
    import scripts.data_quality_runner as dq

    monkeypatch.setenv("OPS_STORAGE_BACKEND", "iceberg")
    recs = Check(
        "ops_recommendations",
        "file",
        "not_null",
        "SELECT COUNT(*) AS violation FROM agent_platform.ops_recommendations_current WHERE file IS NULL",
        "recs file not null",
        "error",
    )
    out = dq.apply_backend_routing([recs], "agent_platform")
    assert recs.backend == "ducklake"
    assert recs in out


def test_run_checks_no_boto3():
    with patch.dict("sys.modules", {"boto3": None}):
        checks = [Check("t", "c", "type", "sql", "desc")]
        res = run_checks(checks, "wg", "db")
        assert res.verdict == "SKIP"


def test_run_checks_empty_list_returns_error():
    """Gap 1: run_checks with an empty check list must return verdict=ERROR, not PASS."""
    with patch("boto3.Session") as mock_session:
        mock_session.return_value.client.return_value = MagicMock()
        res = run_checks([], "wg", "db")
    assert res.verdict == "ERROR"
    assert len(res.results) == 0


def test_run_checks_enforced_false_advisory():
    """enforced=False FAIL does not produce FAIL aggregate; enforced=True FAIL does."""
    enforced_check = Check("t", "c", "not_null", "sql", "desc", enforced=True)
    unenforced_check = Check("t", "c", "unique", "sql", "desc", enforced=False)

    with patch("boto3.Session") as mock_session:
        mock_session.return_value.client.return_value = MagicMock()
        with patch("scripts.data_quality_execute._execute_check") as mock_exec:
            mock_exec.side_effect = [
                CheckResult(unenforced_check, "FAIL"),
            ]
            res = run_checks([unenforced_check], "wg", "db")
    assert res.verdict == "PASS"

    with patch("boto3.Session") as mock_session:
        mock_session.return_value.client.return_value = MagicMock()
        with patch("scripts.data_quality_execute._execute_check") as mock_exec:
            mock_exec.side_effect = [
                CheckResult(enforced_check, "FAIL"),
            ]
            res = run_checks([enforced_check], "wg", "db")
    assert res.verdict == "FAIL"


def test_ops_backend_unconditionally_ducklake(monkeypatch):
    import scripts.data_quality_runner as dq

    # Decision 84 I-1: DuckLake is the sole ops backend; the env rollback flag is retired.
    monkeypatch.delenv("OPS_STORAGE_BACKEND", raising=False)
    assert dq._ops_backend() == "ducklake"
    monkeypatch.setenv("OPS_STORAGE_BACKEND", "iceberg")  # ignored: no env read remains
    assert dq._ops_backend() == "ducklake"


def test_ducklake_ops_tables_set():
    import scripts.data_quality_runner as dq

    assert dq._DUCKLAKE_OPS_TABLES == frozenset(
        {"ops_recommendations", "ops_decisions", "ops_priority_queue", "ops_execution_plans"}
    )


def test_verdict_for_pass_fail_unenforced_hardgate():
    import scripts.data_quality_runner as dq

    c_pass = dq.Check("t", "x", "not_null", "sql", "d")
    assert dq._verdict_for(c_pass, 0, 0.1).verdict == "PASS"
    assert dq._verdict_for(c_pass, 3, 0.1).verdict == "FAIL"
    c_unenf = dq.Check("t", "x", "not_null", "sql", "d", enforced=False)
    assert dq._verdict_for(c_unenf, 1, 0.1).verdict == "UNENFORCED_FAIL"
    c_tomb = dq.Check("t", "id", "tombstone_resurrection", "sql", "d")
    assert dq._verdict_for(c_tomb, 1, 0.1).verdict == "HARD_GATE"


def test_execute_check_ducklake_success():
    class _Reader:
        def _invoke(self, payload):
            return {"rows": [{"violation": 0}]}

    check = Check("ops_recommendations", "id", "not_null", "SELECT COUNT(*) v FROM {tbl}", "d", backend="ducklake")
    assert _execute_check_ducklake(check, _Reader()).verdict == "PASS"


def test_execute_check_ducklake_relationships_skipped():
    check = Check("ops_priority_queue", "rec_id", "relationships", "sql", "d", backend="ducklake")
    assert _execute_check_ducklake(check, object()).verdict == "SKIP"


def test_execute_check_ducklake_reader_none_is_error():
    class _Reader:
        def _invoke(self, payload):
            return None  # unexpected None from _invoke -- body.get() raises AttributeError -> ERROR

    check = Check("ops_recommendations", "id", "not_null", "SELECT 1 FROM {tbl}", "d", backend="ducklake")
    assert _execute_check_ducklake(check, _Reader()).verdict == "ERROR"


def test_execute_check_ducklake_hist_only_resolves_to_history_table():
    """A check whose SQL references ONLY {hist} (no {tbl}) is resolved to the physical history table
    client-side (rec-2756-adjacent: a genuine cross-table current-vs-history DQ check, T2.26 c9)."""
    captured = {}

    class _Reader:
        def _invoke(self, payload):
            captured["sql"] = payload["sql"]
            return {"rows": [{"violation": 0}]}

    check = Check(
        "ops_execution_plans",
        "rec_id",
        "expression",
        "SELECT COUNT(*) v FROM {hist} GROUP BY rec_id, revision HAVING COUNT(*) > 1",
        "d",
        backend="ducklake",
    )
    result = _execute_check_ducklake(check, _Reader())
    assert result.verdict == "PASS"
    assert "{hist}" not in captured["sql"]
    assert "ops_catalog.ops_execution_plans_history" in captured["sql"]


def test_execute_check_ducklake_hist_and_tbl_both_present():
    """A check referencing BOTH {tbl} and {hist} resolves {hist} client-side while leaving {tbl}
    for query_ops/query_current's own server-side current-table substitution."""
    captured = {}

    class _Reader:
        def _invoke(self, payload):
            captured["sql"] = payload["sql"]
            return {"rows": [{"violation": 0}]}

    check = Check(
        "ops_execution_plans",
        "revision",
        "expression",
        "SELECT COUNT(*) v FROM {tbl} cur JOIN {hist} h ON h.rec_id = cur.rec_id WHERE h.revision > cur.revision",
        "d",
        backend="ducklake",
    )
    result = _execute_check_ducklake(check, _Reader())
    assert result.verdict == "PASS"
    assert "{hist}" not in captured["sql"]
    assert "ops_catalog.ops_execution_plans_history" in captured["sql"]
    # {tbl} is left for query_ops's own server-side substitution -- still a literal placeholder here.
    assert "{tbl}" in captured["sql"]


def test_run_checks_routes_ducklake(monkeypatch):
    class _Reader:
        def _invoke(self, payload):
            return {"rows": [{"violation": 0}]}

    monkeypatch.setattr("src.common.iceberg_reader.DuckLakeReader", lambda profile=None: _Reader())
    check = Check("ops_recommendations", "id", "not_null", "SELECT 1 FROM {tbl}", "d", backend="ducklake")
    result = run_checks([check], "wg", "db", dry_run=False)
    assert result.verdict == "PASS"


# ---------------------------------------------------------------------------
# UNAVAILABLE/DEGRADED: _is_reader_unavailable classification
# ---------------------------------------------------------------------------


class TestIsReaderUnavailable:
    """_is_reader_unavailable must classify transient infra outages vs structured handler errors."""

    def test_requests_connection_error_is_unavailable(self):
        import requests

        assert _is_reader_unavailable(requests.ConnectionError("connection refused")) is True

    def test_requests_timeout_is_unavailable(self):
        import requests

        assert _is_reader_unavailable(requests.Timeout("timed out")) is True

    def test_runtime_error_502_no_error_type_is_unavailable(self):
        assert _is_reader_unavailable(RuntimeError("ducklake reader failed (HTTP 502)")) is True

    def test_runtime_error_503_is_unavailable(self):
        assert _is_reader_unavailable(RuntimeError("failed (HTTP 503)")) is True

    def test_runtime_error_504_is_unavailable(self):
        assert _is_reader_unavailable(RuntimeError("failed (HTTP 504)")) is True

    def test_runtime_error_502_with_error_type_is_not_unavailable(self):
        assert _is_reader_unavailable(RuntimeError("failed (HTTP 502) error_type=runtime")) is False

    def test_runtime_error_500_with_error_type_is_not_unavailable(self):
        assert _is_reader_unavailable(RuntimeError("failed (HTTP 500) error_type=version_mismatch")) is False

    def test_runtime_error_500_no_error_type_is_not_unavailable(self):
        """HTTP 500 is NOT in the transient set {502,503,504} -- must gate as ERROR."""
        assert _is_reader_unavailable(RuntimeError("failed (HTTP 500)")) is False

    def test_runtime_error_4xx_is_not_unavailable(self):
        assert _is_reader_unavailable(RuntimeError("failed (HTTP 403)")) is False

    def test_generic_exception_is_not_unavailable(self):
        assert _is_reader_unavailable(Exception("some error")) is False

    def test_value_error_is_not_unavailable(self):
        assert _is_reader_unavailable(ValueError("bad value")) is False


# ---------------------------------------------------------------------------
# UNAVAILABLE/DEGRADED: _execute_check_ducklake exception classification
# ---------------------------------------------------------------------------


class TestExecuteCheckDucklakeUnavailable:
    """_execute_check_ducklake must classify transient _invoke raises as UNAVAILABLE."""

    def test_connection_error_returns_unavailable(self):
        import requests

        class _Reader:
            def _invoke(self, payload):
                raise requests.ConnectionError("connection refused")

        check = Check("ops_recommendations", "id", "not_null", "SELECT 1 FROM {tbl}", "d", backend="ducklake")
        assert _execute_check_ducklake(check, _Reader()).verdict == "UNAVAILABLE"

    def test_runtime_error_502_returns_unavailable(self):
        class _Reader:
            def _invoke(self, payload):
                raise RuntimeError("ducklake reader failed (HTTP 502)")

        check = Check("ops_recommendations", "id", "not_null", "SELECT 1 FROM {tbl}", "d", backend="ducklake")
        assert _execute_check_ducklake(check, _Reader()).verdict == "UNAVAILABLE"

    def test_runtime_error_503_returns_unavailable(self):
        class _Reader:
            def _invoke(self, payload):
                raise RuntimeError("failed (HTTP 503)")

        check = Check("ops_recommendations", "id", "not_null", "SELECT 1 FROM {tbl}", "d", backend="ducklake")
        assert _execute_check_ducklake(check, _Reader()).verdict == "UNAVAILABLE"

    def test_structured_500_with_error_type_returns_error(self):
        class _Reader:
            def _invoke(self, payload):
                raise RuntimeError("ducklake reader failed (HTTP 500) error_type=runtime")

        check = Check("ops_recommendations", "id", "not_null", "SELECT 1 FROM {tbl}", "d", backend="ducklake")
        assert _execute_check_ducklake(check, _Reader()).verdict == "ERROR"

    def test_runtime_error_4xx_returns_error(self):
        class _Reader:
            def _invoke(self, payload):
                raise RuntimeError("ducklake reader failed (HTTP 403)")

        check = Check("ops_recommendations", "id", "not_null", "SELECT 1 FROM {tbl}", "d", backend="ducklake")
        assert _execute_check_ducklake(check, _Reader()).verdict == "ERROR"

    def test_semantic_error_returns_error(self):
        class _Reader:
            def _invoke(self, payload):
                raise ValueError("bad SQL syntax")

        check = Check("ops_recommendations", "id", "not_null", "SELECT 1 FROM {tbl}", "d", backend="ducklake")
        assert _execute_check_ducklake(check, _Reader()).verdict == "ERROR"


# ---------------------------------------------------------------------------
# UNAVAILABLE/DEGRADED: run_checks aggregate
# ---------------------------------------------------------------------------


class TestRunChecksDegradedAggregate:
    """run_checks must aggregate DEGRADED when the only non-PASS results are UNAVAILABLE."""

    def test_only_unavailable_aggregates_to_degraded(self, monkeypatch):
        class _Reader:
            def _invoke(self, payload):
                raise RuntimeError("failed (HTTP 503)")

        monkeypatch.setattr("src.common.iceberg_reader.DuckLakeReader", lambda profile=None: _Reader())
        check = Check("ops_recommendations", "id", "not_null", "SELECT 1 FROM {tbl}", "d", backend="ducklake")
        result = run_checks([check], "wg", "db", dry_run=False)
        assert result.verdict == "DEGRADED"
        assert result.unavailable == 1

    def test_mixed_unavailable_and_violation_aggregates_to_fail(self, monkeypatch):
        call_count = {"n": 0}

        class _Reader:
            def _invoke(self, payload):
                call_count["n"] += 1
                if call_count["n"] == 1:
                    raise RuntimeError("failed (HTTP 503)")
                return {"rows": [{"violation": 5}]}

        monkeypatch.setattr("src.common.iceberg_reader.DuckLakeReader", lambda profile=None: _Reader())
        checks = [
            Check("ops_recommendations", "id", "not_null", "SELECT 1 FROM {tbl}", "d", backend="ducklake"),
            Check("ops_recommendations", "file", "not_null", "SELECT 1 FROM {tbl}", "d", backend="ducklake"),
        ]
        result = run_checks(checks, "wg", "db", dry_run=False)
        assert result.verdict == "FAIL"

    def test_unavailable_property_counts_correctly(self):
        c = Check("t", "c", "type", "sql", "d")
        rr = RunResult(
            results=[
                CheckResult(c, "UNAVAILABLE"),
                CheckResult(c, "UNAVAILABLE"),
                CheckResult(c, "PASS"),
            ],
            verdict="DEGRADED",
        )
        assert rr.unavailable == 2
