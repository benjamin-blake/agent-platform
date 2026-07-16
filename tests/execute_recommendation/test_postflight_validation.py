"""Warm-base auto-resume, doc-only validation fallback, and postflight validation quarantine tests (rec-2709 Wave 2)."""

from unittest.mock import MagicMock, patch

from scripts.execute_recommendation import (
    AcceptanceFeasibility,
    ExecutionPlan,
    execute_recommendation,
)
from scripts.executor.step_runner import StepOutcome


class TestWarmBaseAndAutoResume:
    """Tests for XS/S warm_base skip and --auto-resume dispatch logic."""

    def _eligible_rec(self, effort: str = "XS") -> dict:
        return {"id": "rec-100", "title": "Test rec", "risk": "low", "automatable": True, "effort": effort}

    def _approved_plan(self) -> ExecutionPlan:
        return ExecutionPlan(
            rec_id="rec-100",
            slug="rec-100",
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

    def _common_patches(self, stack, checkpoint=None, *, latest_plan_ret=None, rec=None):
        """Enter common patches into an ExitStack and return a dict of mock references."""
        mock_val = MagicMock(returncode=0, stdout="", stderr="")
        mocks = {}
        mocks["load_rec"] = stack.enter_context(
            patch("scripts.execute_recommendation.load_recommendation", return_value=rec or self._eligible_rec())
        )
        mocks["ensure"] = stack.enter_context(patch("scripts.execute_recommendation.ensure_feature_branch", return_value=True))
        mocks["load_ck"] = stack.enter_context(
            patch("scripts.execute_recommendation.load_checkpoint", return_value=checkpoint)
        )
        stack.enter_context(patch("scripts.execute_recommendation.save_checkpoint"))
        stack.enter_context(patch("scripts.execute_recommendation.clear_checkpoint"))
        stack.enter_context(patch("scripts.execute_recommendation._commits_ahead_of_main", return_value=0))
        mocks["gen"] = stack.enter_context(patch("scripts.execute_recommendation.generate_initial_plan"))
        mocks["latest"] = stack.enter_context(
            patch("scripts.execute_recommendation.get_latest_plan", return_value=latest_plan_ret)
        )
        mocks["critique"] = stack.enter_context(patch("scripts.execute_recommendation.critique_plan"))
        stack.enter_context(patch("scripts.execute_recommendation.save_plan"))
        mocks["impl"] = stack.enter_context(patch("scripts.execute_recommendation.implement_step"))
        stack.enter_context(patch("scripts.execute_recommendation.commit_step", return_value=(True, "1 file")))
        stack.enter_context(patch("scripts.execute_recommendation._append_step_telemetry"))
        mocks["finalize"] = stack.enter_context(
            patch("scripts.execute_recommendation.finalize", return_value="https://github.com/pr/1")
        )
        stack.enter_context(patch("scripts.execute_recommendation.update_recommendation_status"))
        stack.enter_context(patch("scripts.execute_recommendation._scope_drift_check", return_value=[]))
        mocks["review"] = stack.enter_context(
            patch("scripts.execute_recommendation._code_review_gate", return_value=(True, 0.0, []))
        )
        mock_popen = stack.enter_context(patch("scripts.execute_recommendation.subprocess.Popen"))
        mock_popen.return_value.__enter__ = MagicMock(return_value=mock_popen.return_value)
        mock_popen.return_value.__exit__ = MagicMock(return_value=False)
        mock_popen.return_value.communicate.return_value = ("", "")
        mock_popen.return_value.returncode = 0
        stack.enter_context(patch("scripts.execute_recommendation.subprocess.run", return_value=mock_val))
        return mocks

    def test_xs_effort_skips_seed_session(self):
        """execute_recommendation with effort=XS must NOT call _seed_gemini_session."""
        from contextlib import ExitStack

        with ExitStack() as stack:
            mocks = self._common_patches(stack)
            mock_seed = stack.enter_context(patch("scripts.execute_recommendation._seed_gemini_session"))
            stack.enter_context(patch("scripts.llm.model_registry.resolve_provider", return_value="gemini"))
            mocks["gen"].return_value = self._approved_plan()
            mocks["critique"].return_value = {"verdict": "approved", "suggestions": [], "tokens_used": 10}
            mocks["impl"].return_value = (StepOutcome.SUCCESS, 0.01, "abc123def456", "ses-step")  # pragma: allowlist secret

            execute_recommendation("rec-100", skip_critique=True)

        mock_seed.assert_not_called()

    def test_auto_resume_from_impl_complete(self):
        """auto_resume=True with IMPL_COMPLETE checkpoint skips plan/impl and runs postflight."""
        from contextlib import ExitStack

        checkpoint = {
            "plan_file": "rec-100",
            "current_step": 1,
            "total_steps": 1,
            "status": "IMPL_COMPLETE",
            "branch": "agent/rec-100",
            "last_updated": "2026-04-27T00:00:00+00:00",
        }
        with ExitStack() as stack:
            mocks = self._common_patches(stack, checkpoint=checkpoint, latest_plan_ret=self._approved_plan())

            result = execute_recommendation("rec-100", auto_resume=True)

        assert result is True
        mocks["gen"].assert_not_called()
        mocks["critique"].assert_not_called()
        mocks["impl"].assert_not_called()
        mocks["finalize"].assert_called_once()
        # Code review should run (skip_to_finalize is False for IMPL_COMPLETE)
        mocks["review"].assert_called_once()

    def test_auto_resume_from_ci_pending(self):
        """auto_resume=True with CI_PENDING checkpoint skips plan/impl/review and runs finalize."""
        from contextlib import ExitStack

        checkpoint = {
            "plan_file": "rec-100",
            "current_step": 1,
            "total_steps": 1,
            "status": "CI_PENDING",
            "branch": "agent/rec-100",
            "last_updated": "2026-04-27T00:00:00+00:00",
        }
        with ExitStack() as stack:
            mocks = self._common_patches(stack, checkpoint=checkpoint, latest_plan_ret=self._approved_plan())

            result = execute_recommendation("rec-100", auto_resume=True)

        assert result is True
        mocks["gen"].assert_not_called()
        mocks["critique"].assert_not_called()
        mocks["impl"].assert_not_called()
        mocks["finalize"].assert_called_once()
        # Code review must be skipped (skip_to_finalize=True for CI_PENDING)
        mocks["review"].assert_not_called()


class TestDocOnlyValidationFallback:
    """Test that doc-only diffs trigger --scope auto validation fallback."""

    def test_doc_only_diff_triggers_scope_auto(self):
        """When full validation fails and diff has no .py files, fallback uses --scope auto."""
        from contextlib import ExitStack

        plan = ExecutionPlan(
            rec_id="rec-100",
            slug="rec-100",
            revision=1,
            timestamp="2026-04-15T10:00:00Z",
            status="approved",
            model="test",
            tokens_used=100,
            steps=[
                {
                    "n": 1,
                    "title": "step",
                    "file": "docs/README.md",
                    "action": "modify",
                    "description": "",
                    "acceptance": "",
                }
            ],
            plan_text="",
        )

        # First Popen: full validation -- fails (returncode=1)
        full_val_proc = MagicMock()
        full_val_proc.communicate.return_value = ("fail output", "")
        full_val_proc.returncode = 1
        full_val_proc.__enter__ = MagicMock(return_value=full_val_proc)
        full_val_proc.__exit__ = MagicMock(return_value=False)

        # Second Popen: quick validation fallback -- succeeds
        quick_val_proc = MagicMock()
        quick_val_proc.communicate.return_value = ("ok", "")
        quick_val_proc.returncode = 0
        quick_val_proc.__enter__ = MagicMock(return_value=quick_val_proc)
        quick_val_proc.__exit__ = MagicMock(return_value=False)

        popen_calls = []
        popen_side_effects = [full_val_proc, quick_val_proc]

        def popen_tracker(*args, **kwargs):
            popen_calls.append((args, kwargs))
            return popen_side_effects.pop(0)

        # subprocess.run for git diff returns only non-.py files
        git_diff_result = MagicMock(
            returncode=0,
            stdout="docs/README.md\nconfig/settings.yaml\n",
            stderr="",
        )

        patches = [
            patch("scripts.execute_recommendation.load_recommendation"),
            patch(
                "scripts.execute_recommendation.ensure_feature_branch",
                return_value=True,
            ),
            patch("scripts.execute_recommendation.prune_merged_agent_branches"),
            patch(
                "scripts.execute_recommendation.load_checkpoint",
                return_value=None,
            ),
            patch(
                "scripts.execute_recommendation._commits_ahead_of_main",
                return_value=0,
            ),
            patch(
                "scripts.execute_recommendation.get_latest_plan",
                return_value=None,
            ),
            patch(
                "scripts.execute_recommendation.generate_initial_plan",
                return_value=plan,
            ),
            patch("scripts.execute_recommendation.save_plan"),
            patch(
                "scripts.execute_recommendation.implement_step",
                return_value=(StepOutcome.SUCCESS, 0.25, "abc123", "s-1"),
            ),
            patch(
                "scripts.execute_recommendation.commit_step",
                return_value=(True, "1 file changed"),
            ),
            patch("scripts.execute_recommendation._append_step_telemetry"),
            patch(
                "scripts.execute_recommendation._scope_drift_check",
                return_value=[],
            ),
            patch(
                "scripts.execute_recommendation._code_review_gate",
                return_value=(True, 0.25, []),
            ),
            patch(
                "scripts.execute_recommendation.subprocess.Popen",
                side_effect=popen_tracker,
            ),
            patch(
                "scripts.execute_recommendation.run_acceptance",
                return_value=True,
            ),
            patch(
                "scripts.execute_recommendation.finalize",
                return_value="https://github.com/example/pr/1",
            ),
            patch("scripts.execute_recommendation.update_recommendation_status"),
            patch("scripts.execute_recommendation._handle_failure"),
            patch("scripts.execute_recommendation._capture_executor_telemetry"),
            patch("scripts.execute_recommendation.write_run_summary"),
            patch("scripts.execute_recommendation.clear_checkpoint"),
            patch(
                "scripts.execute_recommendation.lint_acceptance_command",
                return_value=(True, ""),
            ),
            patch(
                "scripts.execute_recommendation.validate_acceptance_feasibility",
                return_value=(AcceptanceFeasibility.FEASIBLE, ""),
            ),
            patch(
                "scripts.execute_recommendation.subprocess.run",
                return_value=git_diff_result,
            ),
        ]

        with ExitStack() as stack:
            mocks = [stack.enter_context(p) for p in patches]
            mock_load = mocks[0]
            mock_load.return_value = {
                "id": "rec-100",
                "title": "Test rec",
                "risk": "low",
                "automatable": True,
                "effort": "S",
                "file": "docs/README.md",
                "acceptance": "grep -q 'pattern' docs/README.md",
            }
            execute_recommendation("rec-100", skip_critique=True)

        # Second Popen call should be the --scope prompts fallback
        assert len(popen_calls) >= 2, f"Expected at least 2 Popen calls, got {len(popen_calls)}"
        second_call_args = popen_calls[1][0][0]
        assert "--scope" in second_call_args, f"Expected '--scope' in fallback argv: {second_call_args}"
        scope_idx = second_call_args.index("--scope")
        assert second_call_args[scope_idx + 1] == "prompts", (
            f"Expected '--scope prompts', got '--scope {second_call_args[scope_idx + 1]}'"
        )


class TestPostflightValidationQuarantine:
    """Tests for quarantined baseline validation failures in postflight."""

    def test_known_baseline_failure_allows_finalize(self, monkeypatch):
        """A known baseline-red test failure is recorded and does not block finalize."""
        from contextlib import ExitStack

        monkeypatch.setenv("SKIP_CI_WAIT", "true")

        plan = ExecutionPlan(
            rec_id="rec-100",
            slug="rec-100",
            revision=1,
            timestamp="2026-04-15T10:00:00Z",
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

        full_val_output = (
            "FAILED tests\\test_execute_recommendation.py::"
            "TestPlanningContextInjection::test_empty_context_does_not_fail"
            " - planner error\n"
            "=== Validation Summary (scope: python) ===\n"
            "Failed checks:\n"
            "  - Unit tests + coverage\n\n"
            "Fix all failures before committing.\n"
        )

        full_val_proc = MagicMock()
        full_val_proc.communicate.return_value = (full_val_output, "")
        full_val_proc.returncode = 1
        full_val_proc.__enter__ = MagicMock(return_value=full_val_proc)
        full_val_proc.__exit__ = MagicMock(return_value=False)

        patches = [
            patch("scripts.execute_recommendation.load_recommendation"),
            patch(
                "scripts.execute_recommendation.ensure_feature_branch",
                return_value=True,
            ),
            patch("scripts.execute_recommendation.prune_merged_agent_branches"),
            patch(
                "scripts.execute_recommendation.load_checkpoint",
                return_value=None,
            ),
            patch(
                "scripts.execute_recommendation._commits_ahead_of_main",
                return_value=0,
            ),
            patch(
                "scripts.execute_recommendation.get_latest_plan",
                return_value=None,
            ),
            patch(
                "scripts.execute_recommendation.generate_initial_plan",
                return_value=plan,
            ),
            patch("scripts.execute_recommendation.save_plan"),
            patch(
                "scripts.execute_recommendation.implement_step",
                return_value=(StepOutcome.SUCCESS, 0.25, "abc123", "s-1"),
            ),
            patch(
                "scripts.execute_recommendation.commit_step",
                return_value=(True, "1 file changed"),
            ),
            patch("scripts.execute_recommendation._append_step_telemetry"),
            patch(
                "scripts.execute_recommendation._scope_drift_check",
                return_value=[],
            ),
            patch(
                "scripts.execute_recommendation._code_review_gate",
                return_value=(True, 0.25, []),
            ),
            patch(
                "scripts.execute_recommendation.subprocess.Popen",
                return_value=full_val_proc,
            ),
            patch(
                "scripts.execute_recommendation.run_acceptance",
                return_value=True,
            ),
            patch(
                "scripts.execute_recommendation.finalize",
                return_value="https://github.com/example/pr/1",
            ),
            patch("scripts.execute_recommendation.update_recommendation_status"),
            patch("scripts.execute_recommendation._handle_failure"),
            patch("scripts.execute_recommendation._capture_executor_telemetry"),
            patch("scripts.execute_recommendation.write_run_summary"),
            patch("scripts.execute_recommendation.clear_checkpoint"),
            patch(
                "scripts.execute_recommendation.lint_acceptance_command",
                return_value=(True, ""),
            ),
            patch(
                "scripts.execute_recommendation.validate_acceptance_feasibility",
                return_value=(AcceptanceFeasibility.FEASIBLE, ""),
            ),
        ]

        with ExitStack() as stack:
            mocks = [stack.enter_context(p) for p in patches]
            mock_load = mocks[0]
            mock_finalize = mocks[15]
            mock_update = mocks[16]
            mock_summary = mocks[19]
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
        mock_finalize.assert_called_once_with("rec-100", no_merge=False)
        assert mock_update.call_args_list[-1].args[1]["status"] == "closed"
        pf_meta = mock_summary.call_args.kwargs["postflight_validation"]
        assert pf_meta["result"] == "pass_with_quarantine"
        assert pf_meta["quarantined_tests"] == [
            "tests/test_execute_recommendation.py::TestPlanningContextInjection::test_empty_context_does_not_fail"
        ]
