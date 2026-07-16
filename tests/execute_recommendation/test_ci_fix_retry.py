"""CI-fix retry loop and hotfix branch tests (rec-2709 Wave 2)."""

from unittest.mock import MagicMock, patch

from scripts.execute_recommendation import (
    create_hotfix_branch,
    file_hotfix_rec,
)


class TestCIFixRetry:
    """Tests for _get_ci_failure_details, _fix_ci_failure, and the finalize retry loop."""

    def test_get_ci_failure_details_success(self):
        """Returns stdout from gh pr checks --output text."""
        from scripts.execute_recommendation import _get_ci_failure_details

        with patch("scripts.executor.postflight.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="FAIL: lint\n", stderr="")
            result = _get_ci_failure_details("agent/rec-100")
        assert "FAIL: lint" in result

    def test_get_ci_failure_details_subprocess_error(self):
        """Returns fallback string if subprocess raises."""
        from scripts.execute_recommendation import _get_ci_failure_details

        with patch("scripts.executor.postflight.subprocess.run", side_effect=Exception("oops")):
            result = _get_ci_failure_details("agent/rec-100")
        assert result == "(could not retrieve CI failure details)"

    def test_fix_ci_failure_commits_and_pushes_when_changes_made(self):
        """When copilot makes changes, fix is committed and pushed; returns True."""
        from scripts.execute_recommendation import _fix_ci_failure

        mock_val_proc = MagicMock()
        mock_val_proc.communicate.return_value = ("", "")
        mock_val_proc.returncode = 0
        mock_val_proc.__enter__ = MagicMock(return_value=mock_val_proc)
        mock_val_proc.__exit__ = MagicMock(return_value=False)

        with (
            patch("scripts.executor.postflight._get_ci_failure_details", return_value="error"),
            patch("scripts.executor.postflight.llm_call") as mock_copilot,
            patch("scripts.executor.postflight.subprocess.Popen", return_value=mock_val_proc),
            patch("scripts.executor.postflight.subprocess.run") as mock_run,
        ):
            mock_copilot.return_value = MagicMock(exit_code=0, tokens_in=100, tokens_out=0)
            # diff --name-only, diff --cached, git add, git commit, git push
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout="file.py\n"),  # diff --name-only (changed)
                MagicMock(returncode=0, stdout=""),  # diff --cached
                MagicMock(returncode=0),  # git add
                MagicMock(returncode=0, stdout="", stderr=""),  # git commit
                MagicMock(returncode=0),  # git push
            ]
            result = _fix_ci_failure("rec-100", "agent/rec-100", "failure")
        assert result is True

    def test_fix_ci_failure_returns_false_when_no_changes(self):
        """When copilot makes no file changes, returns False."""
        from scripts.execute_recommendation import _fix_ci_failure

        mock_val_proc = MagicMock()
        mock_val_proc.communicate.return_value = ("", "")
        mock_val_proc.returncode = 0
        mock_val_proc.__enter__ = MagicMock(return_value=mock_val_proc)
        mock_val_proc.__exit__ = MagicMock(return_value=False)

        with (
            patch("scripts.executor.postflight._get_ci_failure_details", return_value=""),
            patch("scripts.executor.postflight.llm_call") as mock_copilot,
            patch("scripts.executor.postflight.subprocess.Popen", return_value=mock_val_proc),
            patch("scripts.executor.postflight.subprocess.run") as mock_run,
        ):
            mock_copilot.return_value = MagicMock(exit_code=0, tokens_in=10, tokens_out=0)
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout=""),  # diff --name-only (no changes)
                MagicMock(returncode=0, stdout=""),  # diff --cached
            ]
            result = _fix_ci_failure("rec-100", "agent/rec-100", "failure")
        assert result is False

    def test_fix_ci_failure_tolerates_copilot_error(self):
        """If copilot call errors, returns False without raising."""
        from scripts.execute_recommendation import _fix_ci_failure

        mock_val_proc = MagicMock()
        mock_val_proc.communicate.return_value = ("", "")
        mock_val_proc.returncode = 0
        mock_val_proc.__enter__ = MagicMock(return_value=mock_val_proc)
        mock_val_proc.__exit__ = MagicMock(return_value=False)

        with (
            patch("scripts.executor.postflight._get_ci_failure_details", return_value=""),
            patch("scripts.executor.postflight.llm_call", side_effect=Exception("timeout")),
            patch("scripts.executor.postflight.subprocess.Popen", return_value=mock_val_proc),
            patch("scripts.executor.postflight.subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            result = _fix_ci_failure("rec-100", "agent/rec-100", "failure")
        assert result is False

    def test_finalize_retries_on_ci_failure(self):
        """finalize() calls _fix_ci_failure and retries CI when CI fails."""
        with (
            patch("scripts.executor.postflight.subprocess.run") as mock_run,
            patch("scripts.executor.postflight.wait_for_ci") as mock_ci,
            patch("scripts.executor.postflight._fix_ci_failure") as mock_fix,
            patch("scripts.executor.postflight.merge_pr") as mock_merge,
            patch("scripts.executor.postflight.cleanup_after_merge"),
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
            # CI fails once, fix makes a change, CI passes on second poll
            mock_ci.side_effect = [(False, "failure"), (True, "success")]
            mock_fix.return_value = True
            mock_merge.return_value = (True, None)
            from scripts.execute_recommendation import finalize

            result = finalize("rec-100", no_merge=False)
        assert result == "https://github.com/pr/1"
        assert mock_ci.call_count == 2
        mock_fix.assert_called_once()

    def test_finalize_gives_up_if_fix_produces_no_changes(self):
        """finalize() returns None if fix attempt produces no changes."""
        with (
            patch("scripts.executor.postflight.subprocess.run") as mock_run,
            patch("scripts.executor.postflight.wait_for_ci") as mock_ci,
            patch("scripts.executor.postflight._fix_ci_failure") as mock_fix,
            patch(
                "scripts.execute_recommendation.load_recommendation",
                return_value={"id": "rec-100", "title": "Test", "status": "open", "risk": "low"},
            ),
            patch("scripts.executor.postflight.update_recommendation_status"),
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
            mock_ci.return_value = (False, "failure")
            mock_fix.return_value = False
            from scripts.execute_recommendation import finalize

            result = finalize("rec-100", no_merge=False)
        assert result is None

    def test_finalize_ci_timeout_skips_fix(self):
        """finalize() does not attempt fix on CI timeout."""
        with (
            patch("scripts.executor.postflight.subprocess.run") as mock_run,
            patch("scripts.executor.postflight.wait_for_ci") as mock_ci,
            patch("scripts.executor.postflight._fix_ci_failure") as mock_fix,
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
        mock_fix.assert_not_called()

    def test_finalize_checks_unavailable_skips_fix_ci_failure(self):
        """checks_unavailable reason bypasses _fix_ci_failure and goes straight to agent escalation."""
        with (
            patch("scripts.executor.postflight.subprocess.run") as mock_run,
            patch("scripts.executor.postflight.wait_for_ci") as mock_ci,
            patch("scripts.executor.postflight._fix_ci_failure") as mock_fix,
            patch(
                "scripts.executor.postflight._agent_merge_recovery",
                return_value=(False, "still failing"),
            ),
            patch("scripts.executor.postflight._create_postmortem_recommendation"),
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
            mock_ci.return_value = (False, "checks_unavailable")
            from scripts.execute_recommendation import finalize

            result = finalize("rec-100", no_merge=False)
        assert result is None
        mock_fix.assert_not_called()  # _fix_ci_failure must never be called for checks_unavailable

    def test_finalize_creates_postmortem_when_all_retries_exhausted(self, tmp_path):
        """When all CI fix retries fail, finalize writes a postmortem rec and marks the rec failed."""
        import json as _json

        jsonl_file = tmp_path / ".recommendations-log.jsonl"
        jsonl_file.write_text(
            _json.dumps({"id": "rec-100", "title": "t", "status": "open"}) + "\n",
            encoding="utf-8",
        )
        with (
            patch("scripts.executor.postflight.subprocess.run") as mock_run,
            patch("scripts.executor.postflight.wait_for_ci") as mock_ci,
            patch("scripts.executor.postflight._fix_ci_failure") as mock_fix,
            patch("scripts.executor.jsonl_store.RECS_JSONL", jsonl_file),
            patch("scripts.executor.postflight.update_recommendation_status") as mock_update,
            patch("scripts.executor.postflight._create_postmortem_recommendation") as mock_pm,
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
            # CI fails on every poll (initial + after each fix)
            mock_ci.return_value = (False, "failure")
            mock_fix.return_value = True  # fix produces changes but CI keeps failing

            from scripts.execute_recommendation import finalize

            result = finalize("rec-100", no_merge=False)

        assert result is None
        mock_pm.assert_called_once()
        pm_call_args = mock_pm.call_args[0]
        assert pm_call_args[0] == "rec-100"
        assert "agent/rec-100" in pm_call_args[1]
        mock_update.assert_called_once()
        update_kwargs = mock_update.call_args[0][1]
        assert update_kwargs["execution_result"] == "ci_failed_3_times"
        assert update_kwargs["status"] == "failed"


class TestHotfixBranch:
    """Tests for create_hotfix_branch() and file_hotfix_rec()."""

    def test_create_hotfix_branch_returns_correct_name(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = create_hotfix_branch("rec-170", "acceptance-cmd")
        assert result == "agent/rec-rec-170-hotfix-acceptance-cmd"

    def test_create_hotfix_branch_calls_git_checkout(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            create_hotfix_branch("rec-170", "some-fix")
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert "git" in call_args
        assert "checkout" in call_args
        assert "-b" in call_args
        assert "agent/rec-rec-170-hotfix-some-fix" in call_args

    def test_file_hotfix_rec_creates_entry(self, tmp_path):
        with patch("scripts.ops_data_portal.file_rec", return_value="rec-600") as mock_file_rec:
            new_id = file_hotfix_rec("rec-170", "acceptance-cmd", "Fixed broken acceptance")

        assert new_id == "rec-600"
        mock_file_rec.assert_called_once()
        call_fields = mock_file_rec.call_args[0][0]
        assert call_fields["source"] == "executor-hotfix"
        assert call_fields["status"] == "open"
        assert "rec-170" in call_fields["context"]

    def test_file_hotfix_rec_generates_next_id(self, tmp_path):
        with patch("scripts.ops_data_portal.file_rec", return_value="rec-611") as mock_file_rec:
            new_id = file_hotfix_rec("rec-005", "my-fix", "Some fix")

        assert new_id == "rec-611"
        mock_file_rec.assert_called_once()

    def test_file_hotfix_rec_references_parent(self, tmp_path):
        with patch("scripts.ops_data_portal.file_rec", return_value="rec-612") as mock_file_rec:
            file_hotfix_rec("rec-170", "slug", "Fix description here")

        call_fields = mock_file_rec.call_args[0][0]
        assert "rec-170" in call_fields["context"]
        assert "slug" in call_fields["context"]
