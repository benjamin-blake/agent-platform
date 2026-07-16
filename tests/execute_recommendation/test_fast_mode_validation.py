"""Fast-mode input-validation/CLI-parse tests (rec-2709 Wave 2, OPEN RISK 1 sibling-split)."""

import json
from unittest.mock import MagicMock, patch

import pytest

from scripts.execute_recommendation import (
    main,
)


class TestFastModeInputValidation:
    """Tests for --fast mode CLI parsing and plan-JSON input validation (sibling of TestFastMode).

    OPEN RISK 1 sibling-split (rec-2709 Wave 2): this class did not exist in the monolith --
    it carries the 4 validation/CLI tests that used to live in TestFastMode, plus verbatim copies
    of the 3 helper methods they use. The 4 test methods re-qualify from TestFastMode:: to
    TestFastModeInputValidation:: -- the one sanctioned test-id delta in this wave."""

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
