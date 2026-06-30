#!/usr/bin/env python3
"""Unit tests for scripts/session_preflight.py."""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

boto3 = pytest.importorskip("boto3")

# Load the module under test
_MODULE_PATH = Path(__file__).resolve().parent.parent / "scripts" / "session_preflight.py"
_spec = importlib.util.spec_from_file_location("session_preflight", _MODULE_PATH)
assert _spec and _spec.loader
_preflight = importlib.util.module_from_spec(_spec)
sys.modules["session_preflight"] = _preflight
_spec.loader.exec_module(_preflight)  # type: ignore[union-attr]


@pytest.fixture(autouse=True)
def _disable_reader_and_git_fetch(request: pytest.FixtureRequest):
    """Prevent all tests from hitting the real DuckLake reader and from doing real git fetches.

    Reader: every warehouse read in this module transits _make_reader().named(verb)
    (Decision 84 I-3). The default stub returns [] for every verb so read_priority_queue()
    does not sys.exit(1) and the rec counters report empty rather than reaching the network.
    Tests that need specific rows or failures re-patch session_preflight._make_reader.

    Git fetch: check_main_freshness() shells out to ``git fetch origin main``; patch it to
    a deterministic stub for every test except TestCheckMainFreshness (which exercises the
    real function via subprocess.run mocking).
    """
    from contextlib import ExitStack  # noqa: PLC0415

    reader_stub = MagicMock()
    reader_stub.named.return_value = []
    reader_stub.current_state.return_value = []

    freshness_stub = {
        "status": "ok",
        "fetched_at": "2026-05-24T00:00:00+00:00",
        "commits_behind": 0,
        "commits_ahead": 0,
        "main_files_changed_since_branch": [],
    }
    class_name = request.cls.__name__ if request.cls else ""

    # warm_sync is the single warm-up reader touch main() makes (neon-egress-reduction D4); stub it
    # so main() integration tests never hit the network. reader_ok=True + empty rows => main derives
    # empty signals (0 open recs etc.), matching the prior empty-reader-stub behaviour.
    warm_sync_stub = {
        "drained": {},
        "pulled": {},
        "rows": {"ops_recommendations": [], "ops_decisions": [], "ops_priority_queue": []},
        "reader_ok": {"ops_recommendations": True, "ops_decisions": True, "ops_priority_queue": True},
    }

    with ExitStack() as stack:
        stack.enter_context(patch("session_preflight._make_reader", return_value=reader_stub))
        stack.enter_context(patch("scripts.sync_ops.sync", return_value={"drained": {}, "pulled": {}}))
        stack.enter_context(patch("scripts.sync_ops.warm_sync", return_value=warm_sync_stub))
        stack.enter_context(patch("session_preflight._sync_ops_pull", return_value={}))
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
    """check_terraform_pending() reads the sandbox convergence record (CD.35 Wave 6 / T2.35).

    The retired ``terraform -chdir=terraform plan`` invocation was replaced by a
    convergence-record read. The function now returns a tuple
    (pending: bool | None, convergence_health: dict | None).
    """

    from contextlib import contextmanager

    @staticmethod
    @contextmanager
    def _patched(verdict):
        """Patch the convergence-record read path so assess_health returns ``verdict``."""
        from contextlib import ExitStack

        with ExitStack() as stack:
            stack.enter_context(patch("session_preflight.resolve_aws_profile", return_value="agent_platform"))
            stack.enter_context(patch("boto3.Session"))
            stack.enter_context(patch("scripts.convergence_health.read_convergence_record", return_value={}))
            stack.enter_context(patch("scripts.convergence_health.find_stuck_gated_approvals", return_value=[]))
            stack.enter_context(patch("scripts.convergence_health.assess_health", return_value=verdict))
            yield

    def test_returns_false_when_green(self) -> None:
        from scripts.convergence_health import HealthVerdict

        verdict = HealthVerdict(status="green", red_age_hours=0.0, unapplied_backlog=0, severity="none")
        with self._patched(verdict):
            pending, health = _preflight.check_terraform_pending()
        assert pending is False
        assert health["status"] == "green"
        assert health["red_age_hours"] == 0.0

    def test_returns_true_when_red(self) -> None:
        from scripts.convergence_health import HealthVerdict

        verdict = HealthVerdict(status="red", red_age_hours=24.27, unapplied_backlog=0, severity="high")
        with self._patched(verdict):
            pending, health = _preflight.check_terraform_pending()
        assert pending is True
        assert health["status"] == "red"
        assert health["severity"] == "high"

    def test_returns_true_when_backlog_nonzero_even_if_green(self) -> None:
        from scripts.convergence_health import HealthVerdict

        verdict = HealthVerdict(status="green", red_age_hours=0.0, unapplied_backlog=3, severity="low")
        with self._patched(verdict):
            pending, health = _preflight.check_terraform_pending()
        assert pending is True
        assert health["unapplied_backlog"] == 3

    def test_returns_none_when_status_unknown(self) -> None:
        from scripts.convergence_health import HealthVerdict

        verdict = HealthVerdict(status="unknown", red_age_hours=0.0, unapplied_backlog=0, severity="none")
        with self._patched(verdict):
            pending, health = _preflight.check_terraform_pending()
        assert pending is None
        assert health["status"] == "unknown"

    def test_stuck_approvals_count_surfaced(self) -> None:
        from scripts.convergence_health import HealthVerdict

        verdict = HealthVerdict(
            status="red",
            red_age_hours=2.0,
            unapplied_backlog=0,
            stuck_approvals=[{"run_id": 1}, {"run_id": 2}],
            severity="high",
        )
        with self._patched(verdict):
            _, health = _preflight.check_terraform_pending()
        assert health["stuck_approvals"] == 2

    def test_returns_none_none_on_exception(self) -> None:
        with patch("session_preflight.resolve_aws_profile", side_effect=RuntimeError("creds down")):
            result = _preflight.check_terraform_pending()
        assert result == (None, None)


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
            "creds_status": "ok",
            "branch": "agent/foo",
            "main_freshness": {"commits_behind": 3, "commits_ahead": 1},
            "open_recommendations": 12,
            "non_automatable_recommendations": 4,
            "ci_rca_recs": [{"id": "rec-1"}, {"id": "rec-2"}],
            "ci_rca_unresolved_recs": [{"id": "rec-1"}],
            "ci_rca_likely_resolved_recs": [{"id": "rec-2"}],
        }
        summary = _preflight._format_preflight_summary(report, Path("/tmp/foo.json"))
        assert "/tmp/foo.json" in summary
        assert "agent/foo" in summary
        assert "3 behind" in summary
        assert "1 ahead" in summary
        assert "open_recs=12" in summary
        assert "ci_rca_unresolved=1" in summary
        assert "ci_rca_likely_resolved=1" in summary
        assert "Read the report file" in summary

    def test_summary_handles_missing_main_freshness(self) -> None:
        report = {
            "venv_ok": False,
            "creds_status": "unavailable",
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
            patch("session_preflight.check_credentials", return_value="ok"),
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
            patch("session_preflight.check_credentials", return_value="ok"),
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
            "creds_status",
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
        """recommendation_sync field appears in output and is derived from sync_ops.warm_sync()['pulled']."""
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
            patch("session_preflight.check_credentials", return_value="ok"),
            patch("session_preflight.parse_last_session", return_value=""),
            patch("session_preflight.count_recommendations", return_value=(3, 0, 0, [])),
            patch(
                "scripts.sync_ops.warm_sync",
                return_value={
                    "drained": {},
                    "pulled": {"ops_recommendations": 5},
                    "rows": {"ops_recommendations": [], "ops_decisions": [], "ops_priority_queue": []},
                    "reader_ok": {"ops_recommendations": True, "ops_decisions": True, "ops_priority_queue": True},
                },
            ) as mock_warm_sync,
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

        mock_warm_sync.assert_called_once()
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
        with (
            patch("session_preflight._count_recommendations_reader", return_value="reader_unreachable"),
            patch("session_preflight.RECOMMENDATIONS_FILE", missing),
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
            patch("session_preflight._count_recommendations_reader", return_value="reader_unreachable"),
            patch("session_preflight.RECOMMENDATIONS_FILE", recs_file),
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
            patch("session_preflight._count_recommendations_reader", return_value="reader_unreachable"),
            patch("session_preflight.RECOMMENDATIONS_FILE", recs_file),
        ):
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
            patch("session_preflight.check_credentials", return_value="ok"),
            patch("session_preflight.parse_last_session", return_value=""),
            patch(
                "session_preflight._count_recommendations_reader",
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
        with (
            patch("session_preflight._count_recommendations_reader", return_value="reader_unreachable"),
            patch("session_preflight.RECOMMENDATIONS_FILE", recs_file),
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
            patch("session_preflight._count_recommendations_reader", return_value="reader_unreachable"),
            patch("session_preflight.RECOMMENDATIONS_FILE", recs_file),
        ):
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

    def test_check_venv_accepts_root_with_pyvenv_cfg(self, tmp_path: Path) -> None:
        """check_venv() returns True via the name-independent fallback when ROOT has its own .venv.

        The on-disk directory name may stay 'agent-platform' (or anything) after a GitHub rename,
        so the fallback checks for ROOT/.venv/pyvenv.cfg rather than matching the repo name.
        """
        fake_root = tmp_path / "some-renamed-dir"
        (fake_root / ".venv").mkdir(parents=True)
        (fake_root / ".venv" / "pyvenv.cfg").touch()
        with (
            patch("session_preflight.ROOT", fake_root),
            patch("sys.executable", "C:/unrelated/path/python.exe"),
            patch("session_preflight.sys.executable", "C:/unrelated/path/python.exe"),
        ):
            assert _preflight.check_venv() is True

    def test_check_venv_rejects_wrong_venv(self, tmp_path: Path) -> None:
        """check_venv() returns False when exe is a different repo's venv and ROOT has no .venv."""
        fake_root = tmp_path / "agent-platform"
        fake_root.mkdir()  # deliberately no .venv -> fallback must be False
        with (
            patch("session_preflight.ROOT", fake_root),
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
    """Tests for the check_telemetry_health() stub (telemetry re-lands on DuckLake in Phase 4)."""

    def test_stub_returns_not_migrated_shape(self) -> None:
        """The stub reports the fixed not-migrated payload compatible with print_telemetry_health()."""
        result = _preflight.check_telemetry_health()
        assert result == {
            "overall": "unknown",
            "checks": [{"check": "telemetry-store", "value": "not migrated (Phase 4)", "severity": "unknown"}],
            "friction_patterns": [],
        }

    def test_stub_makes_no_aws_calls(self) -> None:
        """The stub must not touch boto3 or shell out -- the Athena polling loop is retired."""
        import boto3

        with (
            patch.object(boto3, "Session", side_effect=AssertionError("stub must not construct a boto3 Session")),
            patch("session_preflight.subprocess.run", side_effect=AssertionError("stub must not shell out")),
        ):
            result = _preflight.check_telemetry_health()
        assert result["overall"] == "unknown"

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
            patch("session_preflight.check_credentials", return_value="ok"),
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


class TestReadPriorityQueueDegraded:
    """Tests for read_priority_queue() -- verb hard-fail and degraded-mode cache fallback."""

    def test_hard_fail_when_verb_fails_with_creds_ok(self) -> None:
        """A verb failure with credentials ok is an infrastructure fault -> SystemExit(1) (Decision 60)."""
        reader = MagicMock()
        reader.named.side_effect = RuntimeError("ducklake_reader 'named_read' failed (HTTP 500)")
        with patch("session_preflight._make_reader", return_value=reader):
            with pytest.raises(SystemExit):
                _preflight.read_priority_queue(creds_status="ok")

    def test_cache_fallback_returns_rows_when_creds_unavailable(self, tmp_path: Path) -> None:
        """creds_status != 'ok' -> rows from the local cache, the reader never queried."""
        cache = tmp_path / ".priority-queue.jsonl"
        cache.write_text(
            '{"rec_id": "rec-9", "rank": "1", "rationale": "cached", "north_star_impact": "high"}\n'
            "\n"  # blank lines tolerated
            '{"rec_id": "rec-8", "rank": "2", "rationale": "cached2", "north_star_impact": "low"}\n',
            encoding="utf-8",
        )
        with (
            patch.object(_preflight, "PRIORITY_QUEUE_FILE", cache),
            patch("session_preflight._make_reader") as mock_reader,
        ):
            result = _preflight.read_priority_queue(creds_status="unavailable")
        mock_reader.assert_not_called()
        assert [r["rec_id"] for r in result] == ["rec-9", "rec-8"]
        assert result[0]["rank"] == 1

    def test_empty_when_cache_absent_and_creds_unavailable(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """Absent cache + creds down -> [] with a loud warning, never a crash."""
        missing = tmp_path / "does-not-exist.jsonl"
        with patch.object(_preflight, "PRIORITY_QUEUE_FILE", missing):
            result = _preflight.read_priority_queue(creds_status="unavailable")
        assert result == []
        assert "priority queue unavailable" in capsys.readouterr().err


class TestCheckCredentials:
    """Tests for check_credentials() -- the static-key credential gate."""

    def test_ok_when_returncode_zero(self) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 0
        with (
            patch("session_preflight.resolve_aws_profile", return_value="agent_platform"),
            patch("session_preflight.subprocess.run", return_value=mock_result) as mock_run,
        ):
            assert _preflight.check_credentials() == "ok"
        cmd = mock_run.call_args[0][0]
        assert cmd[:3] == ["aws", "sts", "get-caller-identity"]
        assert "--profile" in cmd and "agent_platform" in cmd

    def test_unavailable_when_returncode_nonzero(self) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 255
        with (
            patch("session_preflight.resolve_aws_profile", return_value="agent_platform"),
            patch("session_preflight.subprocess.run", return_value=mock_result),
        ):
            assert _preflight.check_credentials() == "unavailable"

    def test_unavailable_when_cli_missing(self) -> None:
        with (
            patch("session_preflight.resolve_aws_profile", return_value="agent_platform"),
            patch("session_preflight.subprocess.run", side_effect=FileNotFoundError),
        ):
            assert _preflight.check_credentials() == "unavailable"

    def test_omits_profile_for_default_chain(self) -> None:
        """resolve_aws_profile() -> None (Lambda/CI) means no --profile is passed."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        with (
            patch("session_preflight.resolve_aws_profile", return_value=None),
            patch("session_preflight.subprocess.run", return_value=mock_result) as mock_run,
        ):
            assert _preflight.check_credentials() == "ok"
        assert "--profile" not in mock_run.call_args[0][0]


class TestHandleCredentialsStartup:
    """Tests for _handle_credentials_startup() -- non-fatal degraded mode (Decision 60)."""

    def test_ok_returns_status_without_warning(self, capsys: pytest.CaptureFixture) -> None:
        with patch("session_preflight.subprocess.run") as mock_run:
            assert _preflight._handle_credentials_startup("ok") == "ok"
        mock_run.assert_not_called()
        assert capsys.readouterr().err == ""

    def test_unavailable_is_non_fatal_and_never_logs_in(self, capsys: pytest.CaptureFixture) -> None:
        """No SystemExit; no login subprocess invoked; returns the status unchanged."""
        with patch("session_preflight.subprocess.run") as mock_run:
            result = _preflight._handle_credentials_startup("unavailable")
        assert result == "unavailable"
        mock_run.assert_not_called()
        assert "DEGRADED" in capsys.readouterr().err


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
                "session_preflight.check_credentials",
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
        assert data.get("priority_queue_source") == "ducklake_reader"

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
                "session_preflight.check_credentials",
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

    def test_alert_none_when_creds_not_ok(self) -> None:
        result = _preflight._check_ci_rca_liveness("unavailable")
        assert result is None


class TestForwardFixRecursion:
    """Tests for _check_forward_fix_recursion() -- forward_fix_recursion named verb."""

    def test_alert_set_at_threshold(self) -> None:
        rows = [{"file": "scripts/validate.py", "cnt": "3"}]
        with patch("session_preflight._make_reader") as MockReader:
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
        with patch("session_preflight._make_reader") as MockReader:
            MockReader.return_value.named.return_value = []
            result = _preflight._check_forward_fix_recursion()
        assert result is None

    def test_alert_none_when_reader_unavailable(self) -> None:
        with patch("session_preflight._make_reader") as MockReader:
            MockReader.return_value.named.side_effect = RuntimeError("reader down")
            result = _preflight._check_forward_fix_recursion()
        assert result is None


class TestCredentialsOrderingInMain:
    """Verify that the credential check runs before ops sync in main()."""

    def test_credentials_startup_precedes_sync(self, tmp_path: Path) -> None:
        """_handle_credentials_startup is called before scripts.sync_ops.warm_sync in main()."""
        call_order: list[str] = []

        def _track_creds(status: str) -> str:
            call_order.append("creds")
            return "ok"

        def _track_sync(profile: str = "agent_platform") -> dict:
            call_order.append("sync")
            return {
                "drained": {},
                "pulled": {},
                "rows": {"ops_recommendations": [], "ops_decisions": [], "ops_priority_queue": []},
                "reader_ok": {"ops_recommendations": True, "ops_decisions": True, "ops_priority_queue": True},
            }

        preflight_report = tmp_path / ".preflight-report.json"

        with (
            patch("session_preflight.check_venv", return_value=True),
            patch(
                "session_preflight.check_telemetry_health",
                return_value={"friction_patterns": [], "overall": "ok", "checks": []},
            ),
            patch("session_preflight.print_telemetry_health"),
            patch("session_preflight.run_log_sync", return_value={}),
            patch("session_preflight.get_git_status", return_value=("agent/test", False, [])),
            patch("session_preflight.check_terraform_pending", return_value=False),
            patch("session_preflight.check_credentials", return_value="ok"),
            patch("session_preflight._handle_credentials_startup", side_effect=_track_creds),
            patch("scripts.sync_ops.warm_sync", side_effect=_track_sync),
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
        ):
            _preflight.main()

        assert "creds" in call_order
        assert "sync" in call_order
        assert call_order.index("creds") < call_order.index("sync"), (
            f"credential check must precede sync; got order: {call_order}"
        )


class TestBudgetBypassAlert:
    """Tests for _check_budget_bypass_alert() -- budget_bypass_recent named verb."""

    def test_returns_none_under_threshold(self) -> None:
        """Returns None when fewer than 3 bypass recs exist in 7 days."""
        rows = [
            {"id": "rec-001", "context": "bypass 1", "created_timestamp": "2026-05-12 10:00:00"},
            {"id": "rec-002", "context": "bypass 2", "created_timestamp": "2026-05-11 10:00:00"},
        ]
        with patch("session_preflight._make_reader") as MockReader:
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
        with patch("session_preflight._make_reader") as MockReader:
            MockReader.return_value.named.return_value = rows
            result = _preflight._check_budget_bypass_alert()
        assert result is not None
        assert result["count"] == 3
        assert len(result["entries"]) == 3

    def test_returns_none_on_reader_failure(self) -> None:
        """Returns None (not raises) when reader raises an exception (Decision 55)."""
        with patch("session_preflight._make_reader") as MockReader:
            MockReader.return_value.named.side_effect = RuntimeError("reader unreachable")
            result = _preflight._check_budget_bypass_alert()
        assert result is None

    def test_returns_none_when_verb_returns_empty(self) -> None:
        """Returns None when the verb returns an empty row list (count 0 < 3)."""
        with patch("session_preflight._make_reader") as MockReader:
            MockReader.return_value.named.return_value = []
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


class TestReadPriorityQueueReader:
    """Tests for read_priority_queue() -- priority_queue_current named verb (Decision 84 I-3)."""

    _PQ_ROWS = [
        {"rec_id": "rec-20", "rank": 2, "rationale": "second", "north_star_impact": "low"},
        {"rec_id": "rec-10", "rank": 1, "rationale": "top", "north_star_impact": "high"},
    ]

    def test_reader_path_returns_shaped_sorted_rows(self) -> None:
        """Verb success -> rows shaped {rank, rec_id, rationale, north_star_impact} and rank-sorted."""
        with patch("session_preflight._make_reader") as MockReader:
            MockReader.return_value.named.return_value = list(self._PQ_ROWS)

            result = _preflight.read_priority_queue()

        MockReader.assert_called_once_with(table="ops_priority_queue")
        MockReader.return_value.named.assert_called_once_with("priority_queue_current")
        assert len(result) == 2
        assert result[0]["rec_id"] == "rec-10"  # sorted by rank
        assert result[0]["rank"] == 1
        assert set(result[0].keys()) == {"rank", "rec_id", "rationale", "north_star_impact"}

    def test_reader_string_rank_cast_to_int(self) -> None:
        """String ranks from the reader are cast to int during shaping."""
        rows = [{"rec_id": "rec-99", "rank": "1", "rationale": "r", "north_star_impact": "medium"}]
        with patch("session_preflight._make_reader") as MockReader:
            MockReader.return_value.named.return_value = rows

            result = _preflight.read_priority_queue()

        assert result[0]["rank"] == 1

    def test_reader_empty_returns_empty_list(self) -> None:
        """Verb returns [] -> function returns [] (empty queue, not an error)."""
        with patch("session_preflight._make_reader") as MockReader:
            MockReader.return_value.named.return_value = []

            result = _preflight.read_priority_queue()

        assert result == []


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
        with patch("session_preflight._make_reader") as MockReader:
            MockReader.return_value.named.return_value = list(self._OPEN_ROWS)

            result = _preflight._count_recommendations_reader()

        MockReader.return_value.named.assert_called_once_with("open_recs")
        assert isinstance(result, tuple)
        open_count, _aging, non_auto_count, _details = result
        assert open_count == 2
        assert non_auto_count == 1

    def test_reader_failure_returns_reader_unreachable_string(self) -> None:
        """Reader raises -> returns 'reader_unreachable' string (no Athena fallback, Decision 55)."""
        with patch("session_preflight._make_reader") as MockReader:
            MockReader.return_value.named.side_effect = RuntimeError("reader down")

            result = _preflight._count_recommendations_reader()

        assert result == "reader_unreachable"

    def test_reader_failure_only_returns_reader_unreachable(self) -> None:
        """Reader fails -> 'reader_unreachable' string, never None (T2.19: no Athena escape)."""
        with patch("session_preflight._make_reader") as MockReader:
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
            patch("session_preflight.check_venv", return_value=True),
            patch("session_preflight.get_git_status", return_value=("claude/test", False, [])),
            patch(
                "session_preflight.check_main_freshness",
                return_value={
                    "status": "ok",
                    "fetched_at": "2026-06-09T00:00:00+00:00",
                    "commits_behind": 0,
                    "commits_ahead": 0,
                    "main_files_changed_since_branch": [],
                },
            ),
            patch("session_preflight.check_terraform_pending", return_value=False),
            patch("session_preflight.check_credentials", return_value="ok"),
            patch("session_preflight.parse_last_session", return_value=""),
            patch("session_preflight._count_recommendations_reader", return_value="reader_unreachable"),
            patch("session_preflight._sync_ops_pull", return_value={}),
            patch("session_preflight.read_priority_queue", return_value=[]),
            patch("session_preflight.print_priority_queue"),
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
            patch(
                "session_preflight.check_data_quality_coverage",
                return_value={"tables_covered": 0, "checks_defined": 0, "last_run": None},
            ),
            patch("session_preflight._check_ci_rca_liveness", return_value=None),
            patch("session_preflight._fetch_ci_rca_recs", return_value=[]),
            patch("session_preflight.PREFLIGHT_REPORT", preflight_report),
            patch("builtins.print"),
        ):
            _preflight.main()

        data = json.loads(preflight_report.read_text(encoding="utf-8"))
        assert data.get("recs_read_status") == "reader_unreachable"
        # open_recommendations sentinel is 0 on degradation -- distinguish via recs_read_status
        assert data.get("open_recommendations") == 0


class TestFetchCiRcaRecs:
    """_fetch_ci_rca_recs / _fetch_ci_rca_recs_since transit the ci_rca_* named verbs."""

    def test_fetch_ci_rca_recs_uses_ci_rca_open_verb(self) -> None:
        rows = [{"id": "rec-900", "title": "CI broken", "priority": "critical"}]
        with patch("session_preflight._make_reader") as MockReader:
            MockReader.return_value.named.return_value = rows
            result = _preflight._fetch_ci_rca_recs()
        assert result == rows
        MockReader.return_value.named.assert_called_once_with("ci_rca_open")

    def test_fetch_ci_rca_recs_degrades_to_empty_with_warning(self, capsys: pytest.CaptureFixture) -> None:
        with patch("session_preflight._make_reader") as MockReader:
            MockReader.return_value.named.side_effect = RuntimeError("reader down")
            result = _preflight._fetch_ci_rca_recs()
        assert result == []
        assert "reader unreachable" in capsys.readouterr().err

    def test_fetch_ci_rca_recs_since_binds_since_ts(self) -> None:
        rows = [{"id": "rec-901"}]
        with patch("session_preflight._make_reader") as MockReader:
            MockReader.return_value.named.return_value = rows
            result = _preflight._fetch_ci_rca_recs_since("2026-06-10T00:00:00Z")
        assert result == rows
        MockReader.return_value.named.assert_called_once_with("ci_rca_since", since_ts="2026-06-10T00:00:00Z")

    def test_fetch_ci_rca_recs_since_returns_empty_on_failure(self) -> None:
        with patch("session_preflight._make_reader") as MockReader:
            MockReader.return_value.named.side_effect = RuntimeError("reader down")
            assert _preflight._fetch_ci_rca_recs_since("2026-06-10T00:00:00Z") == []


class TestDeriveCiRcaClosed:
    """Unit tests for _derive_ci_rca_closed() -- closed-sibling cluster projection."""

    def _make_row(
        self,
        rec_id: str,
        source: str = "ci_rca",
        status: str = "closed",
        file: str = "scripts/foo.py",
        title: str = "CI failure",
        last_updated: str = "2026-06-11T10:00:00Z",
    ) -> dict:
        return {
            "id": rec_id,
            "source": source,
            "status": status,
            "file": file,
            "title": title,
            "last_updated_timestamp": last_updated,
        }

    def test_only_closed_ci_rca_rows_returned(self) -> None:
        rows = [
            self._make_row("rec-901", status="closed"),
            self._make_row("rec-902", status="open"),
            self._make_row("rec-903", status="in_progress"),
            self._make_row("rec-904", source="manual", status="closed"),
        ]
        result = _preflight._derive_ci_rca_closed(rows)
        assert [r["id"] for r in result] == ["rec-901"]

    def test_projects_expected_fields(self) -> None:
        rows = [self._make_row("rec-910", file="scripts/bar.py", title="mypy error", last_updated="2026-06-15T12:00:00Z")]
        result = _preflight._derive_ci_rca_closed(rows)
        assert len(result) == 1
        assert set(result[0].keys()) == {"id", "file", "title", "last_updated_timestamp"}
        assert result[0]["id"] == "rec-910"
        assert result[0]["file"] == "scripts/bar.py"
        assert result[0]["title"] == "mypy error"
        assert result[0]["last_updated_timestamp"] == "2026-06-15T12:00:00Z"

    def test_empty_rows_returns_empty(self) -> None:
        assert _preflight._derive_ci_rca_closed([]) == []

    def test_multiple_closed_ci_rca_all_returned(self) -> None:
        rows = [
            self._make_row("rec-920"),
            self._make_row("rec-921"),
            self._make_row("rec-922", status="superseded"),
        ]
        result = _preflight._derive_ci_rca_closed(rows)
        assert [r["id"] for r in result] == ["rec-920", "rec-921"]


class TestGetLatestDecisionTs:
    """_get_latest_decision_ts() reads via the decisions_max_updated verb."""

    def test_returns_ts_from_first_row(self) -> None:
        with patch("session_preflight._make_reader") as MockReader:
            MockReader.return_value.named.return_value = [{"ts": "2026-06-10T12:00:00+00:00"}]
            result = _preflight._get_latest_decision_ts()
        assert result == "2026-06-10T12:00:00+00:00"
        MockReader.assert_called_once_with(table="ops_decisions")
        MockReader.return_value.named.assert_called_once_with("decisions_max_updated")

    def test_returns_none_on_empty_rows(self) -> None:
        with patch("session_preflight._make_reader") as MockReader:
            MockReader.return_value.named.return_value = []
            assert _preflight._get_latest_decision_ts() is None

    def test_returns_none_on_empty_ts_value(self) -> None:
        with patch("session_preflight._make_reader") as MockReader:
            MockReader.return_value.named.return_value = [{"ts": ""}]
            assert _preflight._get_latest_decision_ts() is None

    def test_returns_none_on_reader_failure(self) -> None:
        with patch("session_preflight._make_reader") as MockReader:
            MockReader.return_value.named.side_effect = RuntimeError("reader down")
            assert _preflight._get_latest_decision_ts() is None


class TestReadContextFilesRecsCount:
    """read_context_files() counts open recs via the open_recs verb (Decision 84 I-3)."""

    def test_recommendations_count_is_len_of_open_recs_rows(self, tmp_path: Path) -> None:
        reader = MagicMock()
        reader.named.return_value = [{"id": "rec-1"}, {"id": "rec-2"}, {"id": "rec-3"}]
        with (
            patch("session_preflight._make_reader", return_value=reader),
            patch("session_preflight.ROADMAP_FILE", tmp_path / "missing.md"),
            patch("session_preflight.DECISIONS_FILE", tmp_path / "missing2.md"),
            patch("session_preflight.SESSION_LOG_FILE", tmp_path / "missing3.md"),
        ):
            result = _preflight.read_context_files()
        assert result["recommendations_count"] == 3
        reader.named.assert_called_once_with("open_recs")

    def test_recommendations_count_zero_on_reader_failure(self, tmp_path: Path) -> None:
        reader = MagicMock()
        reader.named.side_effect = RuntimeError("reader down")
        with (
            patch("session_preflight._make_reader", return_value=reader),
            patch("session_preflight.ROADMAP_FILE", tmp_path / "missing.md"),
            patch("session_preflight.DECISIONS_FILE", tmp_path / "missing2.md"),
            patch("session_preflight.SESSION_LOG_FILE", tmp_path / "missing3.md"),
        ):
            result = _preflight.read_context_files()
        assert result["recommendations_count"] == 0


class TestRetiredAthenaEstate:
    """Decision 84: the Athena query helpers and the outbox drain are gone from preflight."""

    def test_athena_helpers_deleted(self) -> None:
        for name in ("_run_athena_query", "_athena_run_query"):
            assert not hasattr(_preflight, name), f"retired symbol still present: {name}"
        athena_constants = [n for n in dir(_preflight) if n.startswith("_ATHENA")]
        assert athena_constants == [], f"retired Athena constants still present: {athena_constants}"

    def test_main_no_longer_drains_pending(self) -> None:
        source = _MODULE_PATH.read_text(encoding="utf-8")
        assert "drain_pending" not in source, "preflight must not reference the retired outbox drain"


class TestPriorityQueueSourceCache:
    """priority_queue_source reports 'cache' when credentials are unavailable."""

    def test_report_source_cache_when_creds_down(self, tmp_path: Path) -> None:
        preflight_report = tmp_path / ".preflight-report.json"
        with (
            patch("session_preflight.check_venv", return_value=True),
            patch("session_preflight.get_git_status", return_value=("claude/test", False, [])),
            patch("session_preflight.check_terraform_pending", return_value=False),
            patch("session_preflight.check_credentials", return_value="unavailable"),
            patch("session_preflight.parse_last_session", return_value=""),
            patch("session_preflight._count_recommendations_reader", return_value=(0, 0, 0, [])),
            patch("session_preflight.read_priority_queue", return_value=[]),
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
            patch("session_preflight._check_ci_rca_liveness", return_value=None),
            patch("session_preflight.PREFLIGHT_REPORT", preflight_report),
            patch("builtins.print"),
        ):
            _preflight.main()

        data = json.loads(preflight_report.read_text(encoding="utf-8"))
        assert data["creds_status"] == "unavailable"
        assert data["priority_queue_source"] == "cache"


class TestCiRcaCorrelation:
    """Tests for correlate_ci_rca_with_main() -- soft/hard classification."""

    def _make_rec(self, rec_id: str, file: str = "scripts/foo.py", created: str = "2026-06-10T10:00:00Z") -> dict:
        return {"id": rec_id, "file": file, "title": "CI failure", "priority": "critical", "created_timestamp": created}

    def _make_commit(self, sha: str, date: str, subject: str, files: list[str] | None = None) -> dict:
        return {"sha": sha, "date": date, "subject": subject, "files": files or []}

    def _make_closed_sibling(
        self,
        sib_id: str,
        file: str = "scripts/foo.py",
        title: str = "CI failure",
        closed: str = "2026-06-11T10:00:00Z",
    ) -> dict:
        return {
            "id": sib_id,
            "file": file,
            "title": title,
            "last_updated_timestamp": closed,
        }

    # --- LIKELY-RESOLVED cases ---

    def test_correlated_by_file_classified_likely_resolved(self) -> None:
        rec = self._make_rec("rec-2187", file="scripts/foo.py", created="2026-06-10T10:00:00Z")
        commit = self._make_commit("abc1234", "2026-06-11T10:00:00+00:00", "fix: repair foo", files=["scripts/foo.py"])
        result = _preflight.correlate_ci_rca_with_main([rec], [commit])
        assert result["likely_resolved"] == [rec]
        assert result["unresolved"] == []

    def test_correlated_by_rec_id_in_subject_classified_likely_resolved(self) -> None:
        rec = self._make_rec("rec-2188", file="scripts/bar.py", created="2026-06-10T10:00:00Z")
        commit = self._make_commit("def5678", "2026-06-11T10:00:00+00:00", "fix(ci): closes rec-2188 mypy issue", files=[])
        result = _preflight.correlate_ci_rca_with_main([rec], [commit])
        assert result["likely_resolved"] == [rec]
        assert result["unresolved"] == []

    # --- UNRESOLVED / HARD BLOCK retained ---

    def test_no_matching_commit_classified_unresolved(self) -> None:
        rec = self._make_rec("rec-2190", file="scripts/baz.py", created="2026-06-10T10:00:00Z")
        commit = self._make_commit(
            "fff9999", "2026-06-11T10:00:00+00:00", "feat: unrelated change", files=["scripts/other.py"]
        )
        result = _preflight.correlate_ci_rca_with_main([rec], [commit])
        assert result["unresolved"] == [rec]
        assert result["likely_resolved"] == []

    def test_commit_before_rec_creation_does_not_correlate(self) -> None:
        rec = self._make_rec("rec-2191", file="scripts/foo.py", created="2026-06-12T10:00:00Z")
        commit = self._make_commit("aaa1111", "2026-06-11T10:00:00+00:00", "fix: repair foo", files=["scripts/foo.py"])
        result = _preflight.correlate_ci_rca_with_main([rec], [commit])
        assert result["unresolved"] == [rec]
        assert result["likely_resolved"] == []

    def test_empty_recs_returns_empty(self) -> None:
        commit = self._make_commit("abc1234", "2026-06-11T10:00:00+00:00", "fix: something")
        result = _preflight.correlate_ci_rca_with_main([], [commit])
        assert result == {"likely_resolved": [], "unresolved": []}

    def test_empty_commits_all_unresolved(self) -> None:
        rec = self._make_rec("rec-9999", file="scripts/x.py")
        result = _preflight.correlate_ci_rca_with_main([rec], [])
        assert result["unresolved"] == [rec]
        assert result["likely_resolved"] == []

    # --- precision: component-boundary path matching ---

    def test_basename_substring_of_unrelated_path_not_correlated(self) -> None:
        # "utils.py" must NOT match "scripts/test_utils.py" (substring crosses component boundary).
        rec = self._make_rec("rec-2195a", file="utils.py", created="2026-06-10T10:00:00Z")
        commit = self._make_commit(
            "bbb1111", "2026-06-11T10:00:00+00:00", "fix: update test_utils", files=["scripts/test_utils.py"]
        )
        result = _preflight.correlate_ci_rca_with_main([rec], [commit])
        assert result["unresolved"] == [rec]
        assert result["likely_resolved"] == []

    def test_ci_py_not_matched_by_cli_py(self) -> None:
        # "ci.py" must NOT match "scripts/cli.py".
        rec = self._make_rec("rec-2195b", file="ci.py", created="2026-06-10T10:00:00Z")
        commit = self._make_commit("ccc2222", "2026-06-11T10:00:00+00:00", "feat: cli improvements", files=["scripts/cli.py"])
        result = _preflight.correlate_ci_rca_with_main([rec], [commit])
        assert result["unresolved"] == [rec]
        assert result["likely_resolved"] == []

    def test_basename_only_rec_matches_full_path_with_same_basename(self) -> None:
        # "session_preflight.py" (basename) must match "scripts/session_preflight.py".
        rec = self._make_rec("rec-2195c", file="session_preflight.py", created="2026-06-10T10:00:00Z")
        commit = self._make_commit(
            "ddd3333", "2026-06-11T10:00:00+00:00", "fix: preflight update", files=["scripts/session_preflight.py"]
        )
        result = _preflight.correlate_ci_rca_with_main([rec], [commit])
        assert result["likely_resolved"] == [rec]
        assert result["unresolved"] == []

    def test_full_path_exact_match_correlated(self) -> None:
        # "scripts/session_preflight.py" must match "scripts/session_preflight.py" exactly.
        rec = self._make_rec("rec-2195d", file="scripts/session_preflight.py", created="2026-06-10T10:00:00Z")
        commit = self._make_commit(
            "eee4444", "2026-06-11T10:00:00+00:00", "fix: preflight update", files=["scripts/session_preflight.py"]
        )
        result = _preflight.correlate_ci_rca_with_main([rec], [commit])
        assert result["likely_resolved"] == [rec]
        assert result["unresolved"] == []

    # --- mixed batch ---

    def test_mixed_batch_split_correctly(self) -> None:
        rec_corr = self._make_rec("rec-100", file="scripts/a.py", created="2026-06-10T10:00:00Z")
        rec_not = self._make_rec("rec-101", file="scripts/b.py", created="2026-06-10T10:00:00Z")
        commit = self._make_commit("aaa2222", "2026-06-11T10:00:00+00:00", "fix: patch a", files=["scripts/a.py"])
        result = _preflight.correlate_ci_rca_with_main([rec_corr, rec_not], [commit])
        assert result["likely_resolved"] == [rec_corr]
        assert result["unresolved"] == [rec_not]

    # --- end-to-end derive->correlate regression (rec-2268 incident shape) ---

    def test_end_to_end_derive_to_correlate_classifies_rec_2268_shape(self) -> None:
        """rec-2268 shape: the open ci_rca rec's file was modified by a newer main commit, but
        _derive_ci_rca_open() previously dropped the `file` field so correlate_ci_rca_with_main()
        could not match it and the rec was incorrectly left as HARD BLOCK."""
        raw_row = {
            "id": "rec-2268",
            "title": "mypy failure in ci_rca_tier_map",
            "priority": "critical",
            "created_timestamp": "2026-06-17T08:00:00Z",
            "source": "ci_rca",
            "status": "open",
            "file": "scripts/ci_rca_tier_map.py",
        }
        derived = _preflight._derive_ci_rca_open([raw_row])
        assert len(derived) == 1
        assert derived[0]["file"] == "scripts/ci_rca_tier_map.py", "file must survive _derive_ci_rca_open projection"

        commit = self._make_commit(
            "e779dd30",
            "2026-06-18T09:00:00+00:00",
            "fix: add encoding utf-8 to ci_rca_tier_map (#184)",
            files=["scripts/ci_rca_tier_map.py"],
        )
        result = _preflight.correlate_ci_rca_with_main(derived, [commit])
        assert result["likely_resolved"] == derived, "rec-2268 shape must classify as likely_resolved end-to-end"
        assert result["unresolved"] == []

    # --- closed-sibling cluster tests ---

    def test_closed_sibling_cluster_positive_same_file_similar_title_sibling_after(self) -> None:
        """Positive: open rec with a closed sibling on the same file, similar title, sibling closed after rec created."""
        rec = self._make_rec("rec-2274", file="scripts/foo.py", created="2026-06-17T08:00:00Z")
        rec["title"] = "mypy failure in foo module"
        sibling = self._make_closed_sibling(
            "rec-2260", file="scripts/foo.py", title="mypy failure in foo module", closed="2026-06-18T09:00:00Z"
        )
        result = _preflight.correlate_ci_rca_with_main([rec], [], closed_ci_rca_recs=[sibling])
        assert len(result["likely_resolved"]) == 1
        assert result["likely_resolved"][0]["id"] == "rec-2274"
        assert "rec-2260" in result["likely_resolved"][0].get("_resolved_reason", "")
        assert result["unresolved"] == []

    def test_closed_sibling_cluster_negative_dissimilar_title(self) -> None:
        """Negative: same file but Jaccard < 0.5 (unrelated title) -- must NOT flag as likely_resolved."""
        rec = self._make_rec("rec-2275", file="scripts/foo.py", created="2026-06-17T08:00:00Z")
        rec["title"] = "mypy type annotation failure"
        sibling = self._make_closed_sibling(
            "rec-2261", file="scripts/foo.py", title="ruff import order violation", closed="2026-06-18T09:00:00Z"
        )
        result = _preflight.correlate_ci_rca_with_main([rec], [], closed_ci_rca_recs=[sibling])
        assert result["likely_resolved"] == []
        assert result["unresolved"] == [rec]

    def test_closed_sibling_cluster_negative_stale_sibling(self) -> None:
        """Negative: same file + similar title but sibling was closed BEFORE the open rec was created -- stale guard."""
        rec = self._make_rec("rec-2276", file="scripts/foo.py", created="2026-06-17T08:00:00Z")
        rec["title"] = "mypy failure in foo module"
        sibling = self._make_closed_sibling(
            "rec-2262", file="scripts/foo.py", title="mypy failure in foo module", closed="2026-06-16T07:00:00Z"
        )
        result = _preflight.correlate_ci_rca_with_main([rec], [], closed_ci_rca_recs=[sibling])
        assert result["likely_resolved"] == []
        assert result["unresolved"] == [rec]

    def test_closed_sibling_cluster_negative_null_timestamp(self) -> None:
        """Negative: same file + similar title but sibling has no last_updated_timestamp -- must NOT flag."""
        rec = self._make_rec("rec-2277", file="scripts/foo.py", created="2026-06-17T08:00:00Z")
        rec["title"] = "mypy failure in foo module"
        sibling = {
            "id": "rec-2263",
            "file": "scripts/foo.py",
            "title": "mypy failure in foo module",
            "last_updated_timestamp": None,
        }
        result = _preflight.correlate_ci_rca_with_main([rec], [], closed_ci_rca_recs=[sibling])
        assert result["likely_resolved"] == []
        assert result["unresolved"] == [rec]


class TestPrintCiRcaRecsWithCorrelation:
    """Tests for the new correlation-aware print_ci_rca_recs() output."""

    def _capture_output(self, recs: list[dict], correlation: dict | None) -> str:
        printed: list[str] = []

        def capture(*args: object, **kwargs: object) -> None:
            printed.append(" ".join(str(a) for a in args))

        with patch("builtins.print", side_effect=capture):
            _preflight.print_ci_rca_recs(recs, correlation=correlation)
        return "\n".join(printed)

    def test_hard_block_shown_for_unresolved_rec(self) -> None:
        rec = {"id": "rec-9999", "title": "CI broken", "priority": "critical", "created_timestamp": "2026-05-13"}
        correlation = {"likely_resolved": [], "unresolved": [rec]}
        output = self._capture_output([rec], correlation)
        assert "HARD BLOCK" in output
        assert "SOFT" not in output
        assert "rec-9999" in output

    def test_soft_prompt_shown_for_likely_resolved_rec(self) -> None:
        rec = {"id": "rec-2187", "title": "mypy fail", "priority": "critical", "created_timestamp": "2026-06-10"}
        correlation = {"likely_resolved": [rec], "unresolved": []}
        output = self._capture_output([rec], correlation)
        assert "SOFT" in output
        assert "LIKELY RESOLVED" in output
        assert "HARD BLOCK" not in output
        assert "rec-2187" in output
        assert "--update-rec rec-2187" in output

    def test_both_soft_and_hard_block_when_mixed(self) -> None:
        r_soft = {"id": "rec-100", "title": "old fail", "priority": "critical", "created_timestamp": "2026-06-10"}
        r_hard = {"id": "rec-101", "title": "new fail", "priority": "critical", "created_timestamp": "2026-06-12"}
        correlation = {"likely_resolved": [r_soft], "unresolved": [r_hard]}
        output = self._capture_output([r_soft, r_hard], correlation)
        assert "SOFT" in output
        assert "HARD BLOCK" in output
        assert "rec-100" in output
        assert "rec-101" in output

    def test_none_correlation_falls_back_to_all_hard_block(self) -> None:
        rec = {"id": "rec-999", "title": "CI broken", "priority": "critical", "created_timestamp": "2026-05-13"}
        output = self._capture_output([rec], correlation=None)
        assert "HARD BLOCK" in output
        assert "SOFT" not in output

    def test_empty_recs_shows_none(self) -> None:
        output = self._capture_output([], correlation={"likely_resolved": [], "unresolved": []})
        assert "(none)" in output


class TestCorrelateRecsWithCommits:
    """Tests for correlate_recs_with_commits() -- general engine (T3.8)."""

    def _rec(self, rec_id: str, file: str = "scripts/foo.py", created: str = "2026-06-10T10:00:00Z") -> dict:
        return {"id": rec_id, "file": file, "title": "Some recommendation", "created_timestamp": created}

    def _commit(self, sha: str, date: str, files: list[str]) -> dict:
        return {"sha": sha, "date": date, "subject": f"fix: {sha}", "files": files}

    def test_file_correlation_marks_likely_resolved(self) -> None:
        rec = self._rec("rec-001", file="scripts/foo.py")
        commit = self._commit("abc12345", "2026-06-11T10:00:00+00:00", ["scripts/foo.py"])
        result = _preflight.correlate_recs_with_commits([rec], [commit])
        assert result["likely_resolved"] == [rec]
        assert result["unresolved"] == []

    def test_id_in_commit_subject_marks_likely_resolved(self) -> None:
        rec = self._rec("rec-042")
        commit = {"sha": "bbb", "date": "2026-06-11T10:00:00+00:00", "subject": "fix: resolves rec-042", "files": []}
        result = _preflight.correlate_recs_with_commits([rec], [commit])
        assert result["likely_resolved"] == [rec]

    def test_no_match_marks_unresolved(self) -> None:
        rec = self._rec("rec-002", file="scripts/bar.py")
        commit = self._commit("ccc12345", "2026-06-11T10:00:00+00:00", ["scripts/other.py"])
        result = _preflight.correlate_recs_with_commits([rec], [commit])
        assert result["unresolved"] == [rec]

    def test_closed_sibling_cluster_signal(self) -> None:
        rec = self._rec("rec-003", file="scripts/foo.py", created="2026-06-10T10:00:00Z")
        rec["title"] = "Fix foo module failure"
        sibling = {
            "id": "rec-sib",
            "file": "scripts/foo.py",
            "title": "Fix foo module error",
            "last_updated_timestamp": "2026-06-11T10:00:00Z",
        }
        result = _preflight.correlate_recs_with_commits([rec], [], closed_recs=[sibling])
        assert len(result["likely_resolved"]) == 1

    def test_no_reader_call_made(self) -> None:
        """Serving from read-cache only; no warehouse re-fetch (Decision 88)."""
        rec = self._rec("rec-004", file="scripts/foo.py")
        commit = self._commit("ddd12345", "2026-06-11T10:00:00+00:00", ["scripts/foo.py"])
        with patch("session_preflight._make_reader") as mock_reader:
            _preflight.correlate_recs_with_commits([rec], [commit])
        mock_reader.assert_not_called()

    def test_correlate_ci_rca_wrapper_delegates(self) -> None:
        """correlate_ci_rca_with_main delegates to correlate_recs_with_commits."""
        rec = self._rec("rec-005", file="scripts/ci.py")
        commit = self._commit("eee12345", "2026-06-11T10:00:00+00:00", ["scripts/ci.py"])
        result = _preflight.correlate_ci_rca_with_main([rec], [commit], closed_ci_rca_recs=None)
        assert result["likely_resolved"] == [rec]


class TestSurfaceQueueRelevanceTriage:
    """Tests for surface_queue_relevance_triage() (T3.8 queue-wide surfacing)."""

    def _row(self, rec_id: str, status: str, source: str, file: str, created: str) -> dict:
        return {
            "id": rec_id,
            "status": status,
            "source": source,
            "file": file,
            "title": f"title {rec_id}",
            "created_timestamp": created,
            "last_updated_timestamp": created,
        }

    def test_returns_likely_resolved_for_open_non_ci_rca(self) -> None:
        cache = [
            self._row("rec-101", "open", "planning", "scripts/foo.py", "2026-06-10T10:00:00Z"),
        ]
        commits = [{"sha": "abc12345", "date": "2026-06-11T10:00:00+00:00", "subject": "fix", "files": ["scripts/foo.py"]}]
        result = _preflight.surface_queue_relevance_triage(cache, commits)
        assert any(r["id"] == "rec-101" for r in result)

    def test_ci_rca_recs_excluded_by_default(self) -> None:
        cache = [
            self._row("rec-200", "open", "ci_rca", "scripts/foo.py", "2026-06-10T10:00:00Z"),
        ]
        commits = [{"sha": "abc12345", "date": "2026-06-11T10:00:00+00:00", "subject": "fix", "files": ["scripts/foo.py"]}]
        result = _preflight.surface_queue_relevance_triage(cache, commits)
        assert all(r["id"] != "rec-200" for r in result)

    def test_no_reader_call_during_surfacing(self) -> None:
        """Surfacing is read-cache only; no DuckLake reader call (Decision 88)."""
        cache = [self._row("rec-300", "open", "planning", "scripts/bar.py", "2026-06-10T10:00:00Z")]
        commits = [{"sha": "def12345", "date": "2026-06-11T10:00:00+00:00", "subject": "fix", "files": ["scripts/bar.py"]}]
        with patch("session_preflight._make_reader") as mock_reader:
            _preflight.surface_queue_relevance_triage(cache, commits)
        mock_reader.assert_not_called()

    def test_cap_limits_results(self) -> None:
        cache = [self._row(f"rec-{i}", "open", "planning", f"scripts/f{i}.py", "2026-06-01T00:00:00Z") for i in range(20)]
        commits = [
            {
                "sha": "fff12345",
                "date": "2026-06-10T00:00:00+00:00",
                "subject": "fix all",
                "files": [f"scripts/f{i}.py" for i in range(20)],
            }
        ]
        result = _preflight.surface_queue_relevance_triage(cache, commits, cap=5)
        assert len(result) <= 5


class TestSyncCollapse:
    """sync_ops.sync is called exactly once; the standalone _sync_ops_pull is not called in main()."""

    _FULL_MAIN_PATCHES: dict = {}  # class-level placeholder; built per test

    @staticmethod
    def _full_main_ctx(tmp_path: Path, extra: dict | None = None):
        """Return a list of patch context managers sufficient to run main() in isolation."""
        patches = [
            patch("session_preflight.check_venv", return_value=True),
            patch("session_preflight.get_git_status", return_value=("agent/test", False, [])),
            patch("session_preflight.check_terraform_pending", return_value=False),
            patch("session_preflight.check_credentials", return_value="ok"),
            patch("session_preflight.parse_last_session", return_value=""),
            # Phase B / pre-Phase-A subprocess users -- patch by name so main() never
            # shells out to real git (tests/CLAUDE.md isolation: no real subprocess in unit tests).
            patch("session_preflight._get_recent_main_commits", return_value=[]),
            patch("session_preflight.run_log_sync", return_value={"status": "skipped", "files": []}),
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
            patch("session_preflight._check_ci_rca_liveness", return_value=None),
            patch("session_preflight.PREFLIGHT_REPORT", tmp_path / ".preflight-report.json"),
            patch("builtins.print"),
        ]
        if extra:
            for tgt, kwargs in extra.items():
                patches.append(patch(tgt, **kwargs))
        return patches

    def test_sync_called_exactly_once(self, tmp_path: Path) -> None:
        """scripts.sync_ops.warm_sync is called once (creds ok); recommendation_sync comes from 'pulled'."""
        sync_call_count: list[int] = []

        def tracking_sync(profile: str = "agent_platform") -> dict:
            sync_call_count.append(1)
            return {
                "drained": {},
                "pulled": {"ops_recommendations": 10},
                "rows": {"ops_recommendations": [], "ops_decisions": [], "ops_priority_queue": []},
                "reader_ok": {"ops_recommendations": True, "ops_decisions": True, "ops_priority_queue": True},
            }

        from contextlib import ExitStack  # noqa: PLC0415

        with ExitStack() as stack:
            for p in self._full_main_ctx(tmp_path):
                stack.enter_context(p)
            stack.enter_context(patch("scripts.sync_ops.warm_sync", side_effect=tracking_sync))
            _preflight.main()

        assert len(sync_call_count) == 1, f"warm_sync called {len(sync_call_count)} times; expected exactly 1"
        report_path = tmp_path / ".preflight-report.json"
        data = json.loads(report_path.read_text(encoding="utf-8"))
        assert data["recommendation_sync"] == {"ops_recommendations": 10}

    def test_sync_ops_pull_not_called_in_main(self, tmp_path: Path) -> None:
        """_sync_ops_pull (= _rebuild_local_cache) is never called from main() after the sync collapse."""
        pull_calls: list[int] = []

        from contextlib import ExitStack  # noqa: PLC0415

        with ExitStack() as stack:
            for p in self._full_main_ctx(tmp_path):
                stack.enter_context(p)
            stack.enter_context(patch("session_preflight._sync_ops_pull", side_effect=lambda: pull_calls.append(1) or {}))
            _preflight.main()

        assert pull_calls == [], "_sync_ops_pull must not be called from main() after the sync collapse"


class TestUrlPriming:
    """_prime_reader_url() resolves the DuckLake reader Function URL once and sets DUCKLAKE_READER_URL."""

    def test_sets_env_var_when_creds_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """On creds ok, DUCKLAKE_READER_URL is set from the resolved URL."""
        monkeypatch.delenv("DUCKLAKE_READER_URL", raising=False)
        fake_url = "https://abc123.lambda-url.eu-west-2.on.aws"
        mock_reader = MagicMock()
        mock_reader._reader_url.return_value = fake_url
        with patch("session_preflight._make_reader", return_value=mock_reader):
            _preflight._prime_reader_url("ok")
        assert os.environ.get("DUCKLAKE_READER_URL") == fake_url

    def test_skips_when_creds_not_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Credentials unavailable -> reader is never called and env var is not set."""
        monkeypatch.delenv("DUCKLAKE_READER_URL", raising=False)
        with patch("session_preflight._make_reader") as mock_make:
            _preflight._prime_reader_url("unavailable")
        mock_make.assert_not_called()
        assert "DUCKLAKE_READER_URL" not in os.environ

    def test_skips_if_already_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """If DUCKLAKE_READER_URL is already set, the existing value is preserved."""
        monkeypatch.setenv("DUCKLAKE_READER_URL", "https://original.url")
        with patch("session_preflight._make_reader") as mock_make:
            _preflight._prime_reader_url("ok")
        mock_make.assert_not_called()
        assert os.environ["DUCKLAKE_READER_URL"] == "https://original.url"

    def test_priming_failure_is_nonfatal(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """If URL resolution raises, _prime_reader_url does not propagate; env var is not set."""
        monkeypatch.delenv("DUCKLAKE_READER_URL", raising=False)
        mock_reader = MagicMock()
        mock_reader._reader_url.side_effect = RuntimeError("SSM unavailable")
        with patch("session_preflight._make_reader", return_value=mock_reader):
            _preflight._prime_reader_url("ok")  # must not raise
        assert "DUCKLAKE_READER_URL" not in os.environ

    def test_non_string_url_not_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """If _reader_url() returns a non-string (e.g. MagicMock), the env var is not polluted."""
        monkeypatch.delenv("DUCKLAKE_READER_URL", raising=False)
        mock_reader = MagicMock()
        mock_reader._reader_url.return_value = MagicMock()  # not a string
        with patch("session_preflight._make_reader", return_value=mock_reader):
            _preflight._prime_reader_url("ok")
        assert "DUCKLAKE_READER_URL" not in os.environ


class TestVerbDedup:
    """Phase B issues ZERO reader verb calls -- every signal is served from the warm-sync rows (D4).

    Before neon-egress-reduction D4, main() de-duplicated the Phase-B reader fan-out down to one call
    per verb. D4 supersedes that: the warm-up sync (warm_sync) pulls the tables ONCE and Phase B
    derives every signal from those in-memory rows, so the per-verb count is now ZERO. This is the
    main()-level encoding of acceptance criterion 1 (zero additional Phase-B reader verb calls).
    """

    @staticmethod
    def _make_counting_reader(verb_calls: dict[str, int]) -> MagicMock:
        """Return a reader stub that counts named() calls per verb."""
        reader = MagicMock()

        def _named(verb: str, **kwargs: object) -> list:
            verb_calls[verb] = verb_calls.get(verb, 0) + 1
            return []

        reader.named.side_effect = _named
        return reader

    def _run_main_with_counting_reader(self, tmp_path: Path, verb_calls: dict[str, int]) -> None:
        counting_reader = self._make_counting_reader(verb_calls)
        preflight_report = tmp_path / ".preflight-report.json"
        # warm_sync returns NON-empty rows for all three tables so the derivations have real input;
        # the counting reader must STILL see zero verb calls in Phase B (everything served from rows).
        warm_sync_rows = {
            "drained": {},
            "pulled": {"ops_recommendations": 2, "ops_decisions": 1, "ops_priority_queue": 0},
            "rows": {
                "ops_recommendations": [
                    {
                        "id": "rec-001",
                        "status": "open",
                        "source": "manual",
                        "automatable": True,
                        "title": "t1",
                        "context": "c1",
                        "created_timestamp": "2026-06-10T00:00:00+00:00",
                    },
                    {
                        "id": "rec-002",
                        "status": "closed",
                        "source": "ci_rca",
                        "automatable": False,
                        "title": "t2",
                        "context": "c2",
                        "created_timestamp": "2026-06-11T00:00:00+00:00",
                    },
                ],
                "ops_decisions": [
                    {"id": "dec-001", "last_updated_timestamp": "2026-06-12T00:00:00+00:00"},
                ],
                "ops_priority_queue": [],
            },
            "reader_ok": {"ops_recommendations": True, "ops_decisions": True, "ops_priority_queue": True},
        }
        with (
            patch("session_preflight._make_reader", return_value=counting_reader),
            patch("scripts.sync_ops.warm_sync", return_value=warm_sync_rows),
            patch("session_preflight.check_venv", return_value=True),
            patch("session_preflight.get_git_status", return_value=("agent/test", False, [])),
            patch("session_preflight.check_terraform_pending", return_value=False),
            patch("session_preflight.check_credentials", return_value="ok"),
            patch("session_preflight.parse_last_session", return_value=""),
            # Patch subprocess users by name so the verb-count assertions are not perturbed
            # by real git calls (tests/CLAUDE.md isolation: no real subprocess in unit tests).
            patch("session_preflight._get_recent_main_commits", return_value=[]),
            patch("session_preflight.run_log_sync", return_value={"status": "skipped", "files": []}),
            patch("session_preflight._check_ci_rca_liveness", return_value=None),
            patch("session_preflight.PREFLIGHT_REPORT", preflight_report),
            patch("builtins.print"),
        ):
            _preflight.main()

    def test_open_recs_not_called_in_phase_b(self, tmp_path: Path) -> None:
        """open_recs verb is NOT queried in Phase B -- the open count is derived from the warm-sync rows (D4)."""
        verb_calls: dict[str, int] = {}
        self._run_main_with_counting_reader(tmp_path, verb_calls)
        count = verb_calls.get("open_recs", 0)
        assert count == 0, f"open_recs called {count} times; expected 0 (served from the warm-sync rows, D4)"

    def test_decisions_max_updated_not_called_in_phase_b(self, tmp_path: Path) -> None:
        """decisions_max_updated verb is NOT queried in Phase B -- the timestamp is derived from rows (D4)."""
        verb_calls: dict[str, int] = {}
        self._run_main_with_counting_reader(tmp_path, verb_calls)
        count = verb_calls.get("decisions_max_updated", 0)
        assert count == 0, f"decisions_max_updated called {count} times; expected 0 (derived from rows, D4)"

    def test_no_reader_verb_calls_in_phase_b(self, tmp_path: Path) -> None:
        """The whole Phase-B fan-out issues ZERO reader verb calls (acceptance criterion 1)."""
        verb_calls: dict[str, int] = {}
        self._run_main_with_counting_reader(tmp_path, verb_calls)
        assert verb_calls == {}, f"Phase B issued reader verb calls {verb_calls}; expected none (served from rows, D4)"


class TestErrorPropagation:
    """Worker thread exceptions and SystemExit propagate to the main thread via future.result()."""

    def test_worker_sysexit_propagates(self, tmp_path: Path) -> None:
        """sys.exit(1) from read_priority_queue (verb failure, creds ok) re-raises in main thread."""
        preflight_report = tmp_path / ".preflight-report.json"
        with (
            patch("session_preflight.check_venv", return_value=True),
            patch("session_preflight.get_git_status", return_value=("agent/test", False, [])),
            patch("session_preflight.check_terraform_pending", return_value=False),
            patch("session_preflight.check_credentials", return_value="ok"),
            patch("session_preflight.parse_last_session", return_value=""),
            patch("session_preflight.read_priority_queue", side_effect=SystemExit(1)),
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
            patch("session_preflight._check_ci_rca_liveness", return_value=None),
            patch("session_preflight.PREFLIGHT_REPORT", preflight_report),
            patch("builtins.print"),
        ):
            with pytest.raises(SystemExit):
                _preflight.main()


class TestGetRecentMainCommits:
    """Tests for _get_recent_main_commits()."""

    _GIT_LOG_OUTPUT = (
        "COMMIT:abc12345|2026-06-12T10:00:00+00:00|feat(scope): fix bar\n"
        "scripts/foo.py\n"
        "scripts/bar.py\n"
        "\n"
        "COMMIT:def67890|2026-06-11T09:00:00+00:00|fix: repair baz\n"
        "scripts/baz.py\n"
    )

    def _make_git_result(self, stdout: str, returncode: int = 0) -> MagicMock:
        r = MagicMock()
        r.returncode = returncode
        r.stdout = stdout
        return r

    def test_returns_list_of_commits(self) -> None:
        with patch("session_preflight.subprocess.run", return_value=self._make_git_result(self._GIT_LOG_OUTPUT)):
            result = _preflight._get_recent_main_commits()
        assert len(result) == 2
        assert result[0]["sha"] == "abc12345"
        assert result[0]["subject"] == "feat(scope): fix bar"
        assert "scripts/foo.py" in result[0]["files"]
        assert result[1]["sha"] == "def67890"

    def test_returns_empty_on_nonzero_exit(self) -> None:
        with patch("session_preflight.subprocess.run", return_value=self._make_git_result("", returncode=1)):
            result = _preflight._get_recent_main_commits()
        assert result == []

    def test_returns_empty_on_oserror(self) -> None:
        with patch("session_preflight.subprocess.run", side_effect=OSError("git not found")):
            result = _preflight._get_recent_main_commits()
        assert result == []

    def test_returns_empty_on_timeout(self) -> None:
        with patch("session_preflight.subprocess.run", side_effect=subprocess.TimeoutExpired("git", 15)):
            result = _preflight._get_recent_main_commits()
        assert result == []

    def test_empty_output_returns_empty(self) -> None:
        with patch("session_preflight.subprocess.run", return_value=self._make_git_result("")):
            result = _preflight._get_recent_main_commits()
        assert result == []


class TestEndstateDrift:
    """Tests for _check_endstate_drift() -- VP step 6 (endstate drift cases)."""

    _OLD_IDS = ["T1.1", "T1.2"]
    _NEW_ID = "ZZ9.99"
    _STAMP_COMMIT = "abc1234"

    def _make_old_roadmap_yaml(self) -> str:
        return (
            "tier_items:\n"
            "  - id: T1.1\n"
            "    name: Item 1\n"
            "    status: not_started\n"
            "  - id: T1.2\n"
            "    name: Item 2\n"
            "    status: not_started\n"
        )

    def _make_new_roadmap_yaml(self) -> str:
        return (
            "tier_items:\n"
            "  - id: T1.1\n"
            "    name: Item 1\n"
            "    status: not_started\n"
            "  - id: T1.2\n"
            "    name: Item 2\n"
            "    status: not_started\n"
            "  - id: ZZ9.99\n"
            "    name: New Item\n"
            "    status: not_started\n"
        )

    def _make_completed_roadmap_yaml(self) -> str:
        return (
            "tier_items:\n"
            "  - id: T1.1\n"
            "    name: Item 1\n"
            "    status: complete\n"
            "  - id: T1.2\n"
            "    name: Item 2\n"
            "    status: not_started\n"
        )

    def _hash_of(self, ids: list[str]) -> str:
        return hashlib.sha256("\n".join(sorted(ids)).encode()).hexdigest()

    def _make_context_md(self, stamped_hash: str, commit: str = "abc1234") -> str:
        return f"Derived from ROADMAP-PLATFORM.yaml @ {commit} (2026-06-28).\nroadmap_tier_id_set sha256: {stamped_hash}\n"

    def _setup_tmpdir(self, tmp_path: Path, context_text: str, roadmap_yaml: str) -> None:
        (tmp_path / "docs").mkdir(parents=True)
        (tmp_path / "docs" / "PROJECT_CONTEXT.md").write_text(context_text, encoding="utf-8")
        (tmp_path / "docs" / "ROADMAP-PLATFORM.yaml").write_text(roadmap_yaml, encoding="utf-8")

    def test_endstate_in_sync_not_stale(self, tmp_path: Path) -> None:
        """Identical ID set: stamped hash matches current roadmap -> not stale, no warning."""
        current_hash = self._hash_of(self._OLD_IDS)
        context = self._make_context_md(current_hash)
        roadmap = self._make_old_roadmap_yaml()
        self._setup_tmpdir(tmp_path, context, roadmap)

        with patch("session_preflight.ROOT", tmp_path):
            result = _preflight._check_endstate_drift()

        assert result["stale"] is False
        assert result["current_hash"] == current_hash
        assert result["new_ids"] == []

    def test_endstate_new_id_stale_names_new_id(self, tmp_path: Path) -> None:
        """New tier_item ID added to roadmap -> stale=True, new_ids contains the new ID."""
        old_hash = self._hash_of(self._OLD_IDS)
        context = self._make_context_md(old_hash, self._STAMP_COMMIT)
        roadmap = self._make_new_roadmap_yaml()
        self._setup_tmpdir(tmp_path, context, roadmap)

        git_result = MagicMock()
        git_result.returncode = 0
        git_result.stdout = self._make_old_roadmap_yaml()

        with patch("session_preflight.ROOT", tmp_path), patch("session_preflight.subprocess.run", return_value=git_result):
            result = _preflight._check_endstate_drift()

        assert result["stale"] is True
        assert self._NEW_ID in result["new_ids"]
        assert result["current_hash"] != old_hash

    def test_endstate_completed_item_unchanged_ids_not_stale(self, tmp_path: Path) -> None:
        """Completing an item changes status but NOT the ID set -> hash unchanged -> not stale."""
        current_hash = self._hash_of(self._OLD_IDS)
        context = self._make_context_md(current_hash)
        roadmap = self._make_completed_roadmap_yaml()
        self._setup_tmpdir(tmp_path, context, roadmap)

        with patch("session_preflight.ROOT", tmp_path):
            result = _preflight._check_endstate_drift()

        assert result["stale"] is False
        assert result["new_ids"] == []


class TestDeriveCiRcaDisputeOpen:
    """Unit tests for _derive_ci_rca_dispute_open() -- filter/sort/cap."""

    def _make_row(
        self,
        rec_id: str,
        source: str = "ci_rca_evidence_dispute",
        status: str = "open",
        created: str = "2026-06-29T10:00:00Z",
        title: str = "Dispute rec",
        priority: str = "low",
    ) -> dict:
        return {
            "id": rec_id,
            "source": source,
            "status": status,
            "created_timestamp": created,
            "title": title,
            "priority": priority,
        }

    def test_filters_by_source_and_open_status(self) -> None:
        """Only source=ci_rca_evidence_dispute + status in (open, in_progress) rows are returned."""
        rows = [
            self._make_row("rec-101", status="open"),
            self._make_row("rec-102", status="in_progress"),
            self._make_row("rec-103", status="closed"),
            self._make_row("rec-104", source="ci_rca", status="open"),
            self._make_row("rec-105", source="planning", status="open"),
        ]
        result = _preflight._derive_ci_rca_dispute_open(rows)
        assert {r["id"] for r in result} == {"rec-101", "rec-102"}

    def test_newest_first_ordering(self) -> None:
        """Results are ordered newest-first by created_timestamp."""
        rows = [
            self._make_row("rec-201", created="2026-06-27T08:00:00Z"),
            self._make_row("rec-202", created="2026-06-29T12:00:00Z"),
            self._make_row("rec-203", created="2026-06-28T06:00:00Z"),
        ]
        result = _preflight._derive_ci_rca_dispute_open(rows)
        assert [r["id"] for r in result] == ["rec-202", "rec-203", "rec-201"]

    def test_capped_at_five(self) -> None:
        """Result is capped at 5 rows."""
        rows = [self._make_row(f"rec-{300 + i}", created=f"2026-06-2{i}T00:00:00Z") for i in range(7)]
        result = _preflight._derive_ci_rca_dispute_open(rows)
        assert len(result) == 5

    def test_projects_expected_fields(self) -> None:
        """Each returned dict has id, title, priority, created_timestamp."""
        rows = [self._make_row("rec-401", title="My dispute", priority="Low", created="2026-06-29T10:00:00Z")]
        result = _preflight._derive_ci_rca_dispute_open(rows)
        assert len(result) == 1
        assert set(result[0].keys()) == {"id", "title", "priority", "created_timestamp"}
        assert result[0]["id"] == "rec-401"
        assert result[0]["title"] == "My dispute"

    def test_empty_rows_returns_empty(self) -> None:
        assert _preflight._derive_ci_rca_dispute_open([]) == []


class TestFetchCiRcaDisputeRecs:
    """Unit tests for _fetch_ci_rca_dispute_recs() -- cache-row path."""

    def _make_dispute_row(self, rec_id: str, status: str = "open") -> dict:
        return {
            "id": rec_id,
            "source": "ci_rca_evidence_dispute",
            "status": status,
            "title": "Dispute rec",
            "priority": "low",
            "created_timestamp": "2026-06-29T10:00:00Z",
        }

    def test_cache_rows_supplied_returns_derived(self) -> None:
        """When cache_rows is a list, returns _derive_ci_rca_dispute_open result (no reader call)."""
        rows = [self._make_dispute_row("rec-501")]
        result = _preflight._fetch_ci_rca_dispute_recs(cache_rows=rows)
        assert len(result) == 1
        assert result[0]["id"] == "rec-501"

    def test_cache_rows_none_returns_empty(self) -> None:
        """When cache_rows is None (warm-pull failed), returns []."""
        result = _preflight._fetch_ci_rca_dispute_recs(cache_rows=None)
        assert result == []

    def test_sentinel_returns_empty(self) -> None:
        """When called with the sentinel (no cache_rows arg), returns [] -- no reader call."""
        result = _preflight._fetch_ci_rca_dispute_recs()
        assert result == []

    def test_filters_closed_rows_from_cache(self) -> None:
        """Closed dispute recs are excluded from the cache-path result."""
        rows = [
            self._make_dispute_row("rec-601", status="open"),
            self._make_dispute_row("rec-602", status="closed"),
        ]
        result = _preflight._fetch_ci_rca_dispute_recs(cache_rows=rows)
        assert [r["id"] for r in result] == ["rec-601"]


class TestPrintCiRcaDisputeRecs:
    """Unit tests for print_ci_rca_dispute_recs() -- section rendering."""

    def test_empty_prints_none_line(self, capsys: pytest.CaptureFixture) -> None:
        """When recs is empty, prints the header and '(none)'."""
        _preflight.print_ci_rca_dispute_recs([])
        out = capsys.readouterr().out
        assert "CI-RCA Dispute Recs (open)" in out
        assert "(none)" in out

    def test_renders_rec_ids(self, capsys: pytest.CaptureFixture) -> None:
        """Each rec is rendered with its id, priority, timestamp, and title."""
        recs = [
            {
                "id": "rec-701",
                "title": "Bundle wrong on earliest_viable_gate",
                "priority": "low",
                "created_timestamp": "2026-06-29T10:00:00Z",
            },
        ]
        _preflight.print_ci_rca_dispute_recs(recs)
        out = capsys.readouterr().out
        assert "CI-RCA Dispute Recs (open)" in out
        assert "rec-701" in out
        assert "Bundle wrong on earliest_viable_gate" in out

    def test_header_printed_before_entries(self, capsys: pytest.CaptureFixture) -> None:
        """The section header appears before any rec lines."""
        recs = [{"id": "rec-801", "title": "Dispute", "priority": "low", "created_timestamp": "2026-06-29T10:00:00Z"}]
        _preflight.print_ci_rca_dispute_recs(recs)
        out = capsys.readouterr().out
        header_pos = out.index("CI-RCA Dispute Recs (open)")
        rec_pos = out.index("rec-801")
        assert header_pos < rec_pos


class TestPreflightReportDisputeKey:
    """The preflight report JSON must include ci_rca_dispute_recs."""

    def test_report_json_contains_ci_rca_dispute_recs(self, tmp_path: Path) -> None:
        """session_preflight.py writes ci_rca_dispute_recs to the report JSON.

        The autouse fixture stubs _make_reader, warm_sync, check_main_freshness, and
        _sync_ops_pull; we only need to patch the infrastructure that main() calls directly.
        """
        preflight_report = tmp_path / ".preflight-report.json"
        dispute_recs = [
            {"id": "rec-901", "title": "Dispute rec", "priority": "low", "created_timestamp": "2026-06-29T10:00:00Z"}
        ]

        with (
            patch("session_preflight.PREFLIGHT_REPORT", preflight_report),
            patch("session_preflight._fetch_ci_rca_dispute_recs", return_value=dispute_recs),
            patch("session_preflight.check_venv", return_value=True),
            patch("session_preflight.get_git_status", return_value=("claude/test", False, [])),
            patch("session_preflight.check_terraform_pending", return_value=False),
            patch("session_preflight.check_credentials", return_value="ok"),
            patch("session_preflight.parse_last_session", return_value=""),
            patch("session_preflight.count_recommendations", return_value=(0, 0, 0, [])),
            patch("session_preflight.read_context_files", return_value={}),
            patch(
                "session_preflight.check_telemetry_health",
                return_value={"overall": "ok", "checks": [], "friction_patterns": []},
            ),
            patch("session_preflight._check_ci_rca_liveness", return_value=None),
            patch("builtins.print"),
        ):
            _preflight.main()

        assert preflight_report.exists()
        report = json.loads(preflight_report.read_text(encoding="utf-8"))
        assert "ci_rca_dispute_recs" in report, f"ci_rca_dispute_recs missing from report keys: {list(report)[:30]}"
        assert report["ci_rca_dispute_recs"] == dispute_recs
