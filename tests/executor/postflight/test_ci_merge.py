"""postflight CI-wait / merge / cleanup / finalize / event-emission tests: wait_for_ci, merge_pr,
cleanup_after_merge, finalize (rec-2709 Wave 5).
"""

from __future__ import annotations

import itertools
import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from scripts.executor.postflight import (
    _code_review_gate,
    _scope_drift_check,
    cleanup_after_merge,
    finalize,
    merge_pr,
    wait_for_ci,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _gh_checks_result(states: list[str], returncode: int = 0) -> MagicMock:
    """Create a mock subprocess.run result for gh pr checks output."""
    checks = [{"state": s} for s in states]
    mock = MagicMock()
    mock.returncode = returncode
    mock.stdout = json.dumps(checks)
    mock.stderr = ""
    return mock


class TestWaitForCi:
    """Tests for wait_for_ci()."""

    def test_returns_success_when_all_checks_pass(self) -> None:
        success_result = _gh_checks_result(["success", "success"])
        with patch("subprocess.run", return_value=success_result), patch("time.sleep"):
            ok, reason = wait_for_ci("agent/my-branch", timeout=60, interval=5)
        assert ok is True
        assert reason == "success"

    def test_returns_failure_when_any_check_fails(self) -> None:
        fail_result = _gh_checks_result(["success", "failure"])
        with patch("subprocess.run", return_value=fail_result), patch("time.sleep"):
            ok, reason = wait_for_ci("agent/my-branch", timeout=60, interval=5)
        assert ok is False
        assert reason == "failure"

    def test_returns_timeout_when_time_runs_out(self) -> None:
        pending_result = _gh_checks_result(["pending"])
        with (
            patch("subprocess.run", return_value=pending_result),
            patch("time.sleep"),
            # itertools.repeat(61) (not a finite list) so an incidental extra time.time() call
            # (e.g. from logging.LogRecord's own timestamp, per log line emitted) never raises
            # StopIteration -- the test only cares that time appears to have passed the deadline.
            patch("time.time", side_effect=itertools.chain([0, 0], itertools.repeat(61))),
        ):
            ok, reason = wait_for_ci("agent/my-branch", timeout=60, interval=5)
        assert ok is False
        assert reason == "timeout"

    def test_returns_checks_unavailable_after_consecutive_failures(self) -> None:
        fail_gh = MagicMock(returncode=1, stdout="", stderr="not found")
        threshold = 3
        with (
            patch("subprocess.run", return_value=fail_gh),
            patch("time.sleep"),
            patch("time.time", return_value=0),
            patch.dict("os.environ", {"CI_CHECKS_FAIL_THRESHOLD": str(threshold), "CI_EARLY_POLL_COUNT": "0"}),
        ):
            ok, reason = wait_for_ci("agent/my-branch", timeout=600, interval=1)
        assert ok is False
        assert reason == "checks_unavailable"

    def test_handles_dict_state_response(self) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps({"state": "success"})
        with patch("subprocess.run", return_value=mock_result), patch("time.sleep"):
            ok, reason = wait_for_ci("agent/my-branch", timeout=60, interval=5)
        assert ok is True
        assert reason == "success"

    def test_handles_empty_checks_list(self) -> None:
        """Empty checks list → pending, continues polling until timeout."""
        empty_result = MagicMock(returncode=0, stdout="[]", stderr="")
        with (
            patch("subprocess.run", return_value=empty_result),
            patch("time.sleep"),
            # itertools.repeat(61), same rationale as test_returns_timeout_when_time_runs_out above.
            patch("time.time", side_effect=itertools.chain([0, 0, 0, 0], itertools.repeat(61))),
        ):
            ok, reason = wait_for_ci("agent/my-branch", timeout=60, interval=1)
        assert ok is False
        assert reason == "timeout"


class TestMergePr:
    """Tests for merge_pr()."""

    def test_returns_true_on_success(self) -> None:
        stash_ok = MagicMock(returncode=0, stdout="No local changes to save")
        merge_ok = MagicMock(returncode=0)

        with patch("subprocess.run", side_effect=[stash_ok, merge_ok]):
            ok, err = merge_pr("agent/my-branch")

        assert ok is True
        assert err is None

    def test_stashes_and_pops_when_dirty(self) -> None:
        stash_ok = MagicMock(returncode=0, stdout="Saved working directory")
        merge_ok = MagicMock(returncode=0)
        pop_ok = MagicMock(returncode=0)

        calls = [stash_ok, merge_ok, pop_ok]
        run_calls: list = []

        def track_run(*args, **kwargs):
            result = calls.pop(0)
            run_calls.append(args[0])
            if getattr(result, "returncode", 0) != 0 and kwargs.get("check", False):
                raise subprocess.CalledProcessError(result.returncode, args[0])
            return result

        with patch("subprocess.run", side_effect=track_run):
            ok, err = merge_pr("agent/my-branch")

        assert ok is True
        # Stash pop should have been called
        pop_call = run_calls[2] if len(run_calls) >= 3 else []
        assert "stash" in " ".join(str(p) for p in pop_call)
        assert "pop" in " ".join(str(p) for p in pop_call)

    def test_returns_false_on_merge_error(self) -> None:
        stash_ok = MagicMock(returncode=0, stdout="No local changes to save")
        merge_err = subprocess.CalledProcessError(1, "gh pr merge")
        merge_err.stderr = "Pull request is not mergeable"

        def run_side(*args, **kwargs):
            if args and "stash" in str(args[0]):
                return stash_ok
            raise merge_err

        with patch("subprocess.run", side_effect=run_side):
            ok, err = merge_pr("agent/my-branch")

        assert ok is False
        assert err is not None
        assert "mergeable" in err

    def test_pops_stash_even_on_merge_failure(self) -> None:
        stash_ok = MagicMock(returncode=0, stdout="Saved working directory and index state")
        merge_err = subprocess.CalledProcessError(1, "gh pr merge")
        merge_err.stderr = "conflicts"
        pop_ok = MagicMock(returncode=0)

        calls_made: list[list[str]] = []

        def run_side(*args, **kwargs):
            calls_made.append(list(args[0]) if args else [])
            if args and "stash" in " ".join(str(a) for a in args[0]) and "pop" in " ".join(str(a) for a in args[0]):
                return pop_ok
            if args and "stash" in " ".join(str(a) for a in args[0]):
                return stash_ok
            raise merge_err

        with patch("subprocess.run", side_effect=run_side):
            merge_pr("agent/my-branch")

        stash_pop_called = any("pop" in " ".join(str(a) for a in c) for c in calls_made)
        assert stash_pop_called


class TestCleanupAfterMerge:
    """Tests for cleanup_after_merge()."""

    def test_returns_true_on_success(self) -> None:
        ok_result = MagicMock(returncode=0, stdout="", stderr="")
        with patch("subprocess.run", return_value=ok_result):
            result = cleanup_after_merge("agent/my-branch")
        assert result is True

    def test_returns_false_on_checkout_failure(self) -> None:
        err = subprocess.CalledProcessError(128, "git checkout main")
        err.stderr = "not a git repo"
        with patch("subprocess.run", side_effect=err):
            result = cleanup_after_merge("agent/my-branch")
        assert result is False

    def test_retries_git_pull_on_transient_failure(self) -> None:
        """Test that git pull is retried up to 2 times before failing."""
        checkout_ok = MagicMock(returncode=0, stdout="", stderr="")
        stash_ok = MagicMock(returncode=0, stdout="No local changes to save\n", stderr="")
        pull_fail = MagicMock(returncode=128, stdout="", stderr="unable to access repository")
        pull_ok = MagicMock(returncode=0, stdout="", stderr="")
        delete_ok = MagicMock(returncode=0, stdout="", stderr="")
        push_delete_ok = MagicMock(returncode=0, stdout="", stderr="")

        results = [checkout_ok, stash_ok, pull_fail, pull_ok, delete_ok, push_delete_ok]

        def run_side(*args, **kwargs):
            return results.pop(0)

        with (
            patch("subprocess.run", side_effect=run_side),
            patch("time.sleep"),
            patch("pathlib.Path.exists", return_value=False),
        ):
            result = cleanup_after_merge("agent/my-branch")

        assert result is True

    def test_cleanup_calls_clear_checkpoint_on_success(self) -> None:
        """Verify clear_checkpoint() is called when cleanup succeeds."""
        ok_result = MagicMock(returncode=0, stdout="", stderr="")
        with (
            patch("subprocess.run", return_value=ok_result),
            patch("scripts.executor.postflight.clear_checkpoint") as mock_clear,
        ):
            result = cleanup_after_merge("agent/my-branch")
        assert result is True
        mock_clear.assert_called_once()

    def test_cleanup_does_not_call_clear_checkpoint_on_failure(self) -> None:
        """Verify clear_checkpoint() is NOT called when cleanup fails."""
        err = subprocess.CalledProcessError(128, "git checkout main")
        err.stderr = "not a git repo"
        with (
            patch("subprocess.run", side_effect=err),
            patch("scripts.executor.postflight.clear_checkpoint") as mock_clear,
        ):
            result = cleanup_after_merge("agent/my-branch")
        assert result is False
        mock_clear.assert_not_called()

    def test_stash_called_before_pull(self) -> None:
        """Verify git stash is called with correct arguments before git pull."""
        checkout_ok = MagicMock(returncode=0, stdout="", stderr="")
        stash_ok = MagicMock(returncode=0, stdout="Saved working directory and index state\n", stderr="")
        pull_ok = MagicMock(returncode=0, stdout="", stderr="")
        pop_ok = MagicMock(returncode=0, stdout="", stderr="")
        delete_ok = MagicMock(returncode=0, stdout="", stderr="")
        push_delete_ok = MagicMock(returncode=0, stdout="", stderr="")

        results = [checkout_ok, stash_ok, pull_ok, pop_ok, delete_ok, push_delete_ok]
        run_calls: list = []

        def run_side(*args, **kwargs):
            run_calls.append(args[0])
            return results.pop(0)

        with (
            patch("subprocess.run", side_effect=run_side),
            patch("time.sleep"),
            patch("pathlib.Path.exists", return_value=False),
        ):
            result = cleanup_after_merge("agent/my-branch")

        assert result is True
        stash_call = next((call for call in run_calls if call[0:2] == ["git", "stash"]), None)
        assert stash_call is not None
        assert "--include-untracked" in stash_call
        assert "logs/" in stash_call

    def test_stash_pop_called_after_pull_success(self) -> None:
        """Verify git stash pop is called after successful pull."""
        checkout_ok = MagicMock(returncode=0, stdout="", stderr="")
        stash_ok = MagicMock(returncode=0, stdout="Saved working directory\n", stderr="")
        pull_ok = MagicMock(returncode=0, stdout="", stderr="")
        pop_ok = MagicMock(returncode=0, stdout="", stderr="")
        delete_ok = MagicMock(returncode=0, stdout="", stderr="")
        push_delete_ok = MagicMock(returncode=0, stdout="", stderr="")

        results = [checkout_ok, stash_ok, pull_ok, pop_ok, delete_ok, push_delete_ok]
        run_calls: list = []

        def run_side(*args, **kwargs):
            run_calls.append(args[0])
            return results.pop(0)

        with (
            patch("subprocess.run", side_effect=run_side),
            patch("time.sleep"),
            patch("pathlib.Path.exists", return_value=False),
        ):
            result = cleanup_after_merge("agent/my-branch")

        assert result is True
        pop_call = next((call for call in run_calls if call == ["git", "stash", "pop"]), None)
        assert pop_call is not None

    def test_cleanup_succeeds_even_if_no_stash_saved(self) -> None:
        """Verify cleanup succeeds when stash has no changes to save."""
        checkout_ok = MagicMock(returncode=0, stdout="", stderr="")
        stash_no_changes = MagicMock(returncode=0, stdout="No local changes to save\n", stderr="")
        pull_ok = MagicMock(returncode=0, stdout="", stderr="")
        delete_ok = MagicMock(returncode=0, stdout="", stderr="")
        push_delete_ok = MagicMock(returncode=0, stdout="", stderr="")

        results = [checkout_ok, stash_no_changes, pull_ok, delete_ok, push_delete_ok]
        run_calls: list = []

        def run_side(*args, **kwargs):
            run_calls.append(args[0])
            return results.pop(0)

        with (
            patch("subprocess.run", side_effect=run_side),
            patch("time.sleep"),
            patch("pathlib.Path.exists", return_value=False),
        ):
            result = cleanup_after_merge("agent/my-branch")

        assert result is True
        pop_call = next((call for call in run_calls if call == ["git", "stash", "pop"]), None)
        assert pop_call is None

    def test_cleanup_succeeds_even_if_stash_pop_fails(self) -> None:
        """Verify cleanup succeeds even if git stash pop fails (non-critical)."""
        checkout_ok = MagicMock(returncode=0, stdout="", stderr="")
        stash_ok = MagicMock(returncode=0, stdout="Saved working directory\n", stderr="")
        pull_ok = MagicMock(returncode=0, stdout="", stderr="")
        pop_fail = MagicMock(returncode=1, stdout="", stderr="conflict: logs/file")
        delete_ok = MagicMock(returncode=0, stdout="", stderr="")
        push_delete_ok = MagicMock(returncode=0, stdout="", stderr="")

        results = [checkout_ok, stash_ok, pull_ok, pop_fail, delete_ok, push_delete_ok]
        run_calls: list = []

        def run_side(*args, **kwargs):
            run_calls.append(args[0])
            return results.pop(0)

        with (
            patch("subprocess.run", side_effect=run_side),
            patch("time.sleep"),
            patch("pathlib.Path.exists", return_value=False),
        ):
            result = cleanup_after_merge("agent/my-branch")

        assert result is True


class TestFinalizeSkipCiMergeGuard:
    """Tests for the SKIP_CI_WAIT merge-recovery guard inside finalize()."""

    @staticmethod
    def _subprocess_side_effect(args, **kwargs):
        """Return a generic success mock; special-case branch detection."""
        m = MagicMock()
        m.returncode = 0
        m.stderr = ""
        if args[:3] == ["git", "branch", "--show-current"]:
            m.stdout = "agent/rec-test\n"
        elif args[:3] == ["gh", "pr", "view"]:
            m.stdout = "https://github.com/owner/repo/pull/1\n"
        else:
            m.stdout = ""
        return m

    def test_skips_agent_recovery_when_skip_ci_and_ci_blocked_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When SKIP_CI_WAIT=true and merge fails with a CI-check phrase, no agent call."""
        monkeypatch.setenv("SKIP_CI_WAIT", "true")

        with (
            patch("subprocess.run", side_effect=self._subprocess_side_effect),
            patch("scripts.executor.postflight.merge_pr") as mock_merge,
            patch("scripts.executor.postflight._agent_merge_recovery") as mock_recovery,
            patch("scripts.executor.postflight.update_recommendation_status"),
            patch("scripts.executor.postflight._create_postmortem_recommendation"),
            patch("scripts.executor.postflight.clear_checkpoint"),
            patch("scripts.executor.postflight._run_verifiers_gate", return_value=True),
            patch("scripts.executor.postflight._code_review_gate", return_value=(True, 0.0, [])),
            patch("scripts.executor.postflight.ExecutionPlan"),
            patch("scripts.executor.jsonl_store.load_recommendation", return_value={}),
        ):
            mock_merge.return_value = (
                False,
                "Required status checks have not passed for this commit",
            )
            mock_recovery.return_value = (False, "unreachable")

            result = finalize("rec-test")

        assert result is None
        mock_recovery.assert_not_called()

    def test_still_calls_agent_recovery_for_non_ci_merge_errors(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When SKIP_CI_WAIT=true but merge fails with a conflict error, agent IS called."""
        monkeypatch.setenv("SKIP_CI_WAIT", "true")

        with (
            patch("subprocess.run", side_effect=self._subprocess_side_effect),
            patch("scripts.executor.postflight.merge_pr") as mock_merge,
            patch("scripts.executor.postflight._agent_merge_recovery") as mock_recovery,
            patch("scripts.executor.postflight.update_recommendation_status"),
            patch("scripts.executor.postflight._create_postmortem_recommendation"),
            patch("scripts.executor.postflight.clear_checkpoint"),
            patch("scripts.executor.postflight._run_verifiers_gate", return_value=True),
            patch("scripts.executor.postflight._code_review_gate", return_value=(True, 0.0, [])),
            patch("scripts.executor.postflight.ExecutionPlan"),
            patch("scripts.executor.jsonl_store.load_recommendation", return_value={}),
        ):
            mock_merge.return_value = (False, "merge conflict in scripts/foo.py")
            mock_recovery.return_value = (False, "could not resolve")

            result = finalize("rec-test")

        assert result is None
        mock_recovery.assert_called()


class TestProcessEventEmission:
    """Verify emit_process_event is called at the correct postflight decision points."""

    def test_scope_drift_detected_emitted_when_unplanned_files_found(self) -> None:
        """emit_process_event(category='scope_drift_detected') is called when unplanned files exist."""
        plan_steps = [{"file": "scripts/executor/plan.py"}]
        changed = ["scripts/executor/plan.py", "scripts/some_unplanned.py"]
        mock_result = MagicMock(returncode=0, stdout="\n".join(changed) + "\n")

        with (
            patch("subprocess.run", return_value=mock_result),
            patch("scripts.executor.postflight.emit_process_event") as mock_emit,
        ):
            unplanned = _scope_drift_check(plan_steps)

        assert "scripts/some_unplanned.py" in unplanned
        mock_emit.assert_called_once()
        assert mock_emit.call_args.kwargs.get("category") == "scope_drift_detected"

    def test_scope_drift_not_emitted_when_no_unplanned_files(self) -> None:
        """emit_process_event is NOT called when all changed files are in the plan."""
        plan_steps = [{"file": "scripts/executor/plan.py"}]
        changed = ["scripts/executor/plan.py"]
        mock_result = MagicMock(returncode=0, stdout="\n".join(changed) + "\n")

        with (
            patch("subprocess.run", return_value=mock_result),
            patch("scripts.executor.postflight.emit_process_event") as mock_emit,
        ):
            unplanned = _scope_drift_check(plan_steps)

        assert unplanned == []
        mock_emit.assert_not_called()

    def test_code_review_pass_emitted_when_no_blocking_findings(self) -> None:
        """emit_process_event(category='code_review_pass') is called when review has no findings."""
        mock_copilot_result = MagicMock(
            exit_code=0,
            content="No issues found.\nGATE: PASSED",
            cost_usd=0.5,
        )

        with (
            patch(
                "scripts.executor.postflight.load_prompt",
                return_value=("Review: {rec_id} {title} {acceptance} {plan_steps} {changed_files} {files_block}", "hash"),
            ),
            patch("scripts.executor.postflight.build_context_path", return_value=None),
            patch("scripts.executor.postflight.llm_call", return_value=mock_copilot_result),
            patch("scripts.executor.postflight.emit_process_event") as mock_emit,
        ):
            rec = {"id": "rec-tel-001", "title": "Test", "acceptance": "grep ..."}
            from scripts.executor.plan import ExecutionPlan

            plan = ExecutionPlan(
                rec_id="rec-tel-001",
                slug="test",
                revision=1,
                timestamp="2026-01-01T00:00:00Z",
                status="approved",
                model="test",
                tokens_used=0,
                steps=[],
                plan_text="",
            )
            passed, cost, blocking = _code_review_gate(rec, plan, [])

        assert passed is True
        assert blocking == []
        mock_emit.assert_called_once()
        assert mock_emit.call_args.kwargs.get("category") == "code_review_pass"
