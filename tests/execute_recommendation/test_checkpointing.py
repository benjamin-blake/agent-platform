"""Checkpoint save/load/resume-branch-merged tests (rec-2709 Wave 2)."""

import subprocess
from unittest.mock import MagicMock, call, patch

from scripts.execute_recommendation import (
    ExecutionPlan,
    _is_checkpoint_branch_merged,
    execute_recommendation,
)
from scripts.executor.step_runner import StepOutcome


class TestCheckpointing:
    """Tests for checkpoint save/resume/clear in _execute_recommendation_inner."""

    def _eligible_rec(self, rec_id: str = "rec-100") -> dict:
        return {"id": rec_id, "title": "Test rec", "risk": "low", "automatable": True, "effort": "S"}

    def _approved_plan(self, rec_id: str = "rec-100") -> ExecutionPlan:
        return ExecutionPlan(
            rec_id=rec_id,
            slug=rec_id,
            revision=1,
            timestamp="2026-03-31T10:00:00Z",
            status="approved",
            model="test",
            tokens_used=100,
            steps=[
                {"n": 1, "title": "Step 1", "file": "", "action": "modify", "description": "", "acceptance": ""},
                {"n": 2, "title": "Step 2", "file": "", "action": "modify", "description": "", "acceptance": ""},
            ],
            plan_text="",
        )

    def test_save_checkpoint_after_each_step(self, tmp_path):
        """save_checkpoint is called after each successful step."""
        mock_val = MagicMock(returncode=0, stdout="", stderr="")
        with (
            patch("scripts.execute_recommendation.load_recommendation") as mock_load,
            patch("scripts.execute_recommendation.ensure_feature_branch") as mock_branch,
            patch("scripts.execute_recommendation.load_checkpoint") as mock_load_ck,
            patch("scripts.execute_recommendation.save_checkpoint") as mock_save_ck,
            patch("scripts.execute_recommendation.clear_checkpoint"),
            patch("scripts.execute_recommendation._commits_ahead_of_main", return_value=0),
            patch("scripts.execute_recommendation.generate_initial_plan") as mock_gen,
            patch("scripts.execute_recommendation.get_latest_plan") as mock_latest,
            patch("scripts.execute_recommendation.critique_plan") as mock_critique,
            patch("scripts.execute_recommendation.save_plan"),
            patch("scripts.execute_recommendation.implement_step") as mock_impl,
            patch("scripts.execute_recommendation.commit_step") as mock_commit,
            patch("scripts.execute_recommendation._append_step_telemetry"),
            patch("scripts.execute_recommendation.finalize") as mock_finalize,
            patch("scripts.execute_recommendation.update_recommendation_status"),
            patch("scripts.execute_recommendation._scope_drift_check", return_value=[]),
            patch("scripts.execute_recommendation._code_review_gate", return_value=(True, 0.0, [])),
            patch("scripts.execute_recommendation.subprocess.Popen") as mock_popen,
            patch("scripts.execute_recommendation.subprocess.run", return_value=mock_val),
        ):
            mock_popen.return_value.__enter__ = MagicMock(return_value=mock_popen.return_value)
            mock_popen.return_value.__exit__ = MagicMock(return_value=False)
            mock_popen.return_value.communicate.return_value = ("", "")
            mock_popen.return_value.returncode = 0
            mock_load.return_value = self._eligible_rec()
            mock_branch.return_value = True
            mock_load_ck.return_value = None
            mock_latest.return_value = None
            mock_gen.return_value = self._approved_plan()
            mock_critique.return_value = {
                "verdict": "approved",
                "suggestions": [],
                "tokens_used": 10,
            }
            mock_impl.return_value = (StepOutcome.SUCCESS, 0.01, "abc123def456", "ses-step1")  # pragma: allowlist secret
            mock_commit.return_value = (True, "1 file changed, 2 insertions")
            mock_finalize.return_value = "https://github.com/pr/1"

            execute_recommendation("rec-100", skip_critique=True)

        # Call sequence:
        # 0: PLAN_COMPLETE (step=0, total=2) -- before implementation loop
        # 1: step 1 in-progress (step=1, total=2)
        # 2: step 2 in-progress (step=2, total=2)
        # 3: IMPL_COMPLETE (step=2, total=2)
        # 4: REVIEW_COMPLETE (step=steps_completed, total=2)
        # 5: CI_PENDING (step=steps_completed, total=2)
        assert mock_save_ck.call_count == 6
        calls = mock_save_ck.call_args_list
        assert calls[0] == call(
            branch="agent/rec-100", plan_file="rec-100", current_step=0, total_steps=2, status="PLAN_COMPLETE"
        )
        assert calls[1] == call(branch="agent/rec-100", plan_file="rec-100", current_step=1, total_steps=2)
        assert calls[2] == call(branch="agent/rec-100", plan_file="rec-100", current_step=2, total_steps=2)
        assert calls[3] == call(
            branch="agent/rec-100",
            plan_file="rec-100",
            current_step=2,
            total_steps=2,
            status="IMPL_COMPLETE",
        )
        assert calls[4].kwargs.get("status") == "REVIEW_COMPLETE"
        assert calls[5].kwargs.get("status") == "CI_PENDING"

    def test_resume_from_checkpoint(self):
        """With checkpoint at step 1, step 1 is skipped and step 2 is executed."""
        ck = {
            "plan_file": "rec-100",
            "current_step": 1,
            "total_steps": 2,
            "status": "IN_PROGRESS",
            "branch": "agent/rec-100",
            "last_updated": "2026-03-31T00:00:00+00:00",
        }
        mock_val = MagicMock(returncode=0, stdout="", stderr="")
        with (
            patch("scripts.execute_recommendation.load_recommendation") as mock_load,
            patch("scripts.execute_recommendation.ensure_feature_branch") as mock_branch,
            patch("scripts.execute_recommendation.load_checkpoint") as mock_load_ck,
            patch("scripts.execute_recommendation.save_checkpoint"),
            patch("scripts.execute_recommendation.clear_checkpoint"),
            patch("scripts.execute_recommendation._commits_ahead_of_main", return_value=0),
            patch("scripts.execute_recommendation.get_latest_plan") as mock_latest,
            patch("scripts.execute_recommendation.generate_initial_plan") as mock_gen,
            patch("scripts.execute_recommendation.save_plan"),
            patch("scripts.execute_recommendation.implement_step") as mock_impl,
            patch("scripts.execute_recommendation.commit_step") as mock_commit,
            patch("scripts.execute_recommendation._append_step_telemetry"),
            patch("scripts.execute_recommendation.finalize") as mock_finalize,
            patch("scripts.execute_recommendation.update_recommendation_status"),
            patch("scripts.execute_recommendation._scope_drift_check", return_value=[]),
            patch("scripts.execute_recommendation._code_review_gate", return_value=(True, 0.0, [])),
            patch("scripts.execute_recommendation.subprocess.Popen") as mock_popen,
            patch("scripts.execute_recommendation.subprocess.run", return_value=mock_val),
        ):
            mock_popen.return_value.__enter__ = MagicMock(return_value=mock_popen.return_value)
            mock_popen.return_value.__exit__ = MagicMock(return_value=False)
            mock_popen.return_value.communicate.return_value = ("", "")
            mock_popen.return_value.returncode = 0
            mock_load.return_value = self._eligible_rec()
            mock_branch.return_value = True
            mock_load_ck.return_value = ck
            mock_latest.return_value = self._approved_plan()
            mock_gen.return_value = self._approved_plan()
            mock_impl.return_value = (StepOutcome.SUCCESS, 0.01, "", "ses-step2")
            mock_commit.return_value = (True, "")
            mock_finalize.return_value = "https://github.com/pr/1"

            execute_recommendation("rec-100", skip_critique=True)

        # Only step 2 should have been implemented (step 1 was skipped)
        assert mock_impl.call_count == 1
        call_args = mock_impl.call_args[0]
        assert call_args[2] == 2  # step_n == 2

    def test_checkpoint_different_rec_returns_false(self):
        """Checkpoint for different rec_id causes early return False."""
        ck = {
            "plan_file": "rec-999",
            "current_step": 1,
            "total_steps": 3,
            "status": "IN_PROGRESS",
            "branch": "agent/rec-999",
            "last_updated": "2026-03-31T00:00:00+00:00",
        }
        with (
            patch("scripts.execute_recommendation.load_checkpoint") as mock_load_ck,
            patch("scripts.execute_recommendation.load_recommendation") as mock_load,
        ):
            mock_load_ck.return_value = ck
            mock_load.return_value = self._eligible_rec("rec-100")
            result = execute_recommendation("rec-100")
        assert result is False

    def test_restart_flag_clears_checkpoint(self):
        """--restart flag calls clear_checkpoint before execution."""
        with (
            patch("scripts.execute_recommendation.clear_checkpoint") as mock_clear,
            patch("scripts.execute_recommendation.load_checkpoint") as mock_load_ck,
            patch("scripts.execute_recommendation.load_recommendation") as mock_load,
            patch(
                "scripts.execute_recommendation._reset_rec_status",
            ),
            patch(
                "scripts.execute_recommendation.ensure_feature_branch",
                return_value=False,
            ),
        ):
            mock_load_ck.return_value = None
            mock_load.return_value = self._eligible_rec()
            execute_recommendation("rec-100", restart=True)
        mock_clear.assert_called_once()

    def test_successful_completion_clears_checkpoint(self):
        """clear_checkpoint is called after all steps complete and finalize succeeds."""
        mock_val = MagicMock(returncode=0, stdout="", stderr="")
        with (
            patch("scripts.execute_recommendation.load_recommendation") as mock_load,
            patch("scripts.execute_recommendation.ensure_feature_branch") as mock_branch,
            patch("scripts.execute_recommendation.load_checkpoint") as mock_load_ck,
            patch("scripts.execute_recommendation.save_checkpoint"),
            patch("scripts.execute_recommendation.clear_checkpoint") as mock_clear,
            patch("scripts.execute_recommendation._commits_ahead_of_main", return_value=0),
            patch("scripts.execute_recommendation.generate_initial_plan") as mock_gen,
            patch("scripts.execute_recommendation.get_latest_plan") as mock_latest,
            patch("scripts.execute_recommendation.save_plan"),
            patch("scripts.execute_recommendation.implement_step") as mock_impl,
            patch("scripts.execute_recommendation.commit_step") as mock_commit,
            patch("scripts.execute_recommendation._append_step_telemetry"),
            patch("scripts.execute_recommendation.finalize") as mock_finalize,
            patch("scripts.execute_recommendation.update_recommendation_status"),
            patch("scripts.execute_recommendation._scope_drift_check", return_value=[]),
            patch("scripts.execute_recommendation._code_review_gate", return_value=(True, 0.0, [])),
            patch("scripts.execute_recommendation.subprocess.Popen") as mock_popen,
            patch("scripts.execute_recommendation.subprocess.run", return_value=mock_val),
        ):
            mock_popen.return_value.__enter__ = MagicMock(return_value=mock_popen.return_value)
            mock_popen.return_value.__exit__ = MagicMock(return_value=False)
            mock_popen.return_value.communicate.return_value = ("", "")
            mock_popen.return_value.returncode = 0
            mock_load.return_value = self._eligible_rec()
            mock_branch.return_value = True
            mock_load_ck.return_value = None
            mock_latest.return_value = None
            mock_gen.return_value = self._approved_plan()
            mock_impl.return_value = (StepOutcome.SUCCESS, 0.01, "", "ses-ok")
            mock_commit.return_value = (True, "")
            mock_finalize.return_value = "https://github.com/pr/1"

            execute_recommendation("rec-100", skip_critique=True)

        mock_clear.assert_called()

    def test_failure_leaves_checkpoint(self):
        """On step failure, clear_checkpoint is NOT called."""
        mock_val = MagicMock(returncode=0, stdout="", stderr="")
        with (
            patch("scripts.execute_recommendation.load_recommendation") as mock_load,
            patch("scripts.execute_recommendation.ensure_feature_branch") as mock_branch,
            patch("scripts.execute_recommendation.load_checkpoint") as mock_load_ck,
            patch("scripts.execute_recommendation.save_checkpoint"),
            patch("scripts.execute_recommendation.clear_checkpoint") as mock_clear,
            patch("scripts.execute_recommendation._commits_ahead_of_main", return_value=0),
            patch("scripts.execute_recommendation.generate_initial_plan") as mock_gen,
            patch("scripts.execute_recommendation.get_latest_plan") as mock_latest,
            patch("scripts.execute_recommendation.save_plan"),
            patch("scripts.execute_recommendation.implement_step") as mock_impl,
            patch("scripts.execute_recommendation._handle_failure"),
            patch("scripts.execute_recommendation.update_recommendation_status"),
            patch("scripts.execute_recommendation.subprocess.Popen") as mock_popen,
            patch("scripts.execute_recommendation.subprocess.run", return_value=mock_val),
        ):
            mock_popen.return_value.__enter__ = MagicMock(return_value=mock_popen.return_value)
            mock_popen.return_value.__exit__ = MagicMock(return_value=False)
            mock_popen.return_value.communicate.return_value = ("", "")
            mock_popen.return_value.returncode = 0
            mock_load.return_value = self._eligible_rec()
            mock_branch.return_value = True
            mock_load_ck.return_value = None
            mock_latest.return_value = None
            mock_gen.return_value = self._approved_plan()
            mock_impl.return_value = (StepOutcome.GHOST_STEP, 0.0, "", "")  # Step fails

            execute_recommendation("rec-100", skip_critique=True)

        mock_clear.assert_not_called()

    def test_checkpoint_auto_clear_on_merged_branch(self):
        """Checkpoint for different rec with merged branch is auto-cleared."""
        from scripts.execute_recommendation import _execute_recommendation_inner

        ck = {
            "plan_file": "rec-999",
            "current_step": 1,
            "total_steps": 3,
            "status": "IN_PROGRESS",
            "branch": "agent/rec-999",
            "last_updated": "2026-03-31T00:00:00+00:00",
        }
        with (
            patch(
                "scripts.execute_recommendation.ensure_feature_branch",
                return_value=False,
            ),
            patch(
                "scripts.execute_recommendation.load_checkpoint",
            ) as mock_load_ck,
            patch(
                "scripts.execute_recommendation.load_recommendation",
            ) as mock_load,
            patch(
                "scripts.execute_recommendation.clear_checkpoint",
            ) as mock_clear,
            patch(
                "scripts.execute_recommendation._is_checkpoint_branch_merged",
            ) as mock_is_merged,
        ):
            mock_load_ck.return_value = ck
            mock_load.return_value = {
                "id": "rec-100",
                "title": "Test",
                "risk": "low",
                "automatable": True,
                "effort": "S",
            }
            mock_is_merged.return_value = True

            _execute_recommendation_inner(
                "rec-100",
                step_limit=None,
                skip_critique=True,
            )

        mock_clear.assert_called_once()

    def test_checkpoint_different_rec_not_merged_returns_false(self):
        """Checkpoint for different rec with unmerged branch causes early return False."""
        from scripts.execute_recommendation import _execute_recommendation_inner

        ck = {
            "plan_file": "rec-999",
            "current_step": 1,
            "total_steps": 3,
            "status": "IN_PROGRESS",
            "branch": "agent/rec-999",
            "last_updated": "2026-03-31T00:00:00+00:00",
        }
        with (
            patch("scripts.execute_recommendation.ensure_feature_branch", return_value=True),
            patch("scripts.execute_recommendation.load_checkpoint") as mock_load_ck,
            patch("scripts.execute_recommendation.load_recommendation") as mock_load,
            patch("scripts.execute_recommendation._is_checkpoint_branch_merged") as mock_is_merged,
        ):
            mock_load_ck.return_value = ck
            mock_load.return_value = {"id": "rec-100", "title": "Test", "risk": "low", "automatable": True, "effort": "S"}
            mock_is_merged.return_value = False  # Branch is NOT merged to main

            result = _execute_recommendation_inner("rec-100", step_limit=None, skip_critique=True)

        # Should return False due to stale checkpoint
        assert result is False

    def test_is_checkpoint_branch_merged_success(self):
        """_is_checkpoint_branch_merged returns True when branch is ancestor of main."""
        mock_result = MagicMock(returncode=0)
        with patch("subprocess.run", return_value=mock_result):
            result = _is_checkpoint_branch_merged("agent/rec-100")

        assert result is True

    def test_is_checkpoint_branch_merged_failure(self):
        """_is_checkpoint_branch_merged returns False when branch is NOT ancestor of main."""
        mock_result = MagicMock(returncode=1)
        with patch("subprocess.run", return_value=mock_result):
            result = _is_checkpoint_branch_merged("agent/rec-100")

        assert result is False

    def test_is_checkpoint_branch_merged_timeout(self):
        """_is_checkpoint_branch_merged returns False on timeout."""
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 10)):
            result = _is_checkpoint_branch_merged("agent/rec-100")

        assert result is False

    def test_is_checkpoint_branch_merged_exception(self):
        """_is_checkpoint_branch_merged returns False on general exception."""
        with patch("subprocess.run", side_effect=Exception("Git error")):
            result = _is_checkpoint_branch_merged("agent/rec-100")

        assert result is False

    def _single_step_plan(self, rec_id: str = "rec-100") -> ExecutionPlan:
        """Helper to create a plan with only 1 step."""
        return ExecutionPlan(
            rec_id=rec_id,
            slug=rec_id,
            revision=1,
            timestamp="2026-03-31T10:00:00Z",
            status="approved",
            model="test",
            tokens_used=100,
            steps=[
                {"n": 1, "title": "Step 1", "file": "", "action": "modify", "description": "", "acceptance": ""},
            ],
            plan_text="",
        )

    def test_resume_from_step_reset_when_new_plan_shorter(self):
        """When checkpoint has current_step=2 but new plan has 1 step, reset to 0 and execute step 1."""
        ck = {
            "plan_file": "rec-100",
            "current_step": 2,
            "total_steps": 2,
            "status": "IN_PROGRESS",
            "branch": "agent/rec-100",
            "last_updated": "2026-03-31T00:00:00+00:00",
        }
        mock_val = MagicMock(returncode=0, stdout="", stderr="")
        with (
            patch("scripts.execute_recommendation.load_recommendation") as mock_load,
            patch("scripts.execute_recommendation.ensure_feature_branch") as mock_branch,
            patch("scripts.execute_recommendation.load_checkpoint") as mock_load_ck,
            patch("scripts.execute_recommendation.save_checkpoint"),
            patch("scripts.execute_recommendation.clear_checkpoint"),
            patch("scripts.execute_recommendation._commits_ahead_of_main", return_value=0),
            patch("scripts.execute_recommendation.get_latest_plan") as mock_latest,
            patch("scripts.execute_recommendation.generate_initial_plan") as mock_gen,
            patch("scripts.execute_recommendation.save_plan"),
            patch("scripts.execute_recommendation.implement_step") as mock_impl,
            patch("scripts.execute_recommendation.commit_step") as mock_commit,
            patch("scripts.execute_recommendation._append_step_telemetry"),
            patch("scripts.execute_recommendation.finalize") as mock_finalize,
            patch("scripts.execute_recommendation.update_recommendation_status"),
            patch("scripts.execute_recommendation._scope_drift_check", return_value=[]),
            patch("scripts.execute_recommendation._code_review_gate", return_value=(True, 0.0, [])),
            patch("scripts.execute_recommendation.subprocess.Popen") as mock_popen,
            patch("scripts.execute_recommendation.subprocess.run", return_value=mock_val),
        ):
            mock_popen.return_value.__enter__ = MagicMock(return_value=mock_popen.return_value)
            mock_popen.return_value.__exit__ = MagicMock(return_value=False)
            mock_popen.return_value.communicate.return_value = ("", "")
            mock_popen.return_value.returncode = 0
            mock_load.return_value = self._eligible_rec()
            mock_branch.return_value = True
            mock_load_ck.return_value = ck  # Checkpoint has current_step=2
            mock_latest.return_value = None
            mock_gen.return_value = self._single_step_plan()  # New plan has only 1 step
            mock_impl.return_value = (StepOutcome.SUCCESS, 0.01, "", "ses-step1")
            mock_commit.return_value = (True, "")
            mock_finalize.return_value = "https://github.com/pr/1"

            execute_recommendation("rec-100", skip_critique=True)

        # Verify that the single step was implemented (not skipped due to resume_from_step reset)
        assert mock_impl.call_count == 1
        call_args = mock_impl.call_args[0]
        assert call_args[2] == 1  # step_n == 1
