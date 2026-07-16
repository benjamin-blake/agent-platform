"""Preflight side-effect-free contract tests (rec-2709 Wave 2)."""

from unittest.mock import MagicMock, patch

from scripts.execute_recommendation import (
    AcceptanceFeasibility,
    execute_recommendation,
)
from scripts.llm.utils import LLMResponseError


class TestPreflightSideEffectFree:
    """Regression: rejected read-only preflight gates must not
    call ensure_feature_branch() or clean_slate()."""

    def test_not_found_skips_branch_and_cleanup(self):
        """Missing rec rejects before any git side effects."""
        from scripts.execute_recommendation import (
            _execute_recommendation_inner,
        )

        with (
            patch(
                "scripts.execute_recommendation.load_recommendation",
                return_value=None,
            ),
            patch(
                "scripts.execute_recommendation.ensure_feature_branch",
            ) as mock_branch,
            patch(
                "scripts.execute_recommendation.clean_slate",
            ) as mock_clean,
            patch(
                "scripts.execute_recommendation.write_run_summary",
            ),
        ):
            result = _execute_recommendation_inner(
                "rec-missing",
                None,
                True,
            )

        assert result is False
        mock_branch.assert_not_called()
        mock_clean.assert_not_called()

    def test_ineligible_skips_branch_and_cleanup(self):
        """Ineligible rec rejects before any git side effects."""
        from scripts.execute_recommendation import (
            _execute_recommendation_inner,
        )

        with (
            patch(
                "scripts.execute_recommendation.load_recommendation",
                return_value={
                    "id": "rec-bad",
                    "risk": "high",
                    "automatable": False,
                },
            ),
            patch(
                "scripts.execute_recommendation.load_checkpoint",
                return_value=None,
            ),
            patch(
                "scripts.execute_recommendation.ensure_feature_branch",
            ) as mock_branch,
            patch(
                "scripts.execute_recommendation.clean_slate",
            ) as mock_clean,
            patch(
                "scripts.execute_recommendation.write_run_summary",
            ),
        ):
            result = _execute_recommendation_inner(
                "rec-bad",
                None,
                True,
            )

        assert result is False
        mock_branch.assert_not_called()
        mock_clean.assert_not_called()

    def test_infeasible_acceptance_skips_branch_and_cleanup(self):
        """Infeasible acceptance rejects before git side effects."""
        from scripts.execute_recommendation import (
            _execute_recommendation_inner,
        )

        with (
            patch(
                "scripts.execute_recommendation.load_recommendation",
                return_value={
                    "id": "rec-inf",
                    "acceptance": "grep missing.py",
                },
            ),
            patch(
                "scripts.execute_recommendation.load_checkpoint",
                return_value=None,
            ),
            patch(
                "scripts.execute_recommendation.validate_acceptance_feasibility",
                return_value=(
                    AcceptanceFeasibility.INFEASIBLE,
                    "file not found",
                ),
            ),
            patch(
                "scripts.execute_recommendation.update_recommendation_status",
            ),
            patch(
                "scripts.execute_recommendation.ensure_feature_branch",
            ) as mock_branch,
            patch(
                "scripts.execute_recommendation.clean_slate",
            ) as mock_clean,
            patch(
                "scripts.execute_recommendation.write_run_summary",
            ),
        ):
            result = _execute_recommendation_inner(
                "rec-inf",
                None,
                True,
            )

        assert result is False
        mock_branch.assert_not_called()
        mock_clean.assert_not_called()

    def test_foreign_checkpoint_skips_branch_and_cleanup(self):
        """Foreign unmerged checkpoint rejects before git ops."""
        from scripts.execute_recommendation import (
            _execute_recommendation_inner,
        )

        ck = {
            "plan_file": "rec-other",
            "current_step": 1,
            "total_steps": 2,
            "status": "IN_PROGRESS",
            "branch": "agent/rec-other",
            "last_updated": "2026-04-17T00:00:00+00:00",
        }
        with (
            patch(
                "scripts.execute_recommendation.load_recommendation",
                return_value={
                    "id": "rec-new",
                    "title": "New",
                    "risk": "low",
                    "automatable": True,
                    "effort": "S",
                },
            ),
            patch(
                "scripts.execute_recommendation.load_checkpoint",
                return_value=ck,
            ),
            patch(
                "scripts.execute_recommendation._is_checkpoint_branch_merged",
                return_value=False,
            ),
            patch(
                "scripts.execute_recommendation.ensure_feature_branch",
            ) as mock_branch,
            patch(
                "scripts.execute_recommendation.clean_slate",
            ) as mock_clean,
            patch(
                "scripts.execute_recommendation.write_run_summary",
            ),
        ):
            result = _execute_recommendation_inner(
                "rec-new",
                None,
                True,
            )

        assert result is False
        mock_branch.assert_not_called()
        mock_clean.assert_not_called()

    def test_resume_postflight_foreign_skips_branch(self):
        """resume_postflight with foreign checkpoint rejects
        before git side effects."""
        from scripts.execute_recommendation import (
            _execute_recommendation_inner,
        )

        ck = {
            "plan_file": "rec-foreign",
            "current_step": 1,
            "total_steps": 2,
            "status": "IN_PROGRESS",
            "branch": "agent/rec-foreign",
            "last_updated": "2026-04-17T00:00:00+00:00",
        }
        with (
            patch(
                "scripts.execute_recommendation.load_recommendation",
                return_value={
                    "id": "rec-new",
                    "title": "New",
                    "risk": "low",
                    "automatable": True,
                    "effort": "S",
                },
            ),
            patch(
                "scripts.execute_recommendation.load_checkpoint",
                return_value=ck,
            ),
            patch(
                "scripts.execute_recommendation.clear_checkpoint",
            ),
            patch(
                "scripts.execute_recommendation.ensure_feature_branch",
            ) as mock_branch,
            patch(
                "scripts.execute_recommendation.clean_slate",
            ) as mock_clean,
            patch(
                "scripts.execute_recommendation.write_run_summary",
            ),
        ):
            result = _execute_recommendation_inner(
                "rec-new",
                None,
                True,
                resume_postflight=True,
            )

        assert result is False
        mock_branch.assert_not_called()
        mock_clean.assert_not_called()

    def test_success_path_calls_branch_and_cleanup(self):
        """Once read-only gates pass, ensure_feature_branch and
        clean_slate are called for a stale-state rec."""
        mock_val = MagicMock(
            returncode=0,
            stdout="0\n",
            stderr="",
        )
        with (
            patch(
                "scripts.execute_recommendation.load_recommendation",
                return_value={
                    "id": "rec-ok",
                    "title": "Good",
                    "risk": "low",
                    "automatable": True,
                    "effort": "S",
                    "file": "src/ok.py",
                    "execution_result": "failure",
                },
            ),
            patch(
                "scripts.execute_recommendation.load_checkpoint",
                return_value=None,
            ),
            patch(
                "scripts.execute_recommendation.ensure_feature_branch",
                return_value=True,
            ) as mock_branch,
            patch(
                "scripts.execute_recommendation.clean_slate",
            ) as mock_clean,
            patch(
                "scripts.execute_recommendation.prune_merged_agent_branches",
            ),
            patch(
                "scripts.execute_recommendation._commits_ahead_of_main",
                return_value=0,
            ),
            patch(
                "scripts.execute_recommendation.generate_initial_plan",
                side_effect=LLMResponseError("stop"),
            ),
            patch(
                "scripts.execute_recommendation.escalate_planning_model",
                return_value="",
            ),
            patch(
                "scripts.execute_recommendation.subprocess.run",
                return_value=mock_val,
            ),
            patch(
                "scripts.execute_recommendation.write_run_summary",
            ),
        ):
            result = execute_recommendation("rec-ok")

        assert result is False
        mock_branch.assert_called_once()
        mock_clean.assert_called_once()
