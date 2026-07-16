"""recs_cache-surface tests: graceful-missing-files, non-automatable recommendation counting
and softcap, forward-fix recursion alert, budget-bypass alert, DuckLake-reader recommendation
counting, recs-read-status degradation, latest-decision-timestamp lookup (rec-2709 Wave 4).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

boto3 = pytest.importorskip("boto3")

from tests.fixtures.session_preflight_module import preflight as _preflight  # noqa: E402


class TestGracefulMissingFiles:
    def test_missing_session_log(self, tmp_path: Path) -> None:
        missing = tmp_path / "SESSION_LOG.md"
        with patch("scripts.preflight._common.SESSION_LOG_FILE", missing):
            result = _preflight.parse_last_session()
        assert result == ""

    def test_missing_recommendations(self, tmp_path: Path) -> None:
        missing = tmp_path / "RECOMMENDATIONS.md"
        with (
            patch("scripts.preflight.recs_cache._count_recommendations_reader", return_value="reader_unreachable"),
            patch("scripts.preflight._common.RECOMMENDATIONS_FILE", missing),
        ):
            open_count, aging_count, non_auto_count, non_auto_details = _preflight.count_recommendations()
        assert open_count == 0
        assert aging_count == 0
        assert non_auto_count == 0
        assert non_auto_details == []


class TestNonAutomatableRecommendations:
    _REC_001 = (
        '{"id": "rec-001", "status": "open", "automatable": false,'
        ' "title": "Manual task", "date": "2026-01-01", "context": "Needs human review"}\n'
    )
    _REC_002 = (
        '{"id": "rec-002", "status": "open", "automatable": true,'
        ' "title": "Auto task", "date": "2026-01-01", "context": "Can be automated"}\n'
    )
    _REC_003 = (
        '{"id": "rec-003", "status": "closed", "automatable": false,'
        ' "title": "Closed manual", "date": "2026-01-01", "context": "Already done"}\n'
    )

    def test_non_automatable_count_and_details(self, tmp_path: Path) -> None:
        """count_recommendations returns non-automatable count and details (cache fallback path)."""
        recs_file = tmp_path / ".recommendations-log.jsonl"
        recs_file.write_text(self._REC_001 + self._REC_002 + self._REC_003, encoding="utf-8")
        with (
            patch("scripts.preflight.recs_cache._count_recommendations_reader", return_value="reader_unreachable"),
            patch("scripts.preflight._common.RECOMMENDATIONS_FILE", recs_file),
        ):
            open_count, aging_count, non_auto_count, non_auto_details = _preflight.count_recommendations()
        assert open_count == 2
        assert non_auto_count == 1
        assert len(non_auto_details) == 1
        assert non_auto_details[0]["id"] == "rec-001"
        assert non_auto_details[0]["title"] == "Manual task"
        assert "Needs human review" in non_auto_details[0]["context_excerpt"]

    def test_non_automatable_details_capped_at_ten(self, tmp_path: Path) -> None:
        """non_automatable_details list is capped at 10 entries."""
        recs_file = tmp_path / ".recommendations-log.jsonl"
        _line = (
            '{{"id": "rec-{i:03d}", "status": "open", "automatable": false,'
            ' "title": "Task {i}", "date": "2026-01-01", "context": "ctx"}}\n'
        )
        lines = [_line.format(i=i) for i in range(1, 16)]
        recs_file.write_text("".join(lines), encoding="utf-8")
        with (
            patch("scripts.preflight.recs_cache._count_recommendations_reader", return_value="reader_unreachable"),
            patch("scripts.preflight._common.RECOMMENDATIONS_FILE", recs_file),
        ):
            _, _, non_auto_count, non_auto_details = _preflight.count_recommendations()
        assert non_auto_count == 15
        assert len(non_auto_details) == 10

    def test_non_automatable_fields_in_preflight_output(self, tmp_path: Path) -> None:
        """non_automatable_recommendations and non_automatable_details appear in preflight JSON."""
        preflight_report = tmp_path / ".preflight-report.json"
        with (
            patch("scripts.preflight.env_git.check_venv", return_value=True),
            patch("scripts.preflight.env_git.get_git_status", return_value=("agent/test", False, [])),
            patch("scripts.preflight.aws_infra.check_terraform_pending", return_value=False),
            patch("scripts.preflight.aws_infra.check_credentials", return_value="ok"),
            patch("scripts.preflight.context_docs.parse_last_session", return_value=""),
            patch(
                "scripts.preflight.recs_cache._count_recommendations_reader",
                return_value=(2, 0, 1, [{"id": "rec-001", "title": "Manual", "context_excerpt": "ctx"}]),
            ),
            patch("session_preflight._sync_ops_pull", return_value={}),
            patch(
                "scripts.preflight.context_docs.read_context_files",
                return_value={
                    "roadmap_phase": "Phase 1.5",
                    "open_decisions_count": 0,
                    "recent_sessions": [],
                    "strategic_review_due": False,
                    "recommendations_count": 0,
                },
            ),
            patch(
                "scripts.preflight.context_docs.check_telemetry_health",
                return_value={"overall": "ok", "checks": [], "friction_patterns": []},
            ),
            patch("scripts.preflight.ci_rca_signals._check_ci_rca_liveness", return_value=None),
            patch("session_preflight.PREFLIGHT_REPORT", preflight_report),
            patch("builtins.print"),
        ):
            _preflight.main()

        data = json.loads(preflight_report.read_text(encoding="utf-8"))
        assert data["non_automatable_recommendations"] == 1
        assert "non_automatable_details" not in data, (
            "non_automatable_details is intentionally dropped from the slim report "
            "(Decision 73: individual rec review suspended). count_recommendations() "
            "still returns the details for any non-report consumer."
        )

    def test_count_recommendations_treats_missing_automatable_as_true(self, tmp_path: Path) -> None:
        """Recs without automatable field default to automatable=True (not counted as non-auto)."""
        recs_file = tmp_path / ".recommendations-log.jsonl"
        recs_file.write_text(
            '{"id": "rec-001", "status": "open", "title": "No automatable field", "date": "2026-01-01", "context": "ctx"}\n',
            encoding="utf-8",
        )
        with (
            patch("scripts.preflight.recs_cache._count_recommendations_reader", return_value="reader_unreachable"),
            patch("scripts.preflight._common.RECOMMENDATIONS_FILE", recs_file),
        ):
            _, _, non_auto_count, non_auto_details = _preflight.count_recommendations()
        assert non_auto_count == 0
        assert non_auto_details == []

    def test_malformed_date_does_not_crash(self, tmp_path: Path) -> None:
        """Recs with invalid date format are counted open but not counted aging."""
        recs_file = tmp_path / ".recommendations-log.jsonl"
        recs_file.write_text(
            '{"id": "rec-001", "status": "open", "date": "not-a-date", "title": "Bad date", "context": "ctx"}\n',
            encoding="utf-8",
        )
        with (
            patch("scripts.preflight.recs_cache._count_recommendations_reader", return_value="reader_unreachable"),
            patch("scripts.preflight._common.RECOMMENDATIONS_FILE", recs_file),
        ):
            open_count, aging_count, non_auto_count, non_auto_details = _preflight.count_recommendations()
        assert open_count == 1
        assert aging_count == 0  # malformed date is not counted as aging


class TestNonAutomatableSoftcap:
    """Tests for _check_non_automatable_softcap() and _NON_AUTOMATABLE_SOFTCAP constant."""

    def test_below_cap_returns_false(self) -> None:
        assert _preflight._check_non_automatable_softcap(249) is False

    def test_above_cap_returns_true(self) -> None:
        assert _preflight._check_non_automatable_softcap(251) is True

    def test_at_cap_returns_false(self) -> None:
        assert _preflight._check_non_automatable_softcap(250) is False

    def test_constant_is_250(self) -> None:
        assert _preflight._NON_AUTOMATABLE_SOFTCAP == 250


class TestForwardFixRecursion:
    """Tests for _check_forward_fix_recursion() -- forward_fix_recursion named verb."""

    def test_alert_set_at_threshold(self) -> None:
        rows = [{"file": "scripts/validate.py", "cnt": "3"}]
        with patch("scripts.preflight._common._make_reader") as MockReader:
            MockReader.return_value.named.return_value = rows
            result = _preflight._check_forward_fix_recursion()
        assert result is not None
        assert result["file"] == "scripts/validate.py"
        assert result["count"] == 3
        assert result["threshold"] == 3
        verb, kwargs = MockReader.return_value.named.call_args[0][0], MockReader.return_value.named.call_args.kwargs
        assert verb == "forward_fix_recursion"
        assert "since_ts" in kwargs  # the 24h cutoff is bound as a verb param

    def test_alert_none_when_no_groups(self) -> None:
        with patch("scripts.preflight._common._make_reader") as MockReader:
            MockReader.return_value.named.return_value = []
            result = _preflight._check_forward_fix_recursion()
        assert result is None

    def test_alert_none_when_reader_unavailable(self) -> None:
        with patch("scripts.preflight._common._make_reader") as MockReader:
            MockReader.return_value.named.side_effect = RuntimeError("reader down")
            result = _preflight._check_forward_fix_recursion()
        assert result is None


class TestBudgetBypassAlert:
    """Tests for _check_budget_bypass_alert() -- budget_bypass_recent named verb."""

    def test_returns_none_under_threshold(self) -> None:
        """Returns None when fewer than 3 bypass recs exist in 7 days."""
        rows = [
            {"id": "rec-001", "context": "bypass 1", "created_timestamp": "2026-05-12 10:00:00"},
            {"id": "rec-002", "context": "bypass 2", "created_timestamp": "2026-05-11 10:00:00"},
        ]
        with patch("scripts.preflight._common._make_reader") as MockReader:
            MockReader.return_value.named.return_value = rows
            result = _preflight._check_budget_bypass_alert()
        assert result is None
        MockReader.return_value.named.assert_called_once_with("budget_bypass_recent")

    def test_returns_dict_at_threshold(self) -> None:
        """Returns dict with count and entries when >= 3 bypass recs exist."""
        rows = [
            {"id": "rec-001", "context": "bypass 1", "created_timestamp": "2026-05-12 10:00:00"},
            {"id": "rec-002", "context": "bypass 2", "created_timestamp": "2026-05-11 10:00:00"},
            {"id": "rec-003", "context": "bypass 3", "created_timestamp": "2026-05-10 10:00:00"},
        ]
        with patch("scripts.preflight._common._make_reader") as MockReader:
            MockReader.return_value.named.return_value = rows
            result = _preflight._check_budget_bypass_alert()
        assert result is not None
        assert result["count"] == 3
        assert len(result["entries"]) == 3

    def test_returns_none_on_reader_failure(self) -> None:
        """Returns None (not raises) when reader raises an exception (Decision 55)."""
        with patch("scripts.preflight._common._make_reader") as MockReader:
            MockReader.return_value.named.side_effect = RuntimeError("reader unreachable")
            result = _preflight._check_budget_bypass_alert()
        assert result is None

    def test_returns_none_when_verb_returns_empty(self) -> None:
        """Returns None when the verb returns an empty row list (count 0 < 3)."""
        with patch("scripts.preflight._common._make_reader") as MockReader:
            MockReader.return_value.named.return_value = []
            result = _preflight._check_budget_bypass_alert()
        assert result is None


class TestCountRecommendationsReader:
    """Tests for _count_recommendations_reader() -- DuckLake reader path (T2.19 cutover)."""

    _OPEN_ROWS = [
        {
            "id": "rec-001",
            "title": "Fix thing",
            "context": "ctx",
            "created_timestamp": "2026-05-01T00:00:00Z",
            "automatable": True,
        },
        {
            "id": "rec-002",
            "title": "Other thing",
            "context": "ctx2",
            "created_timestamp": "2026-05-01T00:00:00Z",
            "automatable": False,
        },
    ]

    def test_reader_path_returns_counts(self) -> None:
        """open_recs verb success -> counts returned as tuple."""
        with patch("scripts.preflight._common._make_reader") as MockReader:
            MockReader.return_value.named.return_value = list(self._OPEN_ROWS)

            result = _preflight._count_recommendations_reader()

        MockReader.return_value.named.assert_called_once_with("open_recs")
        assert isinstance(result, tuple)
        open_count, _aging, non_auto_count, _details = result
        assert open_count == 2
        assert non_auto_count == 1

    def test_reader_failure_returns_reader_unreachable_string(self) -> None:
        """Reader raises -> returns 'reader_unreachable' string (no Athena fallback, Decision 55)."""
        with patch("scripts.preflight._common._make_reader") as MockReader:
            MockReader.return_value.named.side_effect = RuntimeError("reader down")

            result = _preflight._count_recommendations_reader()

        assert result == "reader_unreachable"

    def test_reader_failure_only_returns_reader_unreachable(self) -> None:
        """Reader fails -> 'reader_unreachable' string, never None (T2.19: no Athena escape)."""
        with patch("scripts.preflight._common._make_reader") as MockReader:
            MockReader.return_value.named.side_effect = ConnectionError("timeout")

            result = _preflight._count_recommendations_reader()

        assert result == "reader_unreachable"
        assert result is not None


class TestRecsReadStatusDegradation:
    """Verify that reader outage produces a loud recs_read_status signal (Decision 55)."""

    def test_reader_unreachable_yields_loud_degraded_signal_not_false_zero(self, tmp_path: Path) -> None:
        """reader_unreachable -> report shows recs_read_status=reader_unreachable (Decision 55 / T2.19)."""
        preflight_report = tmp_path / ".preflight-report.json"

        with (
            patch("scripts.preflight.env_git.check_venv", return_value=True),
            patch("scripts.preflight.env_git.get_git_status", return_value=("claude/test", False, [])),
            patch(
                "scripts.preflight.env_git.check_main_freshness",
                return_value={
                    "status": "ok",
                    "fetched_at": "2026-06-09T00:00:00+00:00",
                    "commits_behind": 0,
                    "commits_ahead": 0,
                    "main_files_changed_since_branch": [],
                },
            ),
            patch("scripts.preflight.aws_infra.check_terraform_pending", return_value=False),
            patch("scripts.preflight.aws_infra.check_credentials", return_value="ok"),
            patch("scripts.preflight.context_docs.parse_last_session", return_value=""),
            patch("scripts.preflight.recs_cache._count_recommendations_reader", return_value="reader_unreachable"),
            patch("session_preflight._sync_ops_pull", return_value={}),
            patch("scripts.preflight.priority_queue.read_priority_queue", return_value=[]),
            patch("scripts.preflight.priority_queue.print_priority_queue"),
            patch(
                "scripts.preflight.context_docs.read_context_files",
                return_value={
                    "roadmap_phase": "Phase 2",
                    "open_decisions_count": 0,
                    "recent_sessions": [],
                    "strategic_review_due": False,
                    "recommendations_count": 0,
                },
            ),
            patch(
                "scripts.preflight.context_docs.check_telemetry_health",
                return_value={"overall": "ok", "checks": [], "friction_patterns": []},
            ),
            patch(
                "scripts.preflight.context_docs.check_data_quality_coverage",
                return_value={"tables_covered": 0, "checks_defined": 0, "last_run": None},
            ),
            patch("scripts.preflight.ci_rca_signals._check_ci_rca_liveness", return_value=None),
            patch("scripts.preflight.ci_rca_signals._fetch_ci_rca_recs", return_value=[]),
            patch("session_preflight.PREFLIGHT_REPORT", preflight_report),
            patch("builtins.print"),
        ):
            _preflight.main()

        data = json.loads(preflight_report.read_text(encoding="utf-8"))
        assert data.get("recs_read_status") == "reader_unreachable"
        # open_recommendations sentinel is 0 on degradation -- distinguish via recs_read_status
        assert data.get("open_recommendations") == 0


class TestGetLatestDecisionTs:
    """_get_latest_decision_ts() reads via the decisions_max_updated verb."""

    def test_returns_ts_from_first_row(self) -> None:
        with patch("scripts.preflight._common._make_reader") as MockReader:
            MockReader.return_value.named.return_value = [{"ts": "2026-06-10T12:00:00+00:00"}]
            result = _preflight._get_latest_decision_ts()
        assert result == "2026-06-10T12:00:00+00:00"
        MockReader.assert_called_once_with(table="ops_decisions")
        MockReader.return_value.named.assert_called_once_with("decisions_max_updated")

    def test_returns_none_on_empty_rows(self) -> None:
        with patch("scripts.preflight._common._make_reader") as MockReader:
            MockReader.return_value.named.return_value = []
            assert _preflight._get_latest_decision_ts() is None

    def test_returns_none_on_empty_ts_value(self) -> None:
        with patch("scripts.preflight._common._make_reader") as MockReader:
            MockReader.return_value.named.return_value = [{"ts": ""}]
            assert _preflight._get_latest_decision_ts() is None

    def test_returns_none_on_reader_failure(self) -> None:
        with patch("scripts.preflight._common._make_reader") as MockReader:
            MockReader.return_value.named.side_effect = RuntimeError("reader down")
            assert _preflight._get_latest_decision_ts() is None
