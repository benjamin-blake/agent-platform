"""Unit tests for scripts/execute_recommendation.py"""

import json
from unittest.mock import MagicMock, patch

import pytest

from scripts.execute_recommendation import (
    main,
)
from scripts.executor.step_runner import StepOutcome

# ============================================================================
# New feature tests: CI wait, merge, cleanup, finalize auto-merge,
# checkpointing, batch orchestration, topological sort
# ============================================================================


# ============================================================================
# New feature tests: prompt hashing, diff capture, failure cleanup
# ============================================================================


class TestFastMode:
    """Tests for --fast mode plan delivery and phase skipping."""

    def _base_rec(self):
        return {
            "id": "rec-413",
            "title": "Fast test",
            "risk": "low",
            "automatable": True,
            "file": "scripts/example.py",
            "effort": "XS",
            "acceptance": "echo ok",
        }

    def _fast_plan_json(self):
        return json.dumps(
            [
                {
                    "n": 1,
                    "title": "Apply fix",
                    "file": "scripts/example.py",
                    "action": "modify",
                    "description": "Fix the thing",
                    "acceptance": "grep -q 'x' scripts/example.py",
                }
            ]
        )

    def _patch_run_acceptance(self):
        return patch("scripts.execute_recommendation.run_acceptance", return_value=True)

    def _inner(self):
        from scripts.execute_recommendation import (
            _execute_recommendation_inner,
        )

        return _execute_recommendation_inner

    def test_fast_cli_parses_fast_and_plan_json(self):
        """--fast and --plan-json are recognised by argparse."""
        plan = self._fast_plan_json()
        with (
            patch(
                "scripts.execute_recommendation.check_recursion_guard",
            ),
            patch(
                "scripts.execute_recommendation.check_process_killswitch",
            ),
            patch(
                "scripts.execute_recommendation._assign_job_object",
            ),
            patch(
                "scripts.execute_recommendation.execute_recommendation",
                return_value=True,
            ) as mock_exec,
            patch(
                "scripts.execute_recommendation.sys.argv",
                [
                    "execute_recommendation",
                    "rec-413",
                    "--fast",
                    "--plan-json",
                    plan,
                ],
            ),
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()

        assert exc_info.value.code == 0
        mock_exec.assert_called_once()
        _, kwargs = mock_exec.call_args
        assert kwargs["fast_mode"] is True
        assert kwargs["plan_json"] == plan

    def test_fast_mode_rejects_empty_plan_json(self):
        """Fast mode returns False when plan JSON is empty."""
        inner = self._inner()
        with (
            patch(
                "scripts.execute_recommendation.load_recommendation",
                return_value=self._base_rec(),
            ),
            patch(
                "scripts.execute_recommendation.load_checkpoint",
                return_value=None,
            ),
            patch(
                "scripts.execute_recommendation.ensure_feature_branch",
                return_value=True,
            ),
            patch(
                "scripts.execute_recommendation.prune_merged_agent_branches",
            ),
            patch(
                "scripts.execute_recommendation.clean_slate",
            ),
            patch("subprocess.run") as mock_run,
            patch(
                "scripts.execute_recommendation.write_run_summary",
            ),
        ):
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="0\n",
                stderr="",
            )
            result = inner(
                "rec-413",
                step_limit=None,
                skip_critique=False,
                fast_mode=True,
                plan_json="",
            )

        assert result is False

    def test_fast_mode_rejects_invalid_json(self):
        """Fast mode returns False for malformed JSON."""
        inner = self._inner()
        with (
            patch(
                "scripts.execute_recommendation.load_recommendation",
                return_value=self._base_rec(),
            ),
            patch(
                "scripts.execute_recommendation.load_checkpoint",
                return_value=None,
            ),
            patch(
                "scripts.execute_recommendation.ensure_feature_branch",
                return_value=True,
            ),
            patch(
                "scripts.execute_recommendation.prune_merged_agent_branches",
            ),
            patch(
                "scripts.execute_recommendation.clean_slate",
            ),
            patch("subprocess.run") as mock_run,
            patch(
                "scripts.execute_recommendation.write_run_summary",
            ),
        ):
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="0\n",
                stderr="",
            )
            result = inner(
                "rec-413",
                step_limit=None,
                skip_critique=False,
                fast_mode=True,
                plan_json="{not valid json",
            )

        assert result is False

    def test_fast_mode_rejects_empty_steps(self):
        """Fast mode returns False when JSON has no steps."""
        inner = self._inner()
        with (
            patch(
                "scripts.execute_recommendation.load_recommendation",
                return_value=self._base_rec(),
            ),
            patch(
                "scripts.execute_recommendation.load_checkpoint",
                return_value=None,
            ),
            patch(
                "scripts.execute_recommendation.ensure_feature_branch",
                return_value=True,
            ),
            patch(
                "scripts.execute_recommendation.prune_merged_agent_branches",
            ),
            patch(
                "scripts.execute_recommendation.clean_slate",
            ),
            patch("subprocess.run") as mock_run,
            patch(
                "scripts.execute_recommendation.write_run_summary",
            ),
        ):
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="0\n",
                stderr="",
            )
            result = inner(
                "rec-413",
                step_limit=None,
                skip_critique=False,
                fast_mode=True,
                plan_json=json.dumps({"steps": []}),
            )

        assert result is False

    def test_fast_mode_skips_planning_critique_review(self):
        """Fast mode skips generate_initial_plan, critique, review."""
        from contextlib import ExitStack

        inner = self._inner()
        plan_json = self._fast_plan_json()
        mock_step_result = (
            StepOutcome.SUCCESS,
            1.0,
            "hash",
            "sess",
        )
        with ExitStack() as stack:
            stack.enter_context(self._patch_run_acceptance())
            stack.enter_context(patch("scripts.execute_recommendation.load_recommendation", return_value=self._base_rec()))
            stack.enter_context(patch("scripts.execute_recommendation.load_checkpoint", return_value=None))
            stack.enter_context(patch("scripts.execute_recommendation.ensure_feature_branch", return_value=True))
            stack.enter_context(patch("scripts.execute_recommendation.prune_merged_agent_branches"))
            stack.enter_context(patch("scripts.execute_recommendation.clean_slate"))
            mock_gen_plan = stack.enter_context(patch("scripts.execute_recommendation.generate_initial_plan"))
            mock_critique = stack.enter_context(patch("scripts.execute_recommendation.critique_plan"))
            mock_review = stack.enter_context(patch("scripts.execute_recommendation._code_review_gate"))
            mock_impl = stack.enter_context(
                patch("scripts.execute_recommendation.implement_step", return_value=mock_step_result)
            )
            stack.enter_context(patch("scripts.execute_recommendation.commit_step", return_value=(True, "1 file changed")))
            stack.enter_context(patch("scripts.execute_recommendation._append_step_telemetry"))
            stack.enter_context(patch("scripts.execute_recommendation.save_checkpoint"))
            stack.enter_context(patch("scripts.execute_recommendation.save_plan"))
            stack.enter_context(patch("scripts.execute_recommendation.finalize", return_value=True))
            stack.enter_context(patch("scripts.execute_recommendation.update_recommendation_status"))
            stack.enter_context(patch("scripts.execute_recommendation._scope_drift_check", return_value=[]))
            stack.enter_context(patch("scripts.execute_recommendation._capture_executor_telemetry"))
            stack.enter_context(patch("scripts.execute_recommendation.write_run_summary"))
            stack.enter_context(patch("scripts.execute_recommendation.clear_checkpoint"))
            mock_run = stack.enter_context(patch("subprocess.run"))

            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="0\n",
                stderr="",
            )
            result = inner(
                "rec-413",
                step_limit=None,
                skip_critique=False,
                fast_mode=True,
                plan_json=plan_json,
            )

        assert result is True
        mock_gen_plan.assert_not_called()
        mock_critique.assert_not_called()
        mock_review.assert_not_called()
        mock_impl.assert_called_once()

    def test_fast_mode_still_runs_implement_and_finalize(self):
        """Fast mode runs implementation and finalize."""
        inner = self._inner()
        plan_json = self._fast_plan_json()
        mock_step_result = (
            StepOutcome.SUCCESS,
            1.0,
            "hash",
            "sess",
        )
        with (
            self._patch_run_acceptance(),
            patch(
                "scripts.execute_recommendation.load_recommendation",
                return_value=self._base_rec(),
            ),
            patch(
                "scripts.execute_recommendation.load_checkpoint",
                return_value=None,
            ),
            patch(
                "scripts.execute_recommendation.ensure_feature_branch",
                return_value=True,
            ),
            patch(
                "scripts.execute_recommendation.prune_merged_agent_branches",
            ),
            patch(
                "scripts.execute_recommendation.clean_slate",
            ),
            patch(
                "scripts.execute_recommendation.implement_step",
                return_value=mock_step_result,
            ) as mock_impl,
            patch(
                "scripts.execute_recommendation.commit_step",
                return_value=(True, "1 file changed"),
            ),
            patch(
                "scripts.execute_recommendation._append_step_telemetry",
            ),
            patch(
                "scripts.execute_recommendation.save_checkpoint",
            ),
            patch(
                "scripts.execute_recommendation.save_plan",
            ),
            patch(
                "scripts.execute_recommendation.finalize",
                return_value=True,
            ) as mock_finalize,
            patch(
                "scripts.execute_recommendation.update_recommendation_status",
            ),
            patch(
                "scripts.execute_recommendation._scope_drift_check",
                return_value=[],
            ),
            patch(
                "scripts.execute_recommendation._capture_executor_telemetry",
            ),
            patch(
                "scripts.execute_recommendation.write_run_summary",
            ),
            patch(
                "scripts.execute_recommendation.clear_checkpoint",
            ),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="0\n",
                stderr="",
            )
            result = inner(
                "rec-413",
                step_limit=None,
                skip_critique=False,
                fast_mode=True,
                plan_json=plan_json,
            )

        assert result is True
        mock_impl.assert_called_once()
        mock_finalize.assert_called_once()

    def test_fast_mode_reads_stdin_when_no_plan_json(self):
        """Fast mode reads stdin when --plan-json is None."""
        inner = self._inner()
        plan_json = self._fast_plan_json()
        mock_step_result = (
            StepOutcome.SUCCESS,
            1.0,
            "hash",
            "sess",
        )
        with (
            self._patch_run_acceptance(),
            patch(
                "scripts.execute_recommendation.load_recommendation",
                return_value=self._base_rec(),
            ),
            patch(
                "scripts.execute_recommendation.load_checkpoint",
                return_value=None,
            ),
            patch(
                "scripts.execute_recommendation.ensure_feature_branch",
                return_value=True,
            ),
            patch(
                "scripts.execute_recommendation.prune_merged_agent_branches",
            ),
            patch(
                "scripts.execute_recommendation.clean_slate",
            ),
            patch(
                "scripts.execute_recommendation.implement_step",
                return_value=mock_step_result,
            ),
            patch(
                "scripts.execute_recommendation.commit_step",
                return_value=(True, "1 file changed"),
            ),
            patch(
                "scripts.execute_recommendation._append_step_telemetry",
            ),
            patch(
                "scripts.execute_recommendation.save_checkpoint",
            ),
            patch(
                "scripts.execute_recommendation.save_plan",
            ),
            patch(
                "scripts.execute_recommendation.finalize",
                return_value=True,
            ),
            patch(
                "scripts.execute_recommendation.update_recommendation_status",
            ),
            patch(
                "scripts.execute_recommendation._scope_drift_check",
                return_value=[],
            ),
            patch(
                "scripts.execute_recommendation._capture_executor_telemetry",
            ),
            patch(
                "scripts.execute_recommendation.write_run_summary",
            ),
            patch(
                "scripts.execute_recommendation.clear_checkpoint",
            ),
            patch(
                "scripts.execute_recommendation.sys.stdin",
            ) as mock_stdin,
            patch("subprocess.run") as mock_run,
        ):
            mock_stdin.read.return_value = plan_json
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="0\n",
                stderr="",
            )
            result = inner(
                "rec-413",
                step_limit=None,
                skip_critique=False,
                fast_mode=True,
                plan_json=None,
            )

        assert result is True
        mock_stdin.read.assert_called_once()

    def test_fast_mode_accepts_dict_with_steps_key(self):
        """Fast mode accepts {\"steps\": [...]} format."""
        inner = self._inner()
        plan_json = json.dumps(
            {
                "steps": [
                    {
                        "n": 1,
                        "title": "Fix",
                        "file": "f.py",
                        "action": "modify",
                        "description": "d",
                        "acceptance": "grep -q x f.py",
                    }
                ]
            }
        )
        mock_step_result = (
            StepOutcome.SUCCESS,
            1.0,
            "hash",
            "sess",
        )
        with (
            self._patch_run_acceptance(),
            patch(
                "scripts.execute_recommendation.load_recommendation",
                return_value=self._base_rec(),
            ),
            patch(
                "scripts.execute_recommendation.load_checkpoint",
                return_value=None,
            ),
            patch(
                "scripts.execute_recommendation.ensure_feature_branch",
                return_value=True,
            ),
            patch(
                "scripts.execute_recommendation.prune_merged_agent_branches",
            ),
            patch(
                "scripts.execute_recommendation.clean_slate",
            ),
            patch(
                "scripts.execute_recommendation.implement_step",
                return_value=mock_step_result,
            ) as mock_impl,
            patch(
                "scripts.execute_recommendation.commit_step",
                return_value=(True, "1 file changed"),
            ),
            patch(
                "scripts.execute_recommendation._append_step_telemetry",
            ),
            patch(
                "scripts.execute_recommendation.save_checkpoint",
            ),
            patch(
                "scripts.execute_recommendation.save_plan",
            ),
            patch(
                "scripts.execute_recommendation.finalize",
                return_value=True,
            ),
            patch(
                "scripts.execute_recommendation.update_recommendation_status",
            ),
            patch(
                "scripts.execute_recommendation._scope_drift_check",
                return_value=[],
            ),
            patch(
                "scripts.execute_recommendation._capture_executor_telemetry",
            ),
            patch(
                "scripts.execute_recommendation.write_run_summary",
            ),
            patch(
                "scripts.execute_recommendation.clear_checkpoint",
            ),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="0\n",
                stderr="",
            )
            result = inner(
                "rec-413",
                step_limit=None,
                skip_critique=False,
                fast_mode=True,
                plan_json=plan_json,
            )

        assert result is True
        mock_impl.assert_called_once()

    def test_default_args_unchanged_non_fast(self):
        """Existing callers work with default fast_mode=False."""
        inner = self._inner()
        with (
            self._patch_run_acceptance(),
            patch(
                "scripts.execute_recommendation.load_recommendation",
                return_value=None,
            ),
            patch(
                "scripts.execute_recommendation.write_run_summary",
            ),
        ):
            result = inner(
                "rec-000",
                step_limit=None,
                skip_critique=True,
            )

        assert result is False
