"""Tests for scripts/delegate_runner.py.

Mocks all subprocess calls -- no real Copilot CLI or gh CLI invocations.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.delegate_runner import (
    capture_delegate_telemetry,
    delegate_task,
    poll_delegate_pr,
)


class TestDelegateTask:
    """Tests for delegate_task()."""

    def test_delegate_task_parses_pr_url(self) -> None:
        """PR URL is extracted from subprocess stdout when present."""
        mock_proc = MagicMock()
        mock_proc.__enter__ = lambda s: s
        mock_proc.__exit__ = MagicMock(return_value=False)
        mock_proc.communicate.return_value = (
            "Delegated task. PR: https://github.com/owner/repo/pull/42\n",
            "",
        )

        with (
            patch("scripts.delegate_runner.subprocess.Popen", return_value=mock_proc),
            patch("scripts.delegate_runner.kill_process_tree"),
            patch("shutil.which", return_value="/usr/bin/copilot"),
        ):
            result = delegate_task("Add a comment to README.md", "rec-042")

        assert result["status"] == "delegated"
        assert result["pr_url"] == "https://github.com/owner/repo/pull/42"
        assert result["rec_id"] == "rec-042"

    def test_delegate_task_handles_error_no_pr_url(self) -> None:
        """Returns status=failed when no PR URL is found in output."""
        mock_proc = MagicMock()
        mock_proc.__enter__ = lambda s: s
        mock_proc.__exit__ = MagicMock(return_value=False)
        mock_proc.communicate.return_value = ("Some unexpected output.\n", "")

        with (
            patch("scripts.delegate_runner.subprocess.Popen", return_value=mock_proc),
            patch("scripts.delegate_runner.kill_process_tree"),
            patch("shutil.which", return_value="/usr/bin/copilot"),
        ):
            result = delegate_task("Add a comment to README.md", "rec-042")

        assert result["status"] == "failed"
        assert "No PR URL found" in result["error"]
        assert result["rec_id"] == "rec-042"

    def test_delegate_task_handles_timeout(self) -> None:
        """Returns status=failed when subprocess times out."""
        mock_proc = MagicMock()
        mock_proc.__enter__ = lambda s: s
        mock_proc.__exit__ = MagicMock(return_value=False)
        mock_proc.communicate.side_effect = subprocess.TimeoutExpired(cmd="copilot", timeout=120)
        mock_proc.pid = 9999

        with (
            patch("scripts.delegate_runner.subprocess.Popen", return_value=mock_proc),
            patch("scripts.delegate_runner.kill_process_tree") as mock_kill,
            patch("shutil.which", return_value="/usr/bin/copilot"),
        ):
            result = delegate_task("task", "rec-001")

        assert result["status"] == "failed"
        assert "timed out" in result["error"]
        mock_kill.assert_called_once_with(9999)

    def test_delegate_task_handles_missing_copilot(self) -> None:
        """Returns status=failed when copilot CLI is not in PATH."""
        with patch("shutil.which", return_value=None):
            result = delegate_task("task", "rec-001")

        assert result["status"] == "failed"
        assert "not found in PATH" in result["error"]

    def test_delegate_task_handles_oserror(self) -> None:
        """Returns status=failed when Popen raises OSError."""
        with (
            patch("scripts.delegate_runner.subprocess.Popen", side_effect=OSError("permission denied")),
            patch("shutil.which", return_value="/usr/bin/copilot"),
        ):
            result = delegate_task("task", "rec-001")

        assert result["status"] == "failed"
        assert "permission denied" in result["error"]


class TestPollDelegatePr:
    """Tests for poll_delegate_pr()."""

    def test_poll_delegate_pr_returns_merged(self) -> None:
        """Returns status=merged when PR state is MERGED."""
        gh_output = json.dumps(
            {
                "state": "MERGED",
                "commits": [{"messageHeadline": "feat: add thing"}],
                "statusCheckRollup": [{"conclusion": "SUCCESS"}],
            }
        )

        with patch(
            "scripts.delegate_runner.subprocess.run",
            return_value=MagicMock(returncode=0, stdout=gh_output, stderr=""),
        ):
            result = poll_delegate_pr("https://github.com/owner/repo/pull/42", timeout_secs=5)

        assert result["status"] == "merged"
        assert result["commits"] == 1
        assert result["ci_status"] == "SUCCESS"

    def test_poll_delegate_pr_returns_closed(self) -> None:
        """Returns status=closed when PR state is CLOSED."""
        gh_output = json.dumps(
            {
                "state": "CLOSED",
                "commits": [],
                "statusCheckRollup": [],
            }
        )

        with patch(
            "scripts.delegate_runner.subprocess.run",
            return_value=MagicMock(returncode=0, stdout=gh_output, stderr=""),
        ):
            result = poll_delegate_pr("https://github.com/owner/repo/pull/42", timeout_secs=5)

        assert result["status"] == "closed"

    def test_poll_delegate_pr_gh_error(self) -> None:
        """Returns status=failed when gh CLI returns non-zero exit code."""
        with patch(
            "scripts.delegate_runner.subprocess.run",
            return_value=MagicMock(returncode=1, stdout="", stderr="gh: not found"),
        ):
            result = poll_delegate_pr("https://github.com/owner/repo/pull/42", timeout_secs=5)

        assert result["status"] == "failed"
        assert "gh error" in result["ci_status"]


class TestCaptureDelegateTelemetry:
    """Tests for capture_delegate_telemetry()."""

    def test_capture_delegate_telemetry_writes_jsonl(self, tmp_path: Path) -> None:
        """Telemetry entry is written to JSONL with correct fields."""
        gh_output = json.dumps(
            {
                "commits": [
                    {"messageHeadline": "feat: rec-042 add timeout"},
                    {"messageHeadline": "test: add tests for timeout"},
                ],
                "additions": 25,
                "deletions": 3,
                "statusCheckRollup": [{"conclusion": "SUCCESS"}],
            }
        )

        telemetry_path = tmp_path / "logs" / ".delegate-telemetry.jsonl"

        with (
            patch(
                "scripts.delegate_runner.subprocess.run",
                return_value=MagicMock(returncode=0, stdout=gh_output, stderr=""),
            ),
            patch("scripts.delegate_runner.TELEMETRY_LOG", telemetry_path),
        ):
            capture_delegate_telemetry("https://github.com/owner/repo/pull/42", "rec-042")

        assert telemetry_path.exists()
        line = json.loads(telemetry_path.read_text(encoding="utf-8").strip())
        assert line["rec_id"] == "rec-042"
        assert line["pr_url"] == "https://github.com/owner/repo/pull/42"
        assert len(line["commits"]) == 2
        assert line["diff_additions"] == 25
        assert line["diff_deletions"] == 3
        assert line["ci_status"] == "SUCCESS"

    def test_capture_delegate_telemetry_handles_malformed_json(self, tmp_path: Path) -> None:
        """Gracefully degrades when gh returns malformed JSON."""
        telemetry_path = tmp_path / "logs" / ".delegate-telemetry.jsonl"

        with (
            patch(
                "scripts.delegate_runner.subprocess.run",
                return_value=MagicMock(returncode=0, stdout="not valid json", stderr=""),
            ),
            patch("scripts.delegate_runner.TELEMETRY_LOG", telemetry_path),
        ):
            capture_delegate_telemetry("https://github.com/owner/repo/pull/99", "rec-099")

        assert telemetry_path.exists()
        line = json.loads(telemetry_path.read_text(encoding="utf-8").strip())
        assert line["rec_id"] == "rec-099"
        assert line["commits"] == []
        assert line["diff_additions"] == 0
        assert line["ci_status"] == "unknown"
