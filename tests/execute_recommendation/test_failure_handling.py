"""Failure cleanup, summary, and scope-drift tests (rec-2709 Wave 2)."""

import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from scripts.execute_recommendation import (
    FailureSummary,
    _handle_failure,
    _infer_failure_class,
    _scope_drift_check,
    emit_failure_summary,
)


class TestFailureCleanup:
    """Tests for _handle_failure() branch push + draft PR creation."""

    def _rec(self) -> dict:
        return {"id": "rec-100", "title": "Add caching layer"}

    def test_handle_failure_pushes_branch(self):
        """_handle_failure calls git push --set-upstream origin agent/rec-100."""
        rec = self._rec()

        with patch("scripts.execute_recommendation.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            _handle_failure("rec-100", rec, 2, "step 2 failed", 1, 5)

        calls = [c.args[0] for c in mock_run.call_args_list]
        push_call = next((c for c in calls if "push" in c), None)
        assert push_call is not None, "Expected push command to be called"
        assert "--set-upstream" in push_call, "Expected --set-upstream in push command"
        assert "origin" in push_call, "Expected origin in push command"
        assert "agent/rec-100" in push_call, "Expected agent/rec-100 in push command"

    def test_handle_failure_creates_draft_pr(self):
        """_handle_failure calls gh pr create --draft with [FAILED] title."""
        rec = self._rec()

        with patch("scripts.execute_recommendation.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            _handle_failure("rec-100", rec, 2, "step 2 failed", 1, 5)

        calls = [c.args[0] for c in mock_run.call_args_list]
        pr_call = next((c for c in calls if "pr" in c and "create" in c), None)
        assert pr_call is not None, "Expected 'pr create' command to be called"
        assert "--draft" in pr_call, "Expected --draft in pr create command"
        assert "--title" in pr_call, "Expected --title in pr create command"

        # Verify the title argument contains [FAILED]
        title_idx = pr_call.index("--title")
        title_value = pr_call[title_idx + 1]
        assert "[FAILED]" in title_value, f"Expected [FAILED] in title, got {title_value}"
        assert "rec-100" in title_value, f"Expected rec-100 in title, got {title_value}"

    def test_handle_failure_tolerates_push_error(self):
        """Push failure is logged but does not raise; draft PR is skipped."""
        rec = self._rec()

        with patch("scripts.execute_recommendation.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(1, "git", stderr="could not read from remote")

            # Must not raise
            try:
                _handle_failure("rec-100", rec, 1, "push test", 0, 3)
            except Exception as exc:
                pytest.fail(f"_handle_failure raised unexpectedly: {exc}")

        # Only the push call should have been attempted (PR creation skipped on push failure)
        calls = [c.args[0] for c in mock_run.call_args_list]
        pr_calls = [c for c in calls if "pr" in c and "create" in c]
        assert len(pr_calls) == 0, f"Expected no PR create calls after push failure, got {len(pr_calls)}"

    def test_handle_failure_tolerates_pr_error(self):
        """PR creation failure is logged but does not raise."""
        rec = self._rec()
        call_count = 0

        def run_side_effect(cmd, **kwargs):
            nonlocal call_count
            call_count += 1
            if "push" in cmd:
                return MagicMock(returncode=0, stdout="", stderr="")
            # gh pr create fails
            raise subprocess.CalledProcessError(1, "gh", stderr="already exists")

        with patch("scripts.execute_recommendation.subprocess.run", side_effect=run_side_effect):
            try:
                _handle_failure("rec-100", rec, 1, "test", 0, 3)
            except Exception as exc:
                pytest.fail(f"_handle_failure raised unexpectedly: {exc}")


class TestFailureSummary:
    """Tests for FailureSummary dataclass and emit_failure_summary."""

    _VALID_PHASES = {
        "planning",
        "critique",
        "implementation",
        "validation",
        "postflight",
        "acceptance",
        "preflight",
        "finalize",
    }
    _VALID_CLASSES = {
        "cli_timeout",
        "parse_error",
        "test_failure",
        "scope_creep",
        "ghost_step",
        "acceptance_mismatch",
        "unknown",
    }

    def test_emit_writes_valid_json(self, tmp_path, monkeypatch):
        """emit_failure_summary writes a JSON file with all keys."""
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

        out_dir = tmp_path / "logs" / "failure-summaries"

        mock_git = MagicMock()
        mock_git.return_value = MagicMock(
            returncode=0,
            stdout="file.py | 5 ++---",
        )

        with (
            patch(
                "scripts.execute_recommendation.subprocess.run",
                mock_git,
            ),
            patch(
                "scripts.execute_recommendation._latest_transcript_path",
                return_value="logs/transcripts/rec-fs-001.md",
            ),
            patch(
                "scripts.execute_recommendation.Path",
                side_effect=lambda p: tmp_path / p,
            ),
        ):
            emit_failure_summary(
                rec_id="rec-fs",
                failure_phase="validation",
                failure_reason="full CI validation failed",
                validation_output="FAILED tests/test_foo.py",
            )

        written = list(out_dir.glob("rec-fs-*.json"))
        assert len(written) == 1, f"Expected 1 file, found {len(written)}"
        data = json.loads(
            written[0].read_text(encoding="utf-8"),
        )

        required_keys = {
            "rec_id",
            "attempt",
            "failure_phase",
            "failure_class",
            "last_transcript_path",
            "git_diff_stat",
            "validation_output",
            "acceptance_output",
            "failure_reason",
        }
        assert required_keys.issubset(data.keys()), f"Missing keys: {required_keys - data.keys()}"
        assert data["rec_id"] == "rec-fs"
        assert data["failure_phase"] in self._VALID_PHASES
        assert data["failure_class"] in self._VALID_CLASSES
        assert data["failure_class"] == "test_failure"

    def test_emit_noop_when_pytest_env_set(
        self,
        tmp_path,
        monkeypatch,
    ):
        """emit_failure_summary is a no-op under PYTEST_CURRENT_TEST."""
        monkeypatch.setenv("PYTEST_CURRENT_TEST", "yes")
        out_dir = tmp_path / "logs" / "failure-summaries"
        out_dir.mkdir(parents=True, exist_ok=True)

        emit_failure_summary(
            rec_id="rec-noop",
            failure_phase="preflight",
            failure_reason="should not write",
        )

        written = list(out_dir.glob("*.json"))
        assert written == [], f"Expected no files when PYTEST_CURRENT_TEST set, found {written}"

    def test_failure_phase_and_class_valid_values(self):
        """failure_phase and failure_class contain valid values."""
        summary: FailureSummary = {
            "rec_id": "rec-enum",
            "attempt": 2,
            "failure_phase": "implementation",
            "failure_class": "cli_timeout",
            "last_transcript_path": "",
            "git_diff_stat": "",
            "validation_output": "",
            "acceptance_output": "",
            "failure_reason": "timed out",
        }
        assert summary["failure_phase"] in self._VALID_PHASES
        assert summary["failure_class"] in self._VALID_CLASSES

    def test_infer_failure_class_timeout(self):
        """_infer_failure_class detects timeout patterns."""
        result = _infer_failure_class(
            "validation",
            "timed out after 600s",
        )
        assert result == "cli_timeout"

    def test_infer_failure_class_parse_error(self):
        """_infer_failure_class detects parse/json patterns."""
        result = _infer_failure_class(
            "preflight",
            "invalid JSON: Expecting value",
        )
        assert result == "parse_error"

    def test_infer_failure_class_test_failure(self):
        """_infer_failure_class detects test failure patterns."""
        result = _infer_failure_class(
            "validation",
            "full CI validation failed",
        )
        assert result == "test_failure"

    def test_infer_failure_class_acceptance(self):
        """_infer_failure_class detects acceptance patterns."""
        result = _infer_failure_class(
            "postflight",
            "post-validation acceptance check failed",
        )
        assert result == "acceptance_mismatch"

    def test_infer_failure_class_unknown(self):
        """_infer_failure_class falls back to unknown."""
        result = _infer_failure_class(
            "preflight",
            "something weird happened",
        )
        assert result == "unknown"

    def test_infer_failure_class_scope(self):
        """_infer_failure_class detects scope drift."""
        result = _infer_failure_class(
            "postflight",
            "scope drift detected",
        )
        assert result == "scope_creep"


class TestScopeDriftCheck:
    """Tests for _scope_drift_check()."""

    def test_no_drift_when_all_files_planned(self):
        """Returns empty list when all changed files match plan steps."""
        steps = [
            {"n": 1, "file": "scripts/foo.py", "action": "modify"},
            {"n": 2, "file": "tests/test_foo.py", "action": "modify"},
        ]
        diff_output = "scripts/foo.py\ntests/test_foo.py\n"
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=diff_output)
            result = _scope_drift_check(steps)
        assert result == []

    def test_unplanned_file_flagged(self):
        """Returns unplanned files that appear in the diff."""
        steps = [{"n": 1, "file": "scripts/foo.py", "action": "modify"}]
        diff_output = "scripts/foo.py\nscripts/unplanned.py\n"
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=diff_output)
            result = _scope_drift_check(steps)
        assert "scripts/unplanned.py" in result

    def test_logs_prefix_excluded(self):
        """Files under logs/ are always excluded from drift."""
        steps = [{"n": 1, "file": "scripts/foo.py", "action": "modify"}]
        diff_output = "scripts/foo.py\nlogs/.execution-state.json\n"
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=diff_output)
            result = _scope_drift_check(steps)
        assert result == []

    def test_requirements_txt_excluded(self):
        """requirements.txt is always excluded from drift (side-effect of dep changes)."""
        steps = [{"n": 1, "file": "scripts/foo.py", "action": "modify"}]
        diff_output = "scripts/foo.py\nrequirements.txt\n"
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=diff_output)
            result = _scope_drift_check(steps)
        assert result == []

    def test_jsonl_files_excluded(self):
        """Any .jsonl file is always excluded (telemetry side-effects)."""
        steps = [{"n": 1, "file": "scripts/foo.py", "action": "modify"}]
        diff_output = "scripts/foo.py\nlogs/.recommendations-log.jsonl\nsome-other.jsonl\n"
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=diff_output)
            result = _scope_drift_check(steps)
        assert result == []

    def test_execute_recommendation_script_excluded(self):
        """scripts/execute_recommendation.py is always excluded (self-modifications)."""
        steps = [{"n": 1, "file": "scripts/foo.py", "action": "modify"}]
        diff_output = "scripts/foo.py\nscripts/execute_recommendation.py\n"
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=diff_output)
            result = _scope_drift_check(steps)
        assert result == []

    def test_git_failure_returns_empty(self):
        """Returns empty list (non-blocking) when git diff fails."""
        steps = [{"n": 1, "file": "scripts/foo.py", "action": "modify"}]
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="")
            result = _scope_drift_check(steps)
        assert result == []

    def test_git_timeout_returns_empty(self):
        """Returns empty list (non-blocking) when git diff times out."""
        steps = [{"n": 1, "file": "scripts/foo.py", "action": "modify"}]
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("git", 30)):
            result = _scope_drift_check(steps)
        assert result == []
