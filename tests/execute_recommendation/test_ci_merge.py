"""CI-wait, PR-merge, and branch cleanup tests (rec-2709 Wave 2)."""

import json
import subprocess
from unittest.mock import MagicMock, patch

from scripts.execute_recommendation import (
    ExecutionPlan,
    cleanup_after_merge,
    merge_pr,
    prune_merged_agent_branches,
    wait_for_ci,
)


class TestWaitForCI:
    """Tests for wait_for_ci()."""

    def _make_run(self, stdout: str, returncode: int = 0) -> MagicMock:
        m = MagicMock()
        m.returncode = returncode
        m.stdout = stdout
        m.stderr = ""
        return m

    def test_success_on_first_poll(self):
        """All checks pass on first poll â€” returns (True, 'success')."""
        checks = json.dumps([{"state": "success"}, {"state": "success"}])
        with patch("scripts.execute_recommendation.subprocess.run") as mock_run:
            mock_run.return_value = self._make_run(checks)
            result, reason = wait_for_ci("agent/rec-100", timeout=60, interval=1)
        assert result is True
        assert reason == "success"

    def test_failure_detected(self):
        """Any check in failure state â€” returns (False, 'failure')."""
        checks = json.dumps([{"state": "success"}, {"state": "failure"}])
        with patch("scripts.execute_recommendation.subprocess.run") as mock_run:
            mock_run.return_value = self._make_run(checks)
            result, reason = wait_for_ci("agent/rec-100", timeout=60, interval=1)
        assert result is False
        assert reason == "failure"

    def test_timeout_when_pending(self):
        """Checks stay pending until timeout â€” returns (False, 'timeout')."""
        checks = json.dumps([{"state": "pending"}])
        with (
            patch("scripts.execute_recommendation.subprocess.run") as mock_run,
            patch("scripts.executor.postflight.time.sleep"),
        ):
            mock_run.return_value = self._make_run(checks)
            result, reason = wait_for_ci("agent/rec-100", timeout=1, interval=1)
        assert result is False
        assert reason == "timeout"

    def test_pending_then_success(self):
        """First poll pending, second poll success â€” returns (True, 'success')."""
        pending = json.dumps([{"state": "pending"}])
        success = json.dumps([{"state": "success"}])
        responses = [self._make_run(pending), self._make_run(success)]
        with (
            patch("scripts.execute_recommendation.subprocess.run") as mock_run,
            patch("scripts.executor.postflight.time.sleep"),
        ):
            mock_run.side_effect = responses
            # Use a timeout that will allow 2 polls but not expire on first
            result, reason = wait_for_ci("agent/rec-100", timeout=120, interval=0)
        assert result is True
        assert reason == "success"

    def test_gh_command_failure_retries(self):
        """Non-zero returncode from gh is retried, eventually succeeds."""
        error_resp = MagicMock(returncode=1, stdout="", stderr="error")
        success_resp = self._make_run(json.dumps([{"state": "success"}]))
        with (
            patch("scripts.execute_recommendation.subprocess.run") as mock_run,
            patch("scripts.executor.postflight.time.sleep"),
        ):
            mock_run.side_effect = [error_resp, success_resp]
            result, reason = wait_for_ci("agent/rec-100", timeout=120, interval=0)
        assert result is True
        assert reason == "success"

    def test_consecutive_gh_failures_escalate(self):
        """5 consecutive gh pr checks failures return (False, 'checks_unavailable')."""
        error_resp = MagicMock(returncode=1, stdout="no checks reported", stderr="")
        with (
            patch("scripts.execute_recommendation.subprocess.run") as mock_run,
            patch("scripts.executor.postflight.time.sleep"),
            patch.dict("os.environ", {"CI_CHECKS_FAIL_THRESHOLD": "5"}),
        ):
            mock_run.return_value = error_resp
            result, reason = wait_for_ci("agent/rec-100", timeout=600, interval=0)
        assert result is False
        assert reason == "checks_unavailable"
        assert mock_run.call_count == 5

    def test_empty_checks_list_waits(self):
        """Empty checks list means no CI yet â€” waits, eventually times out."""
        empty = json.dumps([])
        with (
            patch("scripts.execute_recommendation.subprocess.run") as mock_run,
            patch("scripts.executor.postflight.time.sleep"),
        ):
            mock_run.return_value = self._make_run(empty)
            result, reason = wait_for_ci("agent/rec-100", timeout=1, interval=1)
        assert result is False
        assert reason == "timeout"


class TestMergePR:
    """Tests for merge_pr()."""

    def test_merge_success(self):
        """Successful merge returns (True, None)."""
        with patch("scripts.execute_recommendation.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            ok, err = merge_pr("agent/rec-100")
        assert ok is True
        assert err is None

    def test_merge_conflict(self):
        """CalledProcessError returns (False, error_message)."""
        with patch("scripts.execute_recommendation.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(1, "gh", stderr="merge conflict")
            ok, err = merge_pr("agent/rec-100")
        assert ok is False
        assert err is not None
        assert "merge conflict" in err

    def test_merge_subprocess_error(self):
        """Generic CalledProcessError returns (False, non-None message)."""
        with patch("scripts.execute_recommendation.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(128, "gh", stderr="fatal error")
            ok, err = merge_pr("agent/rec-100")
        assert ok is False
        assert err is not None


class TestCleanupAfterMerge:
    """Tests for cleanup_after_merge()."""

    def test_cleanup_success(self):
        """All git commands succeed â€” returns True."""
        responses = [
            MagicMock(returncode=0, stderr="", stdout=""),  # git checkout main
            MagicMock(returncode=0, stderr="", stdout="No local changes to save"),  # git stash
            MagicMock(returncode=0, stderr="", stdout=""),  # git pull
            MagicMock(returncode=0, stderr="", stdout=""),  # git branch -d
            MagicMock(returncode=0, stderr="", stdout=""),  # git push origin --delete
        ]
        with (
            patch("scripts.executor.postflight.subprocess.run") as mock_run,
            patch("scripts.executor.postflight.clear_checkpoint", return_value=True),
        ):
            mock_run.side_effect = responses
            result = cleanup_after_merge("agent/rec-100")
        assert result is True

    def test_local_branch_already_deleted(self):
        """git branch -d fails (already deleted) â€” still returns True (non-critical)."""
        responses = [
            MagicMock(returncode=0, stderr="", stdout=""),  # checkout main
            MagicMock(returncode=0, stderr="", stdout="No local changes to save"),  # git stash (no-op)
            MagicMock(returncode=0, stderr="", stdout=""),  # git pull
            MagicMock(returncode=1, stderr="error: branch not found", stdout=""),  # delete branch - fails
            MagicMock(returncode=0, stderr="", stdout=""),  # git push origin --delete
        ]
        with (
            patch("scripts.executor.postflight.subprocess.run") as mock_run,
            patch("scripts.executor.postflight.clear_checkpoint", return_value=True),
            patch("pathlib.Path.exists", return_value=False),
        ):
            mock_run.side_effect = responses
            result = cleanup_after_merge("agent/rec-100")
        assert result is True

    def test_checkout_failure_returns_false(self):
        """CalledProcessError on fallback checkout - returns False."""
        with patch("scripts.executor.postflight.subprocess.run") as mock_run:
            # First checkout returns non-zero (soft failure), then fallback raises
            mock_run.side_effect = [
                MagicMock(returncode=1, stderr="detached HEAD", stdout=""),
                subprocess.CalledProcessError(1, "git"),
            ]
            result = cleanup_after_merge("agent/rec-100")
        assert result is False


class TestPruneMergedAgentBranches:
    """Tests for prune_merged_agent_branches()."""

    def test_deletes_merged_branches(self):
        """Merged branches are deleted locally and remotely."""
        responses = [
            MagicMock(returncode=0, stdout="  agent/rec-100\n  agent/rec-200\n"),  # git branch --list
            MagicMock(returncode=0),  # merge-base --is-ancestor rec-100
            MagicMock(returncode=0, stderr=""),  # git branch -d rec-100
            MagicMock(returncode=0),  # git push origin --delete rec-100
            MagicMock(returncode=0),  # merge-base --is-ancestor rec-200
            MagicMock(returncode=0, stderr=""),  # git branch -d rec-200
            MagicMock(returncode=0),  # git push origin --delete rec-200
        ]
        with patch("scripts.execute_recommendation.subprocess.run") as mock_run:
            mock_run.side_effect = responses
            prune_merged_agent_branches()
        assert mock_run.call_count == 7

    def test_skips_unmerged_branches(self):
        """Branches not merged to main are left alone."""
        responses = [
            MagicMock(returncode=0, stdout="  agent/rec-100\n"),  # git branch --list
            MagicMock(returncode=1),  # merge-base --is-ancestor fails (not merged)
        ]
        with patch("scripts.execute_recommendation.subprocess.run") as mock_run:
            mock_run.side_effect = responses
            prune_merged_agent_branches()
        assert mock_run.call_count == 2

    def test_no_branches(self):
        """No agent branches found -- returns cleanly."""
        with patch("scripts.execute_recommendation.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="")
            prune_merged_agent_branches()
        mock_run.assert_called_once()

    def test_list_fails(self):
        """git branch --list fails -- returns without error."""
        with patch("scripts.execute_recommendation.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1)
            prune_merged_agent_branches()
        mock_run.assert_called_once()

    def test_local_delete_fails_skips_remote(self):
        """Local branch delete fails -- skips remote delete for that branch."""
        responses = [
            MagicMock(returncode=0, stdout="  agent/rec-100\n"),  # git branch --list
            MagicMock(returncode=0),  # merge-base --is-ancestor
            MagicMock(returncode=1, stderr="branch not found"),  # git branch -d fails
        ]
        with patch("scripts.execute_recommendation.subprocess.run") as mock_run:
            mock_run.side_effect = responses
            prune_merged_agent_branches()
        assert mock_run.call_count == 3


class TestFinalizeAutoMerge:
    """Tests for finalize() with no_merge=True/False."""

    def _make_plan(self) -> ExecutionPlan:
        return ExecutionPlan(
            rec_id="rec-100",
            slug="rec-100",
            revision=1,
            timestamp="2026-03-31T10:00:00Z",
            status="approved",
            model="test",
            tokens_used=100,
            steps=[],
            plan_text="",
        )

    def test_no_merge_flag_stops_at_pr(self):
        """With no_merge=True, finalize polls CI but does not merge."""
        with (
            patch("scripts.execute_recommendation.subprocess.run") as mock_run,
            patch("scripts.executor.postflight.wait_for_ci") as mock_ci,
        ):
            mock_ci.return_value = (True, "success")
            # branch + diff + push + pr create + view URL + pr ready + view title + fetch + merge + commit + push
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout="agent/rec-100\n"),  # git branch --show-current
                MagicMock(returncode=0),  # push
                MagicMock(returncode=0, stdout="https://github.com/pr/1\n"),  # pr create
                MagicMock(returncode=0, stdout="https://github.com/pr/1\n"),  # pr view
                MagicMock(returncode=0),  # gh pr ready
                MagicMock(returncode=0, stdout="rec-100: Test title\n"),  # gh pr view title
                MagicMock(returncode=0),  # git fetch origin main
                MagicMock(returncode=0, stdout="Already up to date."),  # git merge origin/main
                MagicMock(returncode=0),  # git commit (inside safe_merge)
                MagicMock(returncode=0),  # git push origin branch
            ]
            from scripts.execute_recommendation import finalize

            result = finalize("rec-100", no_merge=True)
        assert result == "https://github.com/pr/1"
        mock_ci.assert_called_once()

    def test_full_cycle_ci_pass_and_merge(self):
        """With no_merge=False, finalize waits for CI and merges on success."""
        with (
            patch("scripts.execute_recommendation.subprocess.run") as mock_run,
            patch("scripts.executor.postflight.wait_for_ci") as mock_ci,
            patch("scripts.executor.postflight.merge_pr") as mock_merge,
            patch("scripts.executor.postflight.cleanup_after_merge") as mock_cleanup,
            patch("scripts.executor.postflight._run_verifiers_gate", return_value=True),
        ):
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout="agent/rec-100\n"),  # git branch --show-current
                MagicMock(returncode=0),  # push
                MagicMock(returncode=0, stdout="https://github.com/pr/1\n"),  # pr create
                MagicMock(returncode=0, stdout="https://github.com/pr/1\n"),  # pr view
                MagicMock(returncode=0),  # gh pr ready
                MagicMock(returncode=0, stdout="rec-100: Test title\n"),  # gh pr view title
                MagicMock(returncode=0),  # git fetch origin main
                MagicMock(returncode=0, stdout="Already up to date."),  # git merge origin/main
                MagicMock(returncode=0),  # git commit (inside safe_merge)
                MagicMock(returncode=0),  # git push origin branch
            ]
            mock_ci.return_value = (True, "success")
            mock_merge.return_value = (True, None)
            mock_cleanup.return_value = True
            from scripts.execute_recommendation import finalize

            result = finalize("rec-100", no_merge=False)
        assert result == "https://github.com/pr/1"
        mock_ci.assert_called_once()
        mock_merge.assert_called_once()
        mock_cleanup.assert_called_once()

    def test_ci_timeout_returns_none(self):
        """CI timeout causes finalize to return None."""
        with (
            patch("scripts.execute_recommendation.subprocess.run") as mock_run,
            patch("scripts.executor.postflight.wait_for_ci") as mock_ci,
            patch("scripts.executor.postflight.merge_pr") as mock_merge,
            patch("scripts.executor.postflight._run_verifiers_gate", return_value=True),
        ):
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout="agent/rec-100\n"),  # git branch --show-current
                MagicMock(returncode=0),
                MagicMock(returncode=0, stdout="https://github.com/pr/1\n"),
                MagicMock(returncode=0, stdout="https://github.com/pr/1\n"),
                MagicMock(returncode=0),  # gh pr ready
                MagicMock(returncode=0, stdout="rec-100: Test title\n"),  # gh pr view title
                MagicMock(returncode=0),  # git fetch origin main
                MagicMock(returncode=0, stdout="Already up to date."),  # git merge origin/main
                MagicMock(returncode=0),  # git commit (inside safe_merge)
                MagicMock(returncode=0),  # git push origin branch
            ]
            mock_ci.return_value = (False, "timeout")
            from scripts.execute_recommendation import finalize

            result = finalize("rec-100", no_merge=False)
        assert result is None
        mock_merge.assert_not_called()

    def test_merge_failure_triggers_agent_recovery(self):
        """merge_pr failure triggers _agent_merge_recovery; returns None when all attempts fail."""
        with (
            patch("scripts.execute_recommendation.subprocess.run") as mock_run,
            patch("scripts.executor.postflight.wait_for_ci") as mock_ci,
            patch("scripts.executor.postflight.merge_pr") as mock_merge,
            patch("scripts.executor.postflight._agent_merge_recovery", return_value=(False, "still failing")) as mock_recovery,
            patch("scripts.executor.postflight._create_postmortem_recommendation"),
            patch("scripts.executor.postflight._run_verifiers_gate", return_value=True),
        ):
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout="agent/rec-100\n"),  # git branch --show-current
                MagicMock(returncode=0),  # git push --set-upstream
                MagicMock(returncode=0, stdout="No local changes to save"),  # gh pr create
                MagicMock(returncode=0, stdout="https://github.com/pr/1\n"),  # gh pr view url
                MagicMock(returncode=0),  # gh pr ready
                MagicMock(returncode=0, stdout="rec-100: Test title\n"),  # gh pr view title
                MagicMock(returncode=0),  # git fetch origin main
                MagicMock(returncode=0, stdout="Already up to date."),  # git merge origin/main
                MagicMock(returncode=0),  # git commit (inside safe_merge)
                MagicMock(returncode=0),  # git push origin branch
            ]
            mock_ci.return_value = (True, "success")
            mock_merge.return_value = (False, "merge conflict: diverged")
            from scripts.execute_recommendation import finalize

            result = finalize("rec-100", no_merge=False)
        assert result is None, "expected None when all recovery attempts fail"
        assert mock_recovery.call_count == 2, "expected 2 recovery attempts (MERGE_RECOVERY_RETRIES default)"
