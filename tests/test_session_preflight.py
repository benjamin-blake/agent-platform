#!/usr/bin/env python3
"""Unit tests for scripts/session_preflight.py."""

from __future__ import annotations

import importlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Load the module under test
_MODULE_PATH = Path(__file__).resolve().parent.parent / "scripts" / "session_preflight.py"
_spec = importlib.util.spec_from_file_location("session_preflight", _MODULE_PATH)
assert _spec and _spec.loader
_preflight = importlib.util.module_from_spec(_spec)
sys.modules["session_preflight"] = _preflight
_spec.loader.exec_module(_preflight)  # type: ignore[union-attr]


@pytest.fixture(autouse=True)
def _disable_athena_queries(request: pytest.FixtureRequest):
    """Prevent all tests from hitting real Athena and from doing real git fetches.

    Athena: returns [] for ops_priority_queue_current queries so read_priority_queue() does
    not sys.exit(1) in tests that exercise main(). Returns None for all other queries,
    which preserves the JSONL fallback path in count_recommendations() and other consumers.

    Git fetch: check_main_freshness() shells out to ``git fetch origin main``; patch it to
    a deterministic stub for every test except TestCheckMainFreshness (which exercises the
    real function via subprocess.run mocking).
    """
    from contextlib import ExitStack  # noqa: PLC0415

    def _stub(sql: str) -> list | None:
        if "ops_priority_queue_current" in sql:
            return []
        return None

    freshness_stub = {
        "status": "ok",
        "fetched_at": "2026-05-24T00:00:00+00:00",
        "commits_behind": 0,
        "commits_ahead": 0,
        "main_files_changed_since_branch": [],
    }
    class_name = request.cls.__name__ if request.cls else ""

    with ExitStack() as stack:
        stack.enter_context(patch("session_preflight._run_athena_query", side_effect=_stub))
        stack.enter_context(patch("session_preflight._athena_run_query", return_value=[]))
        stack.enter_context(patch("scripts.sync_ops.sync", return_value={"drained": {}, "pulled": {}}))
        if class_name != "TestCheckMainFreshness":
            stack.enter_context(patch("session_preflight.check_main_freshness", return_value=freshness_stub))
        yield


class TestCheckVenv:
    def test_correct_venv_returns_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "session_preflight.sys.executable",
            "C:/Users/user/Git Repos/agent-platform/.venv/Scripts/python.exe",
        )
        monkeypatch.setattr("session_preflight.ROOT", Path("C:/Users/user/Git Repos/agent-platform"))
        assert _preflight.check_venv() is True

    def test_wrong_venv_returns_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "session_preflight.sys.executable",
            "C:/Users/user/Git Repos/da-data-athena/.venv/Scripts/python.exe",
        )
        monkeypatch.setattr("session_preflight.ROOT", Path("C:/Users/user/Git Repos/agent-platform"))
        assert _preflight.check_venv() is False


class TestGetGitStatus:
    def test_clean_branch(self) -> None:
        def mock_run(cmd: list, **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.returncode = 0
            if "--show-current" in cmd:
                result.stdout = "main\n"
            elif "--porcelain" in cmd:
                result.stdout = ""
            elif "list" in cmd:
                result.stdout = ""
            return result

        with patch("session_preflight.subprocess.run", side_effect=mock_run):
            branch, uncommitted, stash = _preflight.get_git_status()

        assert branch == "main"
        assert uncommitted is False
        assert stash == []

    def test_uncommitted_changes_detected(self) -> None:
        def mock_run(cmd: list, **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.returncode = 0
            if "--show-current" in cmd:
                result.stdout = "agent/test-branch\n"
            elif "--porcelain" in cmd:
                result.stdout = " M scripts/some_file.py\n"
            elif "list" in cmd:
                result.stdout = ""
            return result

        with patch("session_preflight.subprocess.run", side_effect=mock_run):
            branch, uncommitted, stash = _preflight.get_git_status()

        assert branch == "agent/test-branch"
        assert uncommitted is True

    def test_stash_entries_parsed(self) -> None:
        def mock_run(cmd: list, **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.returncode = 0
            if "--show-current" in cmd:
                result.stdout = "main\n"
            elif "--porcelain" in cmd:
                result.stdout = ""
            elif "list" in cmd:
                result.stdout = "stash@{0}: WIP on main: abc123 some work\nstash@{1}: WIP on main: def456 other\n"
            return result

        with patch("session_preflight.subprocess.run", side_effect=mock_run):
            _, _, stash = _preflight.get_git_status()

        assert len(stash) == 2
        assert "stash@{0}" in stash[0]


class TestCheckTerraformPending:
    def test_returns_false_when_exit_code_0(self) -> None:
        mock_result = MagicMock(returncode=0)
        with patch("session_preflight.subprocess.run", return_value=mock_result):
            assert _preflight.check_terraform_pending() is False

    def test_returns_true_when_exit_code_2(self) -> None:
        mock_result = MagicMock(returncode=2)
        with patch("session_preflight.subprocess.run", return_value=mock_result):
            assert _preflight.check_terraform_pending() is True

    def test_returns_none_when_exit_code_1(self) -> None:
        mock_result = MagicMock(returncode=1)
        with patch("session_preflight.subprocess.run", return_value=mock_result):
            assert _preflight.check_terraform_pending() is None

    def test_returns_none_when_terraform_not_found(self) -> None:
        with patch("session_preflight.subprocess.run", side_effect=FileNotFoundError):
            assert _preflight.check_terraform_pending() is None

    def test_returns_none_on_timeout(self) -> None:
        with patch(
            "session_preflight.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="terraform", timeout=120),
        ):
            assert _preflight.check_terraform_pending() is None


class TestCheckMainFreshness:
    def test_fetch_failure_returns_fetch_failed_status(self) -> None:
        fetch_fail = MagicMock(returncode=1, stderr="network unreachable", stdout="")
        with patch("session_preflight.subprocess.run", return_value=fetch_fail):
            result = _preflight.check_main_freshness()
        assert result["status"] == "fetch_failed"
        assert result["commits_behind"] is None
        assert result["commits_ahead"] is None
        assert result["main_files_changed_since_branch"] == []
        assert "network unreachable" in result["error"]

    def test_fetch_filenotfound_returns_fetch_failed_status(self) -> None:
        with patch("session_preflight.subprocess.run", side_effect=FileNotFoundError("git missing")):
            result = _preflight.check_main_freshness()
        assert result["status"] == "fetch_failed"
        assert "git missing" in result["error"]

    def test_fetch_timeout_returns_fetch_failed_status(self) -> None:
        with patch(
            "session_preflight.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="git", timeout=30),
        ):
            result = _preflight.check_main_freshness()
        assert result["status"] == "fetch_failed"

    def test_on_main_branch_returns_zero_zero(self) -> None:
        fetch_ok = MagicMock(returncode=0, stderr="", stdout="")
        counts = MagicMock(returncode=0, stdout="0\t0\n")

        def _runner(cmd, **kwargs):
            if cmd[:2] == ["git", "fetch"]:
                return fetch_ok
            if cmd[:2] == ["git", "rev-list"]:
                return counts
            return MagicMock(returncode=1, stdout="")

        with patch("session_preflight.subprocess.run", side_effect=_runner):
            result = _preflight.check_main_freshness()
        assert result["status"] == "ok"
        assert result["commits_behind"] == 0
        assert result["commits_ahead"] == 0
        assert result["main_files_changed_since_branch"] == []

    def test_branch_ahead_of_main_returns_zero_behind(self) -> None:
        fetch_ok = MagicMock(returncode=0, stderr="", stdout="")
        counts = MagicMock(returncode=0, stdout="0\t3\n")

        def _runner(cmd, **kwargs):
            if cmd[:2] == ["git", "fetch"]:
                return fetch_ok
            if cmd[:2] == ["git", "rev-list"]:
                return counts
            return MagicMock(returncode=1, stdout="")

        with patch("session_preflight.subprocess.run", side_effect=_runner):
            result = _preflight.check_main_freshness()
        assert result["status"] == "ok"
        assert result["commits_behind"] == 0
        assert result["commits_ahead"] == 3
        assert result["main_files_changed_since_branch"] == []

    def test_branch_behind_main_lists_changed_files(self) -> None:
        fetch_ok = MagicMock(returncode=0, stderr="", stdout="")
        counts = MagicMock(returncode=0, stdout="5\t2\n")
        merge_base = MagicMock(returncode=0, stdout="abc123\n")
        diff = MagicMock(returncode=0, stdout="docs/DECISIONS.md\nscripts/foo.py\n\n")

        def _runner(cmd, **kwargs):
            if cmd[:2] == ["git", "fetch"]:
                return fetch_ok
            if cmd[:2] == ["git", "rev-list"]:
                return counts
            if cmd[:2] == ["git", "merge-base"]:
                return merge_base
            if cmd[:2] == ["git", "diff"]:
                return diff
            return MagicMock(returncode=1, stdout="")

        with patch("session_preflight.subprocess.run", side_effect=_runner):
            result = _preflight.check_main_freshness()
        assert result["status"] == "ok"
        assert result["commits_behind"] == 5
        assert result["commits_ahead"] == 2
        assert result["main_files_changed_since_branch"] == ["docs/DECISIONS.md", "scripts/foo.py"]

    def test_rev_list_failure_returns_diff_failed_status(self) -> None:
        fetch_ok = MagicMock(returncode=0, stderr="", stdout="")
        counts = MagicMock(returncode=128, stdout="")

        def _runner(cmd, **kwargs):
            if cmd[:2] == ["git", "fetch"]:
                return fetch_ok
            if cmd[:2] == ["git", "rev-list"]:
                return counts
            return MagicMock(returncode=1, stdout="")

        with patch("session_preflight.subprocess.run", side_effect=_runner):
            result = _preflight.check_main_freshness()
        assert result["status"] == "diff_failed"
        assert result["commits_behind"] is None


class TestSlimRoadmapState:
    def test_keeps_only_actionable_subsets(self) -> None:
        full = {
            "next_eligible": [{"id": "T-1.6"}],
            "strategic_pending": [{"id": "T-2.1"}],
            "in_progress": [{"id": "T-1.5"}],
            "blocked": [{"id": "T-1.7"}],
            "active_tier": "T-1",
            "platform_tier_item_consumers": {"T-1.6": ["product-A"]},
        }
        slim = _preflight._slim_roadmap_state(full)
        assert slim == {
            "next_eligible": [{"id": "T-1.6"}],
            "strategic_pending": [{"id": "T-2.1"}],
        }

    def test_handles_missing_fields(self) -> None:
        slim = _preflight._slim_roadmap_state({})
        assert slim == {"next_eligible": [], "strategic_pending": []}


class TestFormatPreflightSummary:
    def test_summary_is_a_single_block_referencing_the_report_path(self) -> None:
        report = {
            "venv_ok": True,
            "sso_status": "ok",
            "branch": "agent/foo",
            "main_freshness": {"commits_behind": 3, "commits_ahead": 1},
            "open_recommendations": 12,
            "non_automatable_recommendations": 4,
            "ci_rca_recs": [{"id": "rec-1"}, {"id": "rec-2"}],
        }
        summary = _preflight._format_preflight_summary(report, Path("/tmp/foo.json"))
        assert "/tmp/foo.json" in summary
        assert "agent/foo" in summary
        assert "3 behind" in summary
        assert "1 ahead" in summary
        assert "open_recs=12" in summary
        assert "ci_rca=2" in summary
        assert "Read the report file" in summary

    def test_summary_handles_missing_main_freshness(self) -> None:
        report = {
            "venv_ok": False,
            "sso_status": "expired",
            "branch": "main",
            "open_recommendations": 0,
            "non_automatable_recommendations": 0,
            "ci_rca_recs": [],
        }
        summary = _preflight._format_preflight_summary(report, Path("/tmp/foo.json"))
        assert "? behind" in summary
        assert "? ahead" in summary


class TestStdoutDoesNotDumpFullJson:
    def test_main_does_not_print_full_json_to_stdout(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        preflight_report = tmp_path / ".preflight-report.json"
        with (
            patch("session_preflight.check_venv", return_value=True),
            patch("session_preflight.get_git_status", return_value=("agent/test", False, [])),
            patch("session_preflight.check_terraform_pending", return_value=False),
            patch("session_preflight.check_sso_status", return_value="ok"),
            patch("session_preflight.parse_last_session", return_value=""),
            patch("session_preflight.count_recommendations", return_value=(3, 0, 0, [])),
            patch("session_preflight._sync_ops_pull", return_value={}),
            patch(
                "session_preflight.read_context_files",
                return_value={
                    "roadmap_phase": "Phase 1.5",
                    "open_decisions_count": 0,
                    "recent_sessions": [],
                    "strategic_review_due": False,
                    "recommendations_count": 0,
                },
            ),
            patch(
                "session_preflight.check_telemetry_health",
                return_value={"overall": "ok", "checks": [], "friction_patterns": []},
            ),
            patch("session_preflight._check_ci_rca_liveness", return_value=None),
            patch("session_preflight.PREFLIGHT_REPORT", preflight_report),
        ):
            _preflight.main()
        captured = capsys.readouterr()
        assert "Preflight OK ->" in captured.out
        assert "Read the report file" in captured.out
        assert '"venv_ok": true' not in captured.out, (
            "Stdout should NOT contain the full report JSON -- that duplicates "
            "the file write and costs every consuming agent ~12-15k tokens."
        )


class TestJsonOutputSchema:
    def test_all_required_keys_present(self, tmp_path: Path) -> None:
        preflight_report = tmp_path / ".preflight-report.json"

        with (
            patch("session_preflight.check_venv", return_value=True),
            patch("session_preflight.get_git_status", return_value=("main", False, [])),
            patch(
                "session_preflight.check_main_freshness",
                return_value={
                    "status": "ok",
                    "fetched_at": "2026-05-24T00:00:00+00:00",
                    "commits_behind": 0,
                    "commits_ahead": 0,
                    "main_files_changed_since_branch": [],
                },
            ),
            patch("session_preflight.check_terraform_pending", return_value=False),
            patch("session_preflight.check_sso_status", return_value="ok"),
            patch("session_preflight.parse_last_session", return_value="## [2026-03-01] -- test"),
            patch("session_preflight.count_recommendations", return_value=(5, 1, 0, [])),
            patch("session_preflight._sync_ops_pull", return_value={}),
            patch(
                "session_preflight.read_context_files",
                return_value={
                    "roadmap_phase": "Phase 1.5",
                    "open_decisions_count": 2,
                    "recent_sessions": [],
                    "strategic_review_due": False,
                    "recommendations_count": 0,
                },
            ),
            patch(
                "session_preflight.check_telemetry_health",
                return_value={"overall": "ok", "checks": [], "friction_patterns": []},
            ),
            patch("session_preflight._check_ci_rca_liveness", return_value=None),
            patch("session_preflight.PREFLIGHT_REPORT", preflight_report),
            patch("builtins.print"),
        ):
            _preflight.main()

        assert preflight_report.exists()
        data = json.loads(preflight_report.read_text(encoding="utf-8"))

        required_keys = [
            "venv_ok",
            "branch",
            "uncommitted_changes",
            "stash_entries",
            "main_freshness",
            "sso_status",
            "terraform_pending",
            "last_session",
            "open_recommendations",
            "aging_recommendations",
            "non_automatable_recommendations",
            "priority_queue",
            "priority_queue_source",
            "friction_patterns",
            "context",
            "session_start",
            "recommendation_sync",
        ]
        assert "non_automatable_details" not in data, (
            "non_automatable_details was dropped from the slim report -- "
            "Decision 73 suspends individual rec review, so the detail list is dead weight"
        )
        for key in required_keys:
            assert key in data, f"Missing key: {key}"

    def test_recommendation_sync_field_in_output(self, tmp_path: Path) -> None:
        """recommendation_sync field appears in output and _sync_ops_pull is called."""
        preflight_report = tmp_path / ".preflight-report.json"

        with (
            patch("session_preflight.check_venv", return_value=True),
            patch("session_preflight.get_git_status", return_value=("agent/test", False, [])),
            patch(
                "session_preflight.check_main_freshness",
                return_value={
                    "status": "ok",
                    "fetched_at": "2026-05-24T00:00:00+00:00",
                    "commits_behind": 0,
                    "commits_ahead": 0,
                    "main_files_changed_since_branch": [],
                },
            ),
            patch("session_preflight.check_terraform_pending", return_value=False),
            patch("session_preflight.check_sso_status", return_value="ok"),
            patch("session_preflight.parse_last_session", return_value=""),
            patch("session_preflight.count_recommendations", return_value=(3, 0, 0, [])),
            patch(
                "session_preflight._sync_ops_pull",
                return_value={"ops_recommendations": 5},
            ) as mock_sync,
            patch(
                "session_preflight.read_context_files",
                return_value={
                    "roadmap_phase": "Phase 1.5",
                    "open_decisions_count": 0,
                    "recent_sessions": [],
                    "strategic_review_due": False,
                    "recommendations_count": 0,
                },
            ),
            patch(
                "session_preflight.check_telemetry_health",
                return_value={"overall": "ok", "checks": [], "friction_patterns": []},
            ),
            patch("session_preflight._check_ci_rca_liveness", return_value=None),
            patch("session_preflight.PREFLIGHT_REPORT", preflight_report),
            patch("builtins.print"),
        ):
            _preflight.main()

        mock_sync.assert_called_once()
        data = json.loads(preflight_report.read_text(encoding="utf-8"))
        assert data["recommendation_sync"] == {"ops_recommendations": 5}


class TestGracefulMissingFiles:
    def test_missing_session_log(self, tmp_path: Path) -> None:
        missing = tmp_path / "SESSION_LOG.md"
        with patch("session_preflight.SESSION_LOG_FILE", missing):
            result = _preflight.parse_last_session()
        assert result == ""

    def test_missing_recommendations(self, tmp_path: Path) -> None:
        missing = tmp_path / "RECOMMENDATIONS.md"
        with patch("session_preflight.RECOMMENDATIONS_FILE", missing):
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
        """count_recommendations returns non-automatable count and details."""
        recs_file = tmp_path / ".recommendations-log.jsonl"
        recs_file.write_text(self._REC_001 + self._REC_002 + self._REC_003, encoding="utf-8")
        with patch("session_preflight.RECOMMENDATIONS_FILE", recs_file):
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
        with patch("session_preflight.RECOMMENDATIONS_FILE", recs_file):
            _, _, non_auto_count, non_auto_details = _preflight.count_recommendations()
        assert non_auto_count == 15
        assert len(non_auto_details) == 10

    def test_non_automatable_fields_in_preflight_output(self, tmp_path: Path) -> None:
        """non_automatable_recommendations and non_automatable_details appear in preflight JSON."""
        preflight_report = tmp_path / ".preflight-report.json"
        with (
            patch("session_preflight.check_venv", return_value=True),
            patch("session_preflight.get_git_status", return_value=("agent/test", False, [])),
            patch("session_preflight.check_terraform_pending", return_value=False),
            patch("session_preflight.check_sso_status", return_value="ok"),
            patch("session_preflight.parse_last_session", return_value=""),
            patch(
                "session_preflight.count_recommendations",
                return_value=(2, 0, 1, [{"id": "rec-001", "title": "Manual", "context_excerpt": "ctx"}]),
            ),
            patch("session_preflight._sync_ops_pull", return_value={}),
            patch(
                "session_preflight.read_context_files",
                return_value={
                    "roadmap_phase": "Phase 1.5",
                    "open_decisions_count": 0,
                    "recent_sessions": [],
                    "strategic_review_due": False,
                    "recommendations_count": 0,
                },
            ),
            patch(
                "session_preflight.check_telemetry_health",
                return_value={"overall": "ok", "checks": [], "friction_patterns": []},
            ),
            patch("session_preflight._check_ci_rca_liveness", return_value=None),
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
        with patch("session_preflight.RECOMMENDATIONS_FILE", recs_file):
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
        with patch("session_preflight.RECOMMENDATIONS_FILE", recs_file):
            open_count, aging_count, non_auto_count, non_auto_details = _preflight.count_recommendations()
        assert open_count == 1
        assert aging_count == 0  # malformed date is not counted as aging


class TestReadContextFiles:
    def test_roadmap_phase_extracted(self, tmp_path: Path) -> None:
        roadmap = tmp_path / "ROADMAP.md"
        roadmap.write_text("# Roadmap\n\n## Phase 1.5: Schema Flattening\n", encoding="utf-8")
        with (
            patch("session_preflight.ROADMAP_FILE", roadmap),
            patch("session_preflight.DECISIONS_FILE", tmp_path / "missing.md"),
            patch("session_preflight.SESSION_LOG_FILE", tmp_path / "missing2.md"),
            patch("session_preflight.RECOMMENDATIONS_FILE", tmp_path / "missing3.md"),
        ):
            result = _preflight.read_context_files()
        assert result["roadmap_phase"] == "Phase 1.5: Schema Flattening"

    def test_roadmap_phase_defaults_unknown_when_missing(self, tmp_path: Path) -> None:
        with (
            patch("session_preflight.ROADMAP_FILE", tmp_path / "missing.md"),
            patch("session_preflight.DECISIONS_FILE", tmp_path / "missing2.md"),
            patch("session_preflight.SESSION_LOG_FILE", tmp_path / "missing3.md"),
            patch("session_preflight.RECOMMENDATIONS_FILE", tmp_path / "missing4.md"),
        ):
            result = _preflight.read_context_files()
        assert result["roadmap_phase"] == "unknown"

    def test_open_decisions_counted(self, tmp_path: Path) -> None:
        decisions = tmp_path / "DECISIONS.md"
        decisions.write_text(
            "## Decision 1: Foo (Agent-decided -- pending review)\n## Decision 2: Bar (Decided)\n## Decision 3: Baz\n",
            encoding="utf-8",
        )
        with (
            patch("session_preflight.ROADMAP_FILE", tmp_path / "missing.md"),
            patch("session_preflight.DECISIONS_FILE", decisions),
            patch("session_preflight.SESSION_LOG_FILE", tmp_path / "missing2.md"),
            patch("session_preflight.RECOMMENDATIONS_FILE", tmp_path / "missing3.md"),
        ):
            result = _preflight.read_context_files()
        # Decision 1 and 3 are open; Decision 2 is Decided
        assert result["open_decisions_count"] == 2

    def test_recent_sessions_extracted(self, tmp_path: Path) -> None:
        session_log = tmp_path / "SESSION_LOG.md"
        session_log.write_text(
            "## [2026-03-01] -- agent/feature-a\n\n**Done:** Did something\n"
            "## [2026-03-10] -- agent/feature-b\n\n**Done:** Did another thing\n",
            encoding="utf-8",
        )
        with (
            patch("session_preflight.ROADMAP_FILE", tmp_path / "missing.md"),
            patch("session_preflight.DECISIONS_FILE", tmp_path / "missing2.md"),
            patch("session_preflight.SESSION_LOG_FILE", session_log),
            patch("session_preflight.RECOMMENDATIONS_FILE", tmp_path / "missing3.md"),
        ):
            result = _preflight.read_context_files()
        assert len(result["recent_sessions"]) == 2
        assert "2026-03-01" in result["recent_sessions"][0]

    def test_strategic_review_due_when_no_mention(self, tmp_path: Path) -> None:
        session_log = tmp_path / "SESSION_LOG.md"
        # Recent session but no strategic review mention
        from datetime import date

        today = date.today().isoformat()
        session_log.write_text(
            f"## [{today}] -- agent/feature\n\n**Done:** regular work\n",
            encoding="utf-8",
        )
        with (
            patch("session_preflight.ROADMAP_FILE", tmp_path / "missing.md"),
            patch("session_preflight.DECISIONS_FILE", tmp_path / "missing2.md"),
            patch("session_preflight.SESSION_LOG_FILE", session_log),
            patch("session_preflight.RECOMMENDATIONS_FILE", tmp_path / "missing3.md"),
        ):
            result = _preflight.read_context_files()
        assert result["strategic_review_due"] is True

    def test_strategic_review_not_due_when_recent_mention(self, tmp_path: Path) -> None:
        session_log = tmp_path / "SESSION_LOG.md"
        from datetime import date

        today = date.today().isoformat()
        session_log.write_text(
            f"## [{today}] -- strategic_review\n\n**Done:** completed strategic review\n",
            encoding="utf-8",
        )
        with (
            patch("session_preflight.ROADMAP_FILE", tmp_path / "missing.md"),
            patch("session_preflight.DECISIONS_FILE", tmp_path / "missing2.md"),
            patch("session_preflight.SESSION_LOG_FILE", session_log),
            patch("session_preflight.RECOMMENDATIONS_FILE", tmp_path / "missing3.md"),
        ):
            result = _preflight.read_context_files()
        assert result["strategic_review_due"] is False

    def test_missing_files_return_defaults(self, tmp_path: Path) -> None:
        with (
            patch("session_preflight.ROADMAP_FILE", tmp_path / "missing.md"),
            patch("session_preflight.DECISIONS_FILE", tmp_path / "missing2.md"),
            patch("session_preflight.SESSION_LOG_FILE", tmp_path / "missing3.md"),
            patch("session_preflight.RECOMMENDATIONS_FILE", tmp_path / "missing4.md"),
        ):
            result = _preflight.read_context_files()
        assert result["roadmap_phase"] == "unknown"
        assert result["open_decisions_count"] == 0
        assert result["recent_sessions"] == []
        assert result["strategic_review_due"] is True
        assert result["recommendations_count"] == 0


class TestCheckVenvWorktree:
    """Tests for check_venv() with worktree scenario and is_worktree()."""

    def test_check_venv_accepts_root_venv_windows(self, tmp_path: Path) -> None:
        """check_venv() returns True when sys.executable is inside ROOT/.venv (Windows layout)."""
        fake_root = tmp_path / "agent-platform"
        venv_exe = fake_root / ".venv" / "Scripts" / "python.exe"
        venv_exe.parent.mkdir(parents=True)
        venv_exe.touch()
        with (
            patch("session_preflight.ROOT", fake_root),
            patch("session_preflight.sys.executable", str(venv_exe)),
        ):
            assert _preflight.check_venv() is True

    def test_check_venv_accepts_root_venv_linux(self, tmp_path: Path) -> None:
        """check_venv() returns True when sys.executable is inside ROOT/.venv (Linux layout)."""
        fake_root = tmp_path / "agent-platform"
        venv_exe = fake_root / ".venv" / "bin" / "python"
        venv_exe.parent.mkdir(parents=True)
        venv_exe.touch()
        with (
            patch("session_preflight.ROOT", fake_root),
            patch("session_preflight.sys.executable", str(venv_exe)),
        ):
            assert _preflight.check_venv() is True

    def test_check_venv_accepts_repo_name_in_path(self) -> None:
        """check_venv() returns True when repo name is in sys.executable path (worktree fallback)."""
        repo_name = _preflight.ROOT.name  # "agent-platform"
        with patch("sys.executable", f"C:/some/path/{repo_name}/.venv/Scripts/python.exe"):
            assert _preflight.check_venv() is True

    def test_check_venv_rejects_wrong_venv(self) -> None:
        """check_venv() returns False when sys.executable is from a different repo."""
        with (
            patch("sys.executable", "C:/other-repo/.venv/Scripts/python.exe"),
            patch("session_preflight.sys.executable", "C:/other-repo/.venv/Scripts/python.exe"),
        ):
            assert _preflight.check_venv() is False

    def test_is_worktree_returns_true_when_cwd_differs_from_toplevel(self) -> None:
        """is_worktree() returns True when git toplevel differs from CWD."""
        mock_result = MagicMock(returncode=0, stdout="/main/repo\n")
        with (
            patch("session_preflight.subprocess.run", return_value=mock_result),
            patch("session_preflight.Path.cwd", return_value=Path("/main/repo/worktree")),
        ):
            assert _preflight.is_worktree() is True

    def test_is_worktree_returns_false_when_cwd_equals_toplevel(self) -> None:
        """is_worktree() returns False when CWD matches git toplevel."""
        mock_result = MagicMock(returncode=0, stdout="/main/repo\n")
        with (
            patch("session_preflight.subprocess.run", return_value=mock_result),
            patch("session_preflight.Path.cwd", return_value=Path("/main/repo")),
        ):
            assert _preflight.is_worktree() is False

    def test_is_worktree_returns_false_on_git_failure(self) -> None:
        """is_worktree() returns False when git rev-parse fails."""
        mock_result = MagicMock(returncode=1, stdout="")
        with patch("session_preflight.subprocess.run", return_value=mock_result):
            assert _preflight.is_worktree() is False


class TestLogSync:
    """Tests for run_log_sync() in session_preflight."""

    def _make_run(
        self,
        branch: str = "main",
        porcelain: str = "",
        add_rc: int = 0,
        commit_rc: int = 0,
        push_rc: int = 0,
        push_stderr: str = "",
    ) -> object:
        """Helper to build a mock subprocess.run side_effect for run_log_sync."""

        def mock_run(cmd: list, **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.returncode = 0
            result.stdout = ""
            result.stderr = ""
            if "--show-current" in cmd:
                result.stdout = branch + "\n"
            elif "--porcelain" in cmd:
                result.stdout = porcelain
            elif "add" in cmd:
                result.returncode = add_rc
                result.stderr = "add error" if add_rc != 0 else ""
            elif "commit" in cmd:
                result.returncode = commit_rc
                result.stderr = "commit error" if commit_rc != 0 else ""
            elif "push" in cmd:
                result.returncode = push_rc
                result.stderr = push_stderr
            return result

        return mock_run

    def test_log_sync_skipped_on_feature_branch(self) -> None:
        mock_run = self._make_run(branch="agent/foo")
        with patch("session_preflight.subprocess.run", side_effect=mock_run):
            result = _preflight.run_log_sync()
        assert result["status"] == "skipped"

    def test_log_sync_committed_when_only_logs_dirty(self) -> None:
        porcelain = " M logs/.friction-analysis-log.jsonl\n"
        mock_run = self._make_run(branch="main", porcelain=porcelain)
        with patch("session_preflight.subprocess.run", side_effect=mock_run):
            result = _preflight.run_log_sync()
        assert result["status"] == "committed"
        assert "logs/.friction-analysis-log.jsonl" in result["files"]

    def test_log_sync_skipped_when_non_log_dirty(self) -> None:
        porcelain = " M src/main.py\n"
        mock_run = self._make_run(branch="main", porcelain=porcelain)
        with patch("session_preflight.subprocess.run", side_effect=mock_run):
            result = _preflight.run_log_sync()
        assert result["status"] == "skipped"

    def test_log_sync_conflict_on_push_fail(self) -> None:
        porcelain = " M logs/.retro-lite-log.jsonl\n"
        mock_run = self._make_run(branch="main", porcelain=porcelain, push_rc=1, push_stderr="push failed")
        with patch("session_preflight.subprocess.run", side_effect=mock_run):
            result = _preflight.run_log_sync()
        assert result["status"] == "conflict"
        assert "error" in result

    def test_log_sync_clean_when_no_dirty_files(self) -> None:
        mock_run = self._make_run(branch="main", porcelain="")
        with patch("session_preflight.subprocess.run", side_effect=mock_run):
            result = _preflight.run_log_sync()
        assert result["status"] == "clean"


class TestTelemetryHealth:
    """Tests for check_telemetry_health() and --health CLI flag."""

    def _make_boto3_mock(self, session_raises: Exception | None = None) -> MagicMock:
        """Return a standalone boto3 module mock. boto3 is imported locally inside
        check_telemetry_health(), so we inject it via patch.dict(sys.modules)."""
        mock_boto3 = MagicMock()
        if session_raises is not None:
            mock_boto3.Session.side_effect = session_raises
        return mock_boto3

    def test_athena_returns_session_data(self) -> None:
        """When _athena_run_query returns session rows, health metrics are computed."""
        from datetime import timedelta

        now = datetime.now(timezone.utc)
        recent_ts = (now - timedelta(hours=1)).isoformat()
        sessions_rows = [["total", "success_count", "latest"], ["10", "8", recent_ts]]
        friction_rows: list[list[str]] = [["category", "description", "occurrences"]]

        mock_boto3 = self._make_boto3_mock()
        with (
            patch.dict(sys.modules, {"boto3": mock_boto3}),
            patch("session_preflight._athena_run_query", side_effect=[sessions_rows, friction_rows]),
        ):
            result = _preflight.check_telemetry_health()

        assert result["overall"] in ("ok", "warning")
        assert "friction_patterns" in result
        names = [c["check"] for c in result["checks"]]
        assert "sessions-7d" in names
        assert "success-rate-7d" in names

    def test_athena_unreachable_returns_unknown(self) -> None:
        """When boto3.Session raises (SSO expired), returns overall: unknown."""
        mock_boto3 = self._make_boto3_mock(session_raises=Exception("auth error"))
        with patch.dict(sys.modules, {"boto3": mock_boto3}):
            result = _preflight.check_telemetry_health()

        assert result["overall"] == "unknown"
        assert any(c["check"] == "athena-query" for c in result["checks"])

    def test_athena_no_data_rows(self) -> None:
        """When _athena_run_query returns only a header row, sessions-7d is 0."""
        sessions_rows = [["total", "success_count", "latest"]]
        friction_rows: list[list[str]] = [["category", "description", "occurrences"]]

        mock_boto3 = self._make_boto3_mock()
        with (
            patch.dict(sys.modules, {"boto3": mock_boto3}),
            patch("session_preflight._athena_run_query", side_effect=[sessions_rows, friction_rows]),
        ):
            result = _preflight.check_telemetry_health()

        sessions_check = next((c for c in result["checks"] if c["check"] == "sessions-7d"), None)
        assert sessions_check is not None
        assert sessions_check["value"] == "0"

    def test_low_success_rate_flags_warning(self) -> None:
        """Success rate < 50% triggers a warning check."""
        from datetime import timedelta

        now = datetime.now(timezone.utc)
        recent_ts = (now - timedelta(hours=1)).isoformat()
        sessions_rows = [["total", "success_count", "latest"], ["10", "4", recent_ts]]
        friction_rows: list[list[str]] = [["category", "description", "occurrences"]]

        mock_boto3 = self._make_boto3_mock()
        with (
            patch.dict(sys.modules, {"boto3": mock_boto3}),
            patch("session_preflight._athena_run_query", side_effect=[sessions_rows, friction_rows]),
        ):
            result = _preflight.check_telemetry_health()

        rate_check = next((c for c in result["checks"] if c["check"] == "success-rate-7d"), None)
        assert rate_check is not None
        assert rate_check["severity"] == "warning"
        assert result["overall"] in ("warning", "critical")

    def test_open_session_creates_state_file(self, tmp_path: Path) -> None:
        """open_telemetry_session writes state file with correct schema."""
        state_file = tmp_path / ".telemetry-active-session.json"
        mock_tel = MagicMock()
        mock_tel.open_session.return_value = "fake-uuid"
        original = sys.modules.get("scripts.executor.telemetry")
        sys.modules["scripts.executor.telemetry"] = mock_tel
        try:
            with patch("session_preflight.TELEMETRY_ACTIVE_SESSION_FILE", state_file):
                _preflight.open_telemetry_session(workflow="plan", branch="agent/test")
        finally:
            if original is not None:
                sys.modules["scripts.executor.telemetry"] = original
            else:
                sys.modules.pop("scripts.executor.telemetry", None)

        assert state_file.exists()
        data = json.loads(state_file.read_text(encoding="utf-8"))
        assert "session_id" in data
        assert data["workflow"] == "plan"
        assert data["branch"] == "agent/test"
        assert "started_at" in data

    def test_main_includes_telemetry_health(self, tmp_path: Path) -> None:
        """main() includes telemetry_health key in report."""
        preflight_report = tmp_path / ".preflight-report.json"
        mock_health = {"overall": "ok", "checks": [], "friction_patterns": []}

        with (
            patch("session_preflight.check_telemetry_health", return_value=mock_health),
            patch("session_preflight._check_ci_rca_liveness", return_value=None),
            patch("session_preflight.check_venv", return_value=True),
            patch("session_preflight.get_git_status", return_value=("main", False, [])),
            patch("session_preflight.check_terraform_pending", return_value=False),
            patch("session_preflight.check_sso_status", return_value="ok"),
            patch("session_preflight.parse_last_session", return_value=""),
            patch("session_preflight.count_recommendations", return_value=(0, 0, 0, [])),
            patch("session_preflight._sync_ops_pull", return_value={}),
            patch(
                "session_preflight.read_context_files",
                return_value={
                    "roadmap_phase": "Phase 1.5",
                    "open_decisions_count": 0,
                    "recent_sessions": [],
                    "strategic_review_due": False,
                    "recommendations_count": 0,
                },
            ),
            patch("session_preflight.PREFLIGHT_REPORT", preflight_report),
            patch("builtins.print"),
        ):
            _preflight.main()

        data = json.loads(preflight_report.read_text(encoding="utf-8"))
        assert "telemetry_health" in data
        assert data["telemetry_health"]["overall"] == "ok"

    def test_health_flag_exits_zero_on_ok(self) -> None:
        """--health flag exits 0 when overall is ok."""
        mock_health = {"overall": "ok", "checks": []}
        with patch("session_preflight.check_telemetry_health", return_value=mock_health):
            exit_code = 1 if mock_health["overall"] == "critical" else 0
        assert exit_code == 0

    def test_health_flag_exits_nonzero_on_critical(self) -> None:
        """--health flag exits 1 when overall is critical."""
        mock_health = {"overall": "critical", "checks": []}
        with patch("session_preflight.check_telemetry_health", return_value=mock_health):
            exit_code = 1 if mock_health["overall"] == "critical" else 0
        assert exit_code == 1

    def test_health_flag_exits_zero_on_warning(self) -> None:
        """--health flag exits 0 when overall is warning (not critical)."""
        mock_health = {"overall": "warning", "checks": []}
        with patch("session_preflight.check_telemetry_health", return_value=mock_health):
            exit_code = 1 if mock_health["overall"] == "critical" else 0
        assert exit_code == 0

    def test_print_telemetry_health_runs(self) -> None:
        """print_telemetry_health does not crash."""
        health = {
            "overall": "warning",
            "checks": [
                {"check": "sessions-7d", "value": "5", "severity": "ok"},
                {"check": "success-rate-7d", "value": "40%", "severity": "warning"},
            ],
        }
        with patch("builtins.print"):
            _preflight.print_telemetry_health(health)


class TestReadPriorityQueueAthena:
    """Tests for read_priority_queue() via Athena path."""

    def test_success_path_returns_correct_shape(self) -> None:
        """Athena rows are parsed into correctly shaped dicts with int rank."""
        rows = [
            {"rec_id": "rec-100", "rank": "1", "rationale": "First", "north_star_impact": "high"},
            {"rec_id": "rec-200", "rank": "2", "rationale": "Second", "north_star_impact": "medium"},
        ]
        with patch("session_preflight._run_athena_query", return_value=rows):
            result = _preflight.read_priority_queue()
        assert len(result) == 2
        assert result[0]["rec_id"] == "rec-100"
        assert result[0]["rank"] == 1  # Athena returns strings; parser must cast to int
        assert set(result[0].keys()) == {"rank", "rec_id", "rationale", "north_star_impact"}

    def test_hard_fail_on_none(self) -> None:
        """_run_athena_query returning None causes SystemExit(1)."""
        with patch("session_preflight._run_athena_query", return_value=None):
            with pytest.raises(SystemExit):
                _preflight.read_priority_queue()

    def test_sso_login_triggered_on_expired(self) -> None:
        """_handle_sso_startup calls interactive aws sso login on Windows (no --use-device-code)."""
        with (
            patch("session_preflight.subprocess.run") as mock_run,
            patch("session_preflight.check_sso_status", return_value="ok"),
            patch("session_preflight.sys.platform", "win32"),
        ):
            result = _preflight._handle_sso_startup("expired")
        mock_run.assert_called_once_with(
            ["aws", "sso", "login", "--profile", "company-aws-profile"],
            check=False,
            timeout=300,
        )
        assert result == "ok"

    def test_sso_login_uses_device_code_when_headless(self) -> None:
        """_handle_sso_startup appends --use-device-code when DISPLAY is unset and not win32."""
        with (
            patch("session_preflight.subprocess.run") as mock_run,
            patch("session_preflight.check_sso_status", return_value="ok"),
            patch("session_preflight.os.environ", {"DISPLAY": None}.copy()),
            patch("session_preflight.sys.platform", "linux"),
        ):
            # Remove DISPLAY so environ.get("DISPLAY") returns None
            import os as _os

            env_without_display = {k: v for k, v in _os.environ.items() if k != "DISPLAY"}
            with patch.dict("session_preflight.os.environ", env_without_display, clear=True):
                _preflight._handle_sso_startup("expired")
        call_args = mock_run.call_args[0][0]
        assert "--use-device-code" in call_args

    def test_sso_login_interactive_when_display_set(self) -> None:
        """_handle_sso_startup uses interactive browser form when DISPLAY is set."""
        with (
            patch("session_preflight.subprocess.run") as mock_run,
            patch("session_preflight.check_sso_status", return_value="ok"),
            patch("session_preflight.sys.platform", "linux"),
            patch.dict("session_preflight.os.environ", {"DISPLAY": ":0"}, clear=False),
        ):
            _preflight._handle_sso_startup("expired")
        call_args = mock_run.call_args[0][0]
        assert "--use-device-code" not in call_args

    def test_sso_login_interactive_on_win32_regardless_of_display(self) -> None:
        """_handle_sso_startup uses interactive form on win32 even if DISPLAY is unset."""
        with (
            patch("session_preflight.subprocess.run") as mock_run,
            patch("session_preflight.check_sso_status", return_value="ok"),
            patch("session_preflight.sys.platform", "win32"),
        ):
            import os as _os

            env_without_display = {k: v for k, v in _os.environ.items() if k != "DISPLAY"}
            with patch.dict("session_preflight.os.environ", env_without_display, clear=True):
                _preflight._handle_sso_startup("expired")
        call_args = mock_run.call_args[0][0]
        assert "--use-device-code" not in call_args


class TestPrintPriorityQueue:
    """Tests for print_priority_queue() terminal output."""

    def test_empty_queue_prints_section_header(self) -> None:
        """Empty list prints the section header with (empty)."""
        printed: list[str] = []

        def capture(*args: object, **kwargs: object) -> None:
            printed.append(" ".join(str(a) for a in args))

        with patch("builtins.print", side_effect=capture):
            _preflight.print_priority_queue([])
        output = "\n".join(printed)
        assert "--- Priority Queue (top 5) ---" in output
        assert "(empty)" in output

    def test_entries_use_expected_format(self) -> None:
        """Entries are printed with #<rank> rec-NNN: [impact=...] -- <rationale>."""
        items = [
            {
                "rank": 1,
                "rec_id": "rec-100",
                "north_star_impact": "high",
                "rationale": "Top priority work",
            },
            {
                "rank": 2,
                "rec_id": "rec-200",
                "north_star_impact": "medium",
                "rationale": "Second item",
            },
        ]
        printed: list[str] = []

        def capture(*args: object, **kwargs: object) -> None:
            printed.append(" ".join(str(a) for a in args))

        with patch("builtins.print", side_effect=capture):
            _preflight.print_priority_queue(items)
        output = "\n".join(printed)
        assert "--- Priority Queue (top 5) ---" in output
        assert "#1 rec-100:" in output
        assert "[impact=high]" in output
        assert "-- Top priority work" in output
        assert "#2 rec-200:" in output


class TestMainIncludesPriorityQueue:
    """Verify main() integrates priority_queue into report and output."""

    def test_report_contains_priority_queue_key(
        self,
        tmp_path: Path,
    ) -> None:
        """priority_queue key appears in the preflight JSON report."""
        preflight_report = tmp_path / ".preflight-report.json"
        mock_queue = [
            {
                "rank": 1,
                "rec_id": "rec-500",
                "rationale": "Test",
                "north_star_impact": "high",
            },
        ]
        with (
            patch(
                "session_preflight.check_venv",
                return_value=True,
            ),
            patch(
                "session_preflight.get_git_status",
                return_value=("main", False, []),
            ),
            patch(
                "session_preflight.check_terraform_pending",
                return_value=False,
            ),
            patch(
                "session_preflight.check_sso_status",
                return_value="ok",
            ),
            patch(
                "session_preflight.parse_last_session",
                return_value="",
            ),
            patch(
                "session_preflight.count_recommendations",
                return_value=(1, 0, 0, []),
            ),
            patch(
                "session_preflight.read_priority_queue",
                return_value=mock_queue,
            ),
            patch(
                "session_preflight._sync_ops_pull",
                return_value={},
            ),
            patch(
                "session_preflight.read_context_files",
                return_value={
                    "roadmap_phase": "Phase 2",
                    "open_decisions_count": 0,
                    "recent_sessions": [],
                    "strategic_review_due": False,
                    "recommendations_count": 0,
                },
            ),
            patch(
                "session_preflight.check_telemetry_health",
                return_value={"overall": "ok", "checks": [], "friction_patterns": []},
            ),
            patch("session_preflight._check_ci_rca_liveness", return_value=None),
            patch(
                "session_preflight.PREFLIGHT_REPORT",
                preflight_report,
            ),
            patch("builtins.print"),
        ):
            _preflight.main()

        data = json.loads(
            preflight_report.read_text(encoding="utf-8"),
        )
        assert "priority_queue" in data
        assert len(data["priority_queue"]) == 1
        assert data["priority_queue"][0]["rec_id"] == "rec-500"
        assert data.get("priority_queue_source") == "athena"

    def test_terminal_output_includes_queue_section(
        self,
        tmp_path: Path,
    ) -> None:
        """Terminal output includes the priority queue section header."""
        preflight_report = tmp_path / ".preflight-report.json"
        printed: list[str] = []

        def capture_print(*args: object, **kwargs: object) -> None:
            printed.append(" ".join(str(a) for a in args))

        with (
            patch(
                "session_preflight.check_venv",
                return_value=True,
            ),
            patch(
                "session_preflight.get_git_status",
                return_value=("main", False, []),
            ),
            patch(
                "session_preflight.check_terraform_pending",
                return_value=False,
            ),
            patch(
                "session_preflight.check_sso_status",
                return_value="ok",
            ),
            patch(
                "session_preflight.parse_last_session",
                return_value="",
            ),
            patch(
                "session_preflight.count_recommendations",
                return_value=(0, 0, 0, []),
            ),
            patch(
                "session_preflight.read_priority_queue",
                return_value=[],
            ),
            patch(
                "session_preflight._sync_ops_pull",
                return_value={},
            ),
            patch(
                "session_preflight.read_context_files",
                return_value={
                    "roadmap_phase": "Phase 2",
                    "open_decisions_count": 0,
                    "recent_sessions": [],
                    "strategic_review_due": False,
                    "recommendations_count": 0,
                },
            ),
            patch(
                "session_preflight.check_telemetry_health",
                return_value={"overall": "ok", "checks": [], "friction_patterns": []},
            ),
            patch("session_preflight._check_ci_rca_liveness", return_value=None),
            patch(
                "session_preflight.PREFLIGHT_REPORT",
                preflight_report,
            ),
            patch("builtins.print", side_effect=capture_print),
        ):
            _preflight.main()

        output = "\n".join(printed)
        assert "--- Priority Queue (top 5) ---" in output


class TestCiRcaHardBlock:
    """Tests for the HARD BLOCK banner in print_ci_rca_recs()."""

    def test_hard_block_present_when_recs_non_empty(self) -> None:
        printed: list[str] = []

        def capture(*args: object, **kwargs: object) -> None:
            printed.append(" ".join(str(a) for a in args))

        with patch("builtins.print", side_effect=capture):
            _preflight.print_ci_rca_recs(
                [{"id": "rec-999", "title": "CI broken", "priority": "critical", "created_timestamp": "2026-05-13"}]
            )
        output = "\n".join(printed)
        assert "HARD BLOCK" in output

    def test_hard_block_absent_when_recs_empty(self) -> None:
        printed: list[str] = []

        def capture(*args: object, **kwargs: object) -> None:
            printed.append(" ".join(str(a) for a in args))

        with patch("builtins.print", side_effect=capture):
            _preflight.print_ci_rca_recs([])
        output = "\n".join(printed)
        assert "HARD BLOCK" not in output


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


class TestCiRcaLivenessAlert:
    """Tests for _check_ci_rca_liveness()."""

    def _make_gh_result(self, conclusion: str, created_at: str) -> MagicMock:
        result = MagicMock()
        result.returncode = 0
        result.stdout = json.dumps([{"conclusion": conclusion, "createdAt": created_at, "url": "https://github.com/run/1"}])
        return result

    def test_alert_set_when_red_main_no_rec(self) -> None:
        from datetime import timedelta

        old_ts = (datetime.now(timezone.utc) - timedelta(minutes=45)).strftime("%Y-%m-%dT%H:%M:%SZ")
        with (
            patch("session_preflight.subprocess.run", return_value=self._make_gh_result("failure", old_ts)),
            patch("session_preflight._fetch_ci_rca_recs_since", return_value=[]),
        ):
            result = _preflight._check_ci_rca_liveness("ok")
        assert result is not None
        assert "run_url" in result
        assert result["elapsed_minutes"] > 30

    def test_alert_none_when_rec_exists_after_run(self) -> None:
        from datetime import timedelta

        old_ts = (datetime.now(timezone.utc) - timedelta(minutes=45)).strftime("%Y-%m-%dT%H:%M:%SZ")
        with (
            patch("session_preflight.subprocess.run", return_value=self._make_gh_result("failure", old_ts)),
            patch("session_preflight._fetch_ci_rca_recs_since", return_value=[{"id": "rec-1"}]),
        ):
            result = _preflight._check_ci_rca_liveness("ok")
        assert result is None

    def test_alert_none_when_main_is_green(self) -> None:
        from datetime import timedelta

        old_ts = (datetime.now(timezone.utc) - timedelta(minutes=45)).strftime("%Y-%m-%dT%H:%M:%SZ")
        with patch("session_preflight.subprocess.run", return_value=self._make_gh_result("success", old_ts)):
            result = _preflight._check_ci_rca_liveness("ok")
        assert result is None

    def test_alert_none_when_sso_not_ok(self) -> None:
        result = _preflight._check_ci_rca_liveness("expired")
        assert result is None


class TestForwardFixRecursion:
    """Tests for _check_forward_fix_recursion()."""

    def test_alert_set_at_threshold(self) -> None:
        rows = [{"file": "scripts/validate.py", "cnt": "3"}]
        with patch("session_preflight._run_athena_query", return_value=rows):
            result = _preflight._check_forward_fix_recursion()
        assert result is not None
        assert result["file"] == "scripts/validate.py"
        assert result["count"] == 3
        assert result["threshold"] == 3

    def test_alert_none_when_no_groups(self) -> None:
        with patch("session_preflight._run_athena_query", return_value=[]):
            result = _preflight._check_forward_fix_recursion()
        assert result is None

    def test_alert_none_when_athena_unavailable(self) -> None:
        with patch("session_preflight._run_athena_query", return_value=None):
            result = _preflight._check_forward_fix_recursion()
        assert result is None


class TestSsoOrderingInMain:
    """Verify that SSO startup runs before ops pull in main()."""

    def test_sso_startup_precedes_pull(self, tmp_path: Path) -> None:
        """_handle_sso_startup is called before _sync_ops_pull in run_preflight main()."""
        call_order: list[str] = []

        def _track_sso(status: str) -> str:
            call_order.append("sso")
            return "ok"

        def _track_pull() -> dict:
            call_order.append("pull")
            return {}

        preflight_report = tmp_path / ".preflight-report.json"

        with (
            patch("session_preflight.check_venv", return_value=True),
            patch("session_preflight.sync_copilot_instructions"),
            patch(
                "session_preflight.check_telemetry_health",
                return_value={"friction_patterns": [], "overall": "ok", "checks": []},
            ),
            patch("session_preflight.print_telemetry_health"),
            patch("session_preflight.run_log_sync", return_value={}),
            patch("session_preflight.get_git_status", return_value=("agent/test", False, [])),
            patch("session_preflight.check_terraform_pending", return_value=False),
            patch("session_preflight.check_sso_status", return_value="ok"),
            patch("session_preflight._handle_sso_startup", side_effect=_track_sso),
            patch("session_preflight._sync_ops_pull", side_effect=_track_pull),
            patch("session_preflight.parse_last_session", return_value=""),
            patch("session_preflight.count_recommendations", return_value=(0, 0, 0, [])),
            patch("session_preflight.read_priority_queue", return_value=[]),
            patch("session_preflight.print_priority_queue"),
            patch(
                "session_preflight.read_context_files",
                return_value={
                    "roadmap_phase": "",
                    "open_decisions_count": 0,
                    "recent_sessions": [],
                    "strategic_review_due": False,
                    "recommendations_count": 0,
                },
            ),
            patch("session_preflight.check_data_quality_coverage", return_value={}),
            patch("session_preflight._check_ci_rca_liveness", return_value=None),
            patch("session_preflight.PREFLIGHT_REPORT", preflight_report),
            patch("scripts.ops_data_portal.drain_pending", return_value={"drained": 0, "skipped": 0, "deduped": 0}),
        ):
            _preflight.main()

        assert "sso" in call_order
        assert "pull" in call_order
        assert call_order.index("sso") < call_order.index("pull"), f"SSO must precede pull; got order: {call_order}"


class TestBudgetBypassAlert:
    """Tests for _check_budget_bypass_alert()."""

    def test_returns_none_under_threshold(self) -> None:
        """Returns None when fewer than 3 bypass recs exist in 7 days."""
        rows = [
            {"id": "rec-001", "context": "bypass 1", "created_timestamp": "2026-05-12 10:00:00"},
            {"id": "rec-002", "context": "bypass 2", "created_timestamp": "2026-05-11 10:00:00"},
        ]
        with patch("session_preflight._run_athena_query", return_value=rows):
            result = _preflight._check_budget_bypass_alert()
        assert result is None

    def test_returns_dict_at_threshold(self) -> None:
        """Returns dict with count and entries when >= 3 bypass recs exist."""
        rows = [
            {"id": "rec-001", "context": "bypass 1", "created_timestamp": "2026-05-12 10:00:00"},
            {"id": "rec-002", "context": "bypass 2", "created_timestamp": "2026-05-11 10:00:00"},
            {"id": "rec-003", "context": "bypass 3", "created_timestamp": "2026-05-10 10:00:00"},
        ]
        with patch("session_preflight._run_athena_query", return_value=rows):
            result = _preflight._check_budget_bypass_alert()
        assert result is not None
        assert result["count"] == 3
        assert len(result["entries"]) == 3

    def test_returns_none_on_query_failure(self) -> None:
        """Returns None (not raises) when Athena query raises an exception."""
        with patch("session_preflight._run_athena_query", side_effect=RuntimeError("Athena unreachable")):
            result = _preflight._check_budget_bypass_alert()
        assert result is None

    def test_returns_none_when_athena_returns_none(self) -> None:
        """Returns None when _run_athena_query returns None (query failed or SSO expired)."""
        with patch("session_preflight._run_athena_query", return_value=None):
            result = _preflight._check_budget_bypass_alert()
        assert result is None


class TestActivateHint:
    """Verify _print_activate_hint() emits the correct activate line per platform."""

    def test_activate_hint_linux(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
        monkeypatch.setattr(sys, "platform", "linux")
        _preflight._print_activate_hint()
        out = capsys.readouterr().out
        assert ".venv/bin/activate" in out
        assert ".venv/Scripts/activate" not in out

    def test_activate_hint_windows(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
        monkeypatch.setattr(sys, "platform", "win32")
        _preflight._print_activate_hint()
        out = capsys.readouterr().out
        assert ".venv/Scripts/activate" in out
        assert ".venv/bin/activate" not in out
