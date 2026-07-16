"""Resume-from-postflight path tests (rec-2709 Wave 2)."""

from unittest.mock import MagicMock, call, patch

from scripts.execute_recommendation import (
    ExecutionPlan,
    execute_recommendation,
)
from scripts.executor.step_runner import StepOutcome


class TestResumePostflight:
    """Tests for IMPL_COMPLETE checkpoint and --resume-postflight flag."""

    def _eligible_rec(self, rec_id: str = "rec-100") -> dict:
        return {
            "id": rec_id,
            "title": "Test rec",
            "risk": "low",
            "automatable": True,
            "effort": "S",
            "file": "scripts/some_file.py",
        }

    def _approved_plan(self, rec_id: str = "rec-100") -> ExecutionPlan:
        return ExecutionPlan(
            rec_id=rec_id,
            slug=rec_id,
            revision=1,
            timestamp="2026-04-15T10:00:00Z",
            status="approved",
            model="test",
            tokens_used=100,
            steps=[
                {
                    "n": 1,
                    "title": "Step 1",
                    "file": "",
                    "action": "modify",
                    "description": "",
                    "acceptance": "",
                },
                {
                    "n": 2,
                    "title": "Step 2",
                    "file": "",
                    "action": "modify",
                    "description": "",
                    "acceptance": "",
                },
            ],
            plan_text="",
        )

    def test_impl_complete_checkpoint_saved_after_all_steps(self):
        """save_checkpoint is called with status=IMPL_COMPLETE after all steps."""
        mock_val = MagicMock(returncode=0, stdout="", stderr="")
        with (
            patch("scripts.execute_recommendation.load_recommendation") as mock_load,
            patch(
                "scripts.execute_recommendation.ensure_feature_branch",
                return_value=True,
            ),
            patch(
                "scripts.execute_recommendation.load_checkpoint",
                return_value=None,
            ),
            patch("scripts.execute_recommendation.save_checkpoint") as mock_save_ck,
            patch("scripts.execute_recommendation.clear_checkpoint"),
            patch(
                "scripts.execute_recommendation._commits_ahead_of_main",
                return_value=0,
            ),
            patch("scripts.execute_recommendation.generate_initial_plan") as mock_gen,
            patch(
                "scripts.execute_recommendation.get_latest_plan",
                return_value=None,
            ),
            patch("scripts.execute_recommendation.critique_plan") as mock_critique,
            patch("scripts.execute_recommendation.save_plan"),
            patch("scripts.execute_recommendation.implement_step") as mock_impl,
            patch("scripts.execute_recommendation.commit_step") as mock_commit,
            patch("scripts.execute_recommendation._append_step_telemetry"),
            patch(
                "scripts.execute_recommendation.finalize",
                return_value="https://github.com/pr/1",
            ),
            patch("scripts.execute_recommendation.update_recommendation_status"),
            patch(
                "scripts.execute_recommendation._scope_drift_check",
                return_value=[],
            ),
            patch(
                "scripts.execute_recommendation._code_review_gate",
                return_value=(True, 0.0, []),
            ),
            patch("scripts.execute_recommendation.subprocess.Popen") as mock_popen,
            patch(
                "scripts.execute_recommendation.subprocess.run",
                return_value=mock_val,
            ),
        ):
            mock_popen.return_value.__enter__ = MagicMock(return_value=mock_popen.return_value)
            mock_popen.return_value.__exit__ = MagicMock(return_value=False)
            mock_popen.return_value.communicate.return_value = ("", "")
            mock_popen.return_value.returncode = 0
            mock_load.return_value = self._eligible_rec()
            mock_gen.return_value = self._approved_plan()
            mock_critique.return_value = {
                "verdict": "approved",
                "suggestions": [],
                "tokens_used": 10,
            }
            mock_impl.return_value = (
                StepOutcome.SUCCESS,
                0.01,
                "abc123def456",  # pragma: allowlist secret
                "ses-step",
            )
            mock_commit.return_value = (True, "1 file changed")

            execute_recommendation("rec-100", skip_critique=True)

        # Last save_checkpoint call must be IMPL_COMPLETE
        impl_complete_calls = [
            c
            for c in mock_save_ck.call_args_list
            if c.kwargs.get("status") == "IMPL_COMPLETE" or (len(c.args) > 4 and c.args[4] == "IMPL_COMPLETE")
        ]
        assert len(impl_complete_calls) == 1
        impl_call = impl_complete_calls[0]
        assert impl_call == call(
            branch="agent/rec-100",
            plan_file="rec-100",
            current_step=2,
            total_steps=2,
            status="IMPL_COMPLETE",
        )

    def test_resume_postflight_skips_plan_and_impl(self):
        """resume_postflight=True skips plan generation and implementation."""
        checkpoint = {
            "plan_file": "rec-100",
            "current_step": 2,
            "total_steps": 2,
            "status": "IMPL_COMPLETE",
            "branch": "agent/rec-100",
            "last_updated": "2026-04-15T00:00:00+00:00",
        }
        mock_val = MagicMock(returncode=0, stdout="", stderr="")
        with (
            patch("scripts.execute_recommendation.load_recommendation") as mock_load,
            patch(
                "scripts.execute_recommendation.ensure_feature_branch",
                return_value=True,
            ),
            patch(
                "scripts.execute_recommendation.load_checkpoint",
                return_value=checkpoint,
            ),
            patch("scripts.execute_recommendation.save_checkpoint"),
            patch("scripts.execute_recommendation.clear_checkpoint"),
            patch(
                "scripts.execute_recommendation._commits_ahead_of_main",
                return_value=0,
            ),
            patch("scripts.execute_recommendation.generate_initial_plan") as mock_gen,
            patch("scripts.execute_recommendation.get_latest_plan") as mock_latest,
            patch("scripts.execute_recommendation.critique_plan") as mock_critique,
            patch("scripts.execute_recommendation.save_plan"),
            patch("scripts.execute_recommendation.implement_step") as mock_impl,
            patch("scripts.execute_recommendation.commit_step") as mock_commit,
            patch("scripts.execute_recommendation._append_step_telemetry"),
            patch(
                "scripts.execute_recommendation.finalize",
                return_value="https://github.com/pr/1",
            ) as mock_finalize,
            patch("scripts.execute_recommendation.update_recommendation_status"),
            patch(
                "scripts.execute_recommendation._scope_drift_check",
                return_value=[],
            ),
            patch(
                "scripts.execute_recommendation._code_review_gate",
                return_value=(True, 0.0, []),
            ),
            patch("scripts.execute_recommendation.subprocess.Popen") as mock_popen,
            patch(
                "scripts.execute_recommendation.subprocess.run",
                return_value=mock_val,
            ),
        ):
            mock_popen.return_value.__enter__ = MagicMock(return_value=mock_popen.return_value)
            mock_popen.return_value.__exit__ = MagicMock(return_value=False)
            mock_popen.return_value.communicate.return_value = ("", "")
            mock_popen.return_value.returncode = 0
            mock_load.return_value = self._eligible_rec()
            mock_latest.return_value = self._approved_plan()

            result = execute_recommendation("rec-100", resume_postflight=True)

        assert result is True
        # Plan generation and implementation should never be called
        mock_gen.assert_not_called()
        mock_critique.assert_not_called()
        mock_impl.assert_not_called()
        mock_commit.assert_not_called()
        # Postflight (finalize) should be called
        mock_finalize.assert_called_once()

    def test_resume_postflight_without_plan_fails(self):
        """resume_postflight=True requires an existing saved execution plan."""
        checkpoint = {
            "plan_file": "rec-100",
            "current_step": 2,
            "total_steps": 2,
            "status": "IMPL_COMPLETE",
            "branch": "agent/rec-100",
            "last_updated": "2026-04-15T00:00:00+00:00",
        }
        mock_val = MagicMock(returncode=0, stdout="", stderr="")
        with (
            patch(
                "scripts.execute_recommendation.load_recommendation",
                return_value=self._eligible_rec(),
            ),
            patch(
                "scripts.execute_recommendation.load_checkpoint",
                return_value=checkpoint,
            ),
            patch(
                "scripts.execute_recommendation.get_latest_plan",
                return_value=None,
            ),
            patch(
                "scripts.execute_recommendation.write_run_summary",
            ) as mock_summary,
            patch(
                "scripts.execute_recommendation.ensure_feature_branch",
                return_value=True,
            ),
            patch(
                "scripts.execute_recommendation.subprocess.run",
                return_value=mock_val,
            ),
            patch(
                "scripts.execute_recommendation.clear_checkpoint",
            ),
        ):
            result = execute_recommendation(
                "rec-100",
                resume_postflight=True,
            )

        assert result is False
        assert mock_summary.call_count == 1
        assert mock_summary.call_args.args[3] == "resume-postflight requires an existing plan for checkpointed recommendation"

    def test_resume_postflight_without_checkpoint_fails(self):
        """resume_postflight=True without IMPL_COMPLETE checkpoint returns False."""
        mock_val = MagicMock(returncode=0, stdout="", stderr="")
        with (
            patch("scripts.execute_recommendation.load_recommendation") as mock_load,
            patch(
                "scripts.execute_recommendation.ensure_feature_branch",
                return_value=True,
            ),
            patch(
                "scripts.execute_recommendation.load_checkpoint",
                return_value=None,
            ),
            patch("scripts.execute_recommendation.save_checkpoint"),
            patch("scripts.execute_recommendation.clear_checkpoint"),
            patch("scripts.execute_recommendation.write_run_summary"),
            patch(
                "scripts.execute_recommendation.subprocess.run",
                return_value=mock_val,
            ),
        ):
            mock_load.return_value = self._eligible_rec()
            result = execute_recommendation("rec-100", resume_postflight=True)

        assert result is False

    def test_resume_postflight_with_wrong_status_checkpoint_fails(self):
        """resume_postflight=True rejects same-rec checkpoint unless status is IMPL_COMPLETE."""
        checkpoint = {
            "plan_file": "rec-100",
            "current_step": 1,
            "total_steps": 2,
            "status": "in_progress",
            "branch": "agent/rec-100",
            "last_updated": "2026-04-15T00:00:00+00:00",
        }
        mock_val = MagicMock(returncode=0, stdout="", stderr="")
        with (
            patch("scripts.execute_recommendation.load_recommendation") as mock_load,
            patch(
                "scripts.execute_recommendation.ensure_feature_branch",
                return_value=True,
            ),
            patch(
                "scripts.execute_recommendation.load_checkpoint",
                return_value=checkpoint,
            ),
            patch("scripts.execute_recommendation.save_checkpoint"),
            patch("scripts.execute_recommendation.clear_checkpoint"),
            patch("scripts.execute_recommendation.write_run_summary") as mock_summary,
            patch(
                "scripts.execute_recommendation.subprocess.run",
                return_value=mock_val,
            ),
        ):
            mock_load.return_value = self._eligible_rec()
            result = execute_recommendation("rec-100", resume_postflight=True)

        assert result is False
        assert mock_summary.call_count == 1
        assert mock_summary.call_args.args[3] == "resume-postflight without IMPL_COMPLETE checkpoint"

    def test_resume_postflight_with_foreign_checkpoint_clears_then_fails(self):
        """resume_postflight=True clears stale foreign checkpoint and reports resume-postflight error."""
        checkpoint = {
            "plan_file": "rec-999",
            "current_step": 1,
            "total_steps": 2,
            "status": "IN_PROGRESS",
            "branch": "agent/rec-999",
            "last_updated": "2026-04-15T00:00:00+00:00",
        }
        mock_val = MagicMock(returncode=0, stdout="", stderr="")
        with (
            patch("scripts.execute_recommendation.load_recommendation") as mock_load,
            patch(
                "scripts.execute_recommendation.ensure_feature_branch",
                return_value=True,
            ),
            patch(
                "scripts.execute_recommendation.load_checkpoint",
                return_value=checkpoint,
            ),
            patch("scripts.execute_recommendation.save_checkpoint"),
            patch("scripts.execute_recommendation.clear_checkpoint") as mock_clear,
            patch("scripts.execute_recommendation._is_checkpoint_branch_merged") as mock_is_merged,
            patch("scripts.execute_recommendation.write_run_summary"),
            patch("builtins.print") as mock_print,
            patch(
                "scripts.execute_recommendation.subprocess.run",
                return_value=mock_val,
            ),
        ):
            mock_load.return_value = self._eligible_rec()
            result = execute_recommendation("rec-100", resume_postflight=True)

        assert result is False
        mock_clear.assert_called_once()
        mock_is_merged.assert_not_called()
        printed = " ".join(str(call.args[0]) for call in mock_print.call_args_list if call.args)
        assert "--resume-postflight requires an IMPL_COMPLETE checkpoint" in printed
        assert "Checkpoint exists for different rec" not in printed
