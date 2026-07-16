"""Post-validation acceptance path and post-acceptance verification gate tests (rec-2709 Wave 2)."""

from unittest.mock import MagicMock, patch

from scripts.execute_recommendation import (
    AcceptanceFeasibility,
    ExecutionPlan,
    execute_recommendation,
)
from scripts.executor.step_runner import StepOutcome


class TestPostValidationAcceptancePath:
    """Test _execute_recommendation_inner when post-validation acceptance succeeds."""

    def test_acceptance_success_calls_finalize_once_and_returns_true(self):
        """finalize() is called exactly once and execution returns True when post-validation acceptance passes."""
        from contextlib import ExitStack

        plan = ExecutionPlan(
            rec_id="rec-100",
            slug="rec-100",
            revision=1,
            timestamp="2026-03-31T10:00:00Z",
            status="approved",
            model="test",
            tokens_used=100,
            steps=[
                {
                    "n": 1,
                    "title": "step",
                    "file": "scripts/__init__.py",
                    "action": "modify",
                    "description": "",
                    "acceptance": "",
                }
            ],
            plan_text="",
        )

        mock_val_proc = MagicMock()
        mock_val_proc.communicate.return_value = ("", "")
        mock_val_proc.returncode = 0
        mock_val_proc.__enter__ = MagicMock(return_value=mock_val_proc)
        mock_val_proc.__exit__ = MagicMock(return_value=False)

        git_ok = MagicMock(returncode=0, stdout="scripts/execute_recommendation.py\n", stderr="")

        patches = [
            patch("scripts.execute_recommendation.load_recommendation"),
            patch("scripts.execute_recommendation.ensure_feature_branch", return_value=True),
            patch("scripts.execute_recommendation.prune_merged_agent_branches"),
            patch("scripts.execute_recommendation.load_checkpoint", return_value=None),
            patch("scripts.execute_recommendation._commits_ahead_of_main", return_value=0),
            patch("scripts.execute_recommendation.get_latest_plan", return_value=None),
            patch("scripts.execute_recommendation.generate_initial_plan", return_value=plan),
            patch("scripts.execute_recommendation.save_plan"),
            patch(
                "scripts.execute_recommendation.implement_step",
                return_value=(StepOutcome.SUCCESS, 0.25, "abc123", "session-1"),
            ),
            patch("scripts.execute_recommendation.commit_step", return_value=(True, "1 file changed")),
            patch("scripts.execute_recommendation._append_step_telemetry"),
            patch("scripts.execute_recommendation._scope_drift_check", return_value=[]),
            patch("scripts.execute_recommendation._code_review_gate", return_value=(True, 0.25, [])),
            patch("scripts.execute_recommendation.subprocess.Popen", return_value=mock_val_proc),
            patch("scripts.execute_recommendation.run_acceptance", return_value=True),
            patch(
                "scripts.execute_recommendation.finalize",
                return_value="https://github.com/example/pr/1",
            ),
            patch("scripts.execute_recommendation.update_recommendation_status"),
            patch("scripts.execute_recommendation._handle_failure"),
            patch("scripts.execute_recommendation._capture_executor_telemetry"),
            patch("scripts.execute_recommendation.write_run_summary"),
            patch("scripts.execute_recommendation.clear_checkpoint"),
            patch("scripts.execute_recommendation.lint_acceptance_command", return_value=(True, "")),
            patch(
                "scripts.execute_recommendation.validate_acceptance_feasibility",
                return_value=(AcceptanceFeasibility.FEASIBLE, ""),
            ),
            patch("scripts.execute_recommendation.subprocess.run", return_value=git_ok),
        ]

        with ExitStack() as stack:
            mocks = [stack.enter_context(p) for p in patches]
            mock_load = mocks[0]
            mock_finalize = mocks[15]
            mock_load.return_value = {
                "id": "rec-100",
                "title": "Test rec",
                "risk": "low",
                "automatable": True,
                "effort": "S",
                "file": "scripts/__init__.py",
                "acceptance": "grep -q 'pattern' scripts/execute_recommendation.py",
            }
            result = execute_recommendation("rec-100", skip_critique=True)

        assert result is True
        mock_finalize.assert_called_once()


class TestPostAcceptanceVerificationGate:
    """Test verification gate between acceptance pass and finalize()."""

    def _build_patches(self, mock_val_proc, git_ok, plan, verification_result):
        """Build the standard ExitStack patch list for the verification gate tests."""
        return [
            patch("scripts.execute_recommendation.load_recommendation"),
            patch("scripts.execute_recommendation.ensure_feature_branch", return_value=True),
            patch("scripts.execute_recommendation.prune_merged_agent_branches"),
            patch("scripts.execute_recommendation.load_checkpoint", return_value=None),
            patch("scripts.execute_recommendation._commits_ahead_of_main", return_value=0),
            patch("scripts.execute_recommendation.get_latest_plan", return_value=None),
            patch("scripts.execute_recommendation.generate_initial_plan", return_value=plan),
            patch("scripts.execute_recommendation.save_plan"),
            patch(
                "scripts.execute_recommendation.implement_step",
                return_value=(StepOutcome.SUCCESS, 0.25, "abc123", "session-1"),
            ),
            patch("scripts.execute_recommendation.commit_step", return_value=(True, "1 file changed")),
            patch("scripts.execute_recommendation._append_step_telemetry"),
            patch("scripts.execute_recommendation._scope_drift_check", return_value=[]),
            patch("scripts.execute_recommendation._code_review_gate", return_value=(True, 0.25, [])),
            patch("scripts.execute_recommendation.subprocess.Popen", return_value=mock_val_proc),
            patch("scripts.execute_recommendation.run_acceptance", return_value=True),
            patch(
                "scripts.execute_recommendation.finalize",
                return_value="https://github.com/example/pr/1",
            ),
            patch("scripts.execute_recommendation.update_recommendation_status"),
            patch("scripts.execute_recommendation._handle_failure"),
            patch("scripts.execute_recommendation._capture_executor_telemetry"),
            patch("scripts.execute_recommendation.write_run_summary"),
            patch("scripts.execute_recommendation.clear_checkpoint"),
            patch("scripts.execute_recommendation.lint_acceptance_command", return_value=(True, "")),
            patch(
                "scripts.execute_recommendation.validate_acceptance_feasibility",
                return_value=(AcceptanceFeasibility.FEASIBLE, ""),
            ),
            patch("scripts.execute_recommendation.subprocess.run", return_value=git_ok),
            patch("scripts.execute_recommendation.run_verification", return_value=verification_result),
        ]

    def _make_plan(self):
        return ExecutionPlan(
            rec_id="rec-200",
            slug="rec-200",
            revision=1,
            timestamp="2026-04-01T10:00:00Z",
            status="approved",
            model="test",
            tokens_used=100,
            steps=[
                {
                    "n": 1,
                    "title": "step",
                    "file": "scripts/__init__.py",
                    "action": "modify",
                    "description": "",
                    "acceptance": "",
                }
            ],
            plan_text="",
        )

    def _make_val_proc(self):
        mock_val_proc = MagicMock()
        mock_val_proc.communicate.return_value = ("", "")
        mock_val_proc.returncode = 0
        mock_val_proc.__enter__ = MagicMock(return_value=mock_val_proc)
        mock_val_proc.__exit__ = MagicMock(return_value=False)
        return mock_val_proc

    def _make_git_ok(self):
        return MagicMock(returncode=0, stdout="scripts/execute_recommendation.py\n", stderr="")

    def test_verification_pass_still_calls_finalize(self):
        """When verification passes, finalize() is called and execution succeeds."""
        from contextlib import ExitStack

        plan = self._make_plan()
        verification_result = {"passed": True, "output": "ok", "skipped": False, "rejected": False, "error": ""}
        patches = self._build_patches(self._make_val_proc(), self._make_git_ok(), plan, verification_result)

        with ExitStack() as stack:
            mocks = [stack.enter_context(p) for p in patches]
            mock_load = mocks[0]
            mock_finalize = mocks[15]
            mock_telemetry = mocks[18]
            mock_load.return_value = {
                "id": "rec-200",
                "title": "Test rec",
                "risk": "low",
                "automatable": True,
                "effort": "S",
                "file": "scripts/__init__.py",
                "acceptance": "grep -q 'pattern' scripts/execute_recommendation.py",
                "verification": "python -m scripts.some_check --verify",
            }
            result = execute_recommendation("rec-200", skip_critique=True)

        assert result is True
        mock_finalize.assert_called_once()
        # Telemetry should include verification_pass outcome
        telemetry_calls = [c for c in mock_telemetry.call_args_list if c.kwargs.get("outcome") == "verification_pass"]
        assert len(telemetry_calls) >= 1

    def test_verification_fail_still_calls_finalize(self):
        """When verification fails, finalize() is STILL called (advisory failure)."""
        from contextlib import ExitStack

        plan = self._make_plan()
        verification_result = {
            "passed": False,
            "output": "error output",
            "skipped": False,
            "rejected": False,
            "error": "exit 1",
        }
        patches = self._build_patches(self._make_val_proc(), self._make_git_ok(), plan, verification_result)

        with ExitStack() as stack:
            mocks = [stack.enter_context(p) for p in patches]
            mock_load = mocks[0]
            mock_finalize = mocks[15]
            mock_telemetry = mocks[18]
            mock_load.return_value = {
                "id": "rec-200",
                "title": "Test rec",
                "risk": "low",
                "automatable": True,
                "effort": "S",
                "file": "scripts/__init__.py",
                "acceptance": "grep -q 'pattern' scripts/execute_recommendation.py",
                "verification": "python -m scripts.some_check --verify",
            }
            result = execute_recommendation("rec-200", skip_critique=True)

        assert result is True
        mock_finalize.assert_called_once()
        # Telemetry should include verification_warning outcome
        telemetry_calls = [c for c in mock_telemetry.call_args_list if c.kwargs.get("outcome") == "verification_warning"]
        assert len(telemetry_calls) >= 1

    def test_no_verification_field_skips_gate(self):
        """When rec has no verification field, the gate is skipped entirely."""
        from contextlib import ExitStack

        plan = self._make_plan()
        verification_result = {"passed": True, "output": "", "skipped": True, "rejected": False, "error": ""}
        patches = self._build_patches(self._make_val_proc(), self._make_git_ok(), plan, verification_result)

        with ExitStack() as stack:
            mocks = [stack.enter_context(p) for p in patches]
            mock_load = mocks[0]
            mock_finalize = mocks[15]
            mock_run_verification = mocks[24]
            mock_load.return_value = {
                "id": "rec-200",
                "title": "Test rec",
                "risk": "low",
                "automatable": True,
                "effort": "S",
                "file": "scripts/__init__.py",
                "acceptance": "grep -q 'pattern' scripts/execute_recommendation.py",
            }
            result = execute_recommendation("rec-200", skip_critique=True)

        assert result is True
        mock_finalize.assert_called_once()
        mock_run_verification.assert_not_called()

    def test_verification_rejected_still_calls_finalize(self):
        """When verification is rejected (python -c), finalize() is still called."""
        from contextlib import ExitStack

        plan = self._make_plan()
        verification_result = {
            "passed": False,
            "output": "rejected",
            "skipped": False,
            "rejected": True,
            "error": "python -c banned",
        }
        patches = self._build_patches(self._make_val_proc(), self._make_git_ok(), plan, verification_result)

        with ExitStack() as stack:
            mocks = [stack.enter_context(p) for p in patches]
            mock_load = mocks[0]
            mock_finalize = mocks[15]
            mock_load.return_value = {
                "id": "rec-200",
                "title": "Test rec",
                "risk": "low",
                "automatable": True,
                "effort": "S",
                "file": "scripts/__init__.py",
                "acceptance": "grep -q 'pattern' scripts/execute_recommendation.py",
                "verification": 'python -c "import sys"',
            }
            result = execute_recommendation("rec-200", skip_critique=True)

        assert result is True
        mock_finalize.assert_called_once()
