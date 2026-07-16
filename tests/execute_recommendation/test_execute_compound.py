"""Compound-rec execution tests (rec-2709 Wave 2)."""

from unittest.mock import MagicMock, patch

from scripts.executor.step_runner import StepOutcome


class TestExecuteCompound:
    """Tests for execute_compound() function."""

    @patch("scripts.executor.postflight.finalize", return_value="https://github.com/test/pr/1")
    @patch("scripts.executor.postflight._code_review_gate", return_value=(True, 0.0, []))
    @patch("scripts.executor.jsonl_store.update_recommendation_status")
    @patch("scripts.executor.step_runner._append_step_telemetry")
    @patch("scripts.executor.step_runner.commit_step", return_value=(True, "1 file changed"))
    @patch("scripts.executor.step_runner.implement_step", return_value=(StepOutcome.SUCCESS, 0.5, "hash", None))
    @patch("scripts.executor.plan.save_plan")
    @patch("scripts.executor.plan._detect_critique_cycling", return_value=False)
    @patch("scripts.executor.plan.refine_plan")
    @patch("scripts.executor.plan.critique_plan", return_value={"verdict": "approved", "suggestions": []})
    @patch("scripts.executor.plan.generate_initial_plan")
    @patch("scripts.executor.jsonl_store.load_recommendation")
    @patch("scripts.executor.batch._ensure_compound_branch", return_value=True)
    def test_compound_creates_single_branch(
        self,
        mock_branch,
        mock_load,
        mock_gen,
        mock_critique,
        mock_refine,
        mock_cycling,
        mock_save,
        mock_impl,
        mock_commit,
        mock_telem,
        mock_update,
        mock_review_gate,
        mock_finalize,
    ):
        """Creates one compound branch and one PR for multiple recs."""
        from scripts.execute_recommendation import execute_compound

        fake_plan = MagicMock()
        fake_plan.steps = [{"n": 1, "title": "t", "file": "f.py"}]
        fake_plan.status = "draft"
        fake_plan.critique_history = []
        mock_gen.return_value = fake_plan
        mock_load.side_effect = [
            {"id": "rec-042", "title": "A", "file": "a.py"},
            {"id": "rec-043", "title": "B", "file": "b.py"},
        ]

        result = execute_compound(["rec-042", "rec-043"])

        mock_branch.assert_called_once_with("agent/compound-rec-042")
        assert result["attempted"] == 2
        assert result["succeeded"] == 2
        assert result["failed"] == 0
        assert result["pr_url"] == "https://github.com/test/pr/1"
        mock_finalize.assert_called_once()

    @patch("scripts.executor.postflight.finalize", return_value="https://github.com/test/pr/1")
    @patch("scripts.executor.postflight._code_review_gate", return_value=(True, 0.0, []))
    @patch("scripts.executor.jsonl_store.update_recommendation_status")
    @patch("scripts.executor.step_runner._append_step_telemetry")
    @patch("scripts.executor.step_runner.commit_step", return_value=(True, "1 file changed"))
    @patch("scripts.executor.step_runner.implement_step", return_value=(StepOutcome.SUCCESS, 0.5, "hash", None))
    @patch("scripts.executor.plan.save_plan")
    @patch("scripts.executor.plan._detect_critique_cycling", return_value=False)
    @patch("scripts.executor.plan.refine_plan")
    @patch("scripts.executor.plan.critique_plan", return_value={"verdict": "approved", "suggestions": []})
    @patch("scripts.executor.plan.generate_initial_plan")
    @patch("scripts.executor.jsonl_store.load_recommendation")
    @patch("scripts.executor.batch._ensure_compound_branch", return_value=True)
    def test_compound_commits_per_rec(
        self,
        mock_branch,
        mock_load,
        mock_gen,
        mock_critique,
        mock_refine,
        mock_cycling,
        mock_save,
        mock_impl,
        mock_commit,
        mock_telem,
        mock_update,
        mock_review_gate,
        mock_finalize,
    ):
        """Verifies commit_step is called for each rec's steps."""
        from scripts.execute_recommendation import execute_compound

        fake_plan = MagicMock()
        fake_plan.steps = [{"n": 1, "title": "t", "file": "f.py"}]
        fake_plan.status = "draft"
        fake_plan.critique_history = []
        mock_gen.return_value = fake_plan
        mock_load.side_effect = [
            {"id": "rec-100", "title": "A", "file": "a.py"},
            {"id": "rec-101", "title": "B", "file": "b.py"},
        ]

        execute_compound(["rec-100", "rec-101"])

        # commit_step called once per rec (1 step each)
        assert mock_commit.call_count == 2
        assert mock_commit.call_args_list[0].args[1] == "rec-100"
        assert mock_commit.call_args_list[1].args[1] == "rec-101"

    @patch("scripts.executor.postflight.finalize", return_value="https://github.com/test/pr/1")
    @patch("scripts.executor.postflight._code_review_gate", return_value=(True, 0.0, []))
    @patch("scripts.executor.jsonl_store.update_recommendation_status")
    @patch("scripts.executor.step_runner._append_step_telemetry")
    @patch("scripts.executor.step_runner.commit_step", return_value=(True, ""))
    @patch("scripts.executor.step_runner.implement_step")
    @patch("scripts.executor.plan.save_plan")
    @patch("scripts.executor.plan._detect_critique_cycling", return_value=False)
    @patch("scripts.executor.plan.refine_plan")
    @patch("scripts.executor.plan.critique_plan", return_value={"verdict": "approved", "suggestions": []})
    @patch("scripts.executor.plan.generate_initial_plan")
    @patch("scripts.executor.jsonl_store.load_recommendation")
    @patch("scripts.executor.batch._ensure_compound_branch", return_value=True)
    def test_compound_single_pr(
        self,
        mock_branch,
        mock_load,
        mock_gen,
        mock_critique,
        mock_refine,
        mock_cycling,
        mock_save,
        mock_impl,
        mock_commit,
        mock_telem,
        mock_update,
        mock_review_gate,
        mock_finalize,
    ):
        """Only one finalize/PR created even when processing 3 recs."""
        from scripts.execute_recommendation import execute_compound

        fake_plan = MagicMock()
        fake_plan.steps = [{"n": 1, "title": "t", "file": "f.py"}]
        fake_plan.status = "draft"
        fake_plan.critique_history = []
        mock_gen.return_value = fake_plan
        mock_impl.side_effect = [
            (StepOutcome.SUCCESS, 0.5, "h", None),
            (StepOutcome.GHOST_STEP, 0.5, "h", None),
            (StepOutcome.SUCCESS, 0.5, "h", None),
        ]
        mock_load.side_effect = [
            {"id": "rec-200", "title": "A", "file": "a.py"},
            {"id": "rec-201", "title": "B", "file": "b.py"},
            {"id": "rec-202", "title": "C", "file": "c.py"},
        ]

        result = execute_compound(["rec-200", "rec-201", "rec-202"])

        assert result["succeeded"] == 2
        assert result["failed"] == 1
        # Only one finalize call
        mock_finalize.assert_called_once()

    @patch("scripts.executor.postflight.finalize", return_value="https://github.com/test/pr/1")
    @patch("scripts.executor.postflight._code_review_gate", return_value=(True, 0.0, []))
    @patch("scripts.executor.jsonl_store.update_recommendation_status")
    @patch("scripts.executor.step_runner._append_step_telemetry")
    @patch("scripts.executor.step_runner.commit_step", return_value=(True, "1 file changed"))
    @patch("scripts.executor.step_runner.implement_step", return_value=(StepOutcome.SUCCESS, 0.5, "hash", None))
    @patch("scripts.executor.plan.save_plan")
    @patch("scripts.executor.plan._detect_critique_cycling", return_value=False)
    @patch("scripts.executor.plan.refine_plan")
    @patch("scripts.executor.plan.critique_plan", return_value={"verdict": "approved", "suggestions": []})
    @patch("scripts.executor.plan.generate_initial_plan")
    @patch("scripts.executor.jsonl_store.load_recommendation")
    @patch("scripts.executor.batch._ensure_compound_branch", return_value=True)
    def test_compound_updates_all_statuses(
        self,
        mock_branch,
        mock_load,
        mock_gen,
        mock_critique,
        mock_refine,
        mock_cycling,
        mock_save,
        mock_impl,
        mock_commit,
        mock_telem,
        mock_update,
        mock_review_gate,
        mock_finalize,
    ):
        """All successful recs get status updated to closed/compound."""
        from scripts.execute_recommendation import execute_compound

        fake_plan = MagicMock()
        fake_plan.steps = [{"n": 1, "title": "t", "file": "f.py"}]
        fake_plan.status = "draft"
        fake_plan.critique_history = []
        mock_gen.return_value = fake_plan
        mock_load.side_effect = [
            {"id": "rec-300", "title": "A", "file": "a.py"},
            {"id": "rec-301", "title": "B", "file": "b.py"},
        ]

        execute_compound(["rec-300", "rec-301"], cluster_id="cluster-001")

        # Branch uses cluster naming
        mock_branch.assert_called_once_with("agent/cluster-cluster-001")
        # Both recs updated
        assert mock_update.call_count == 2
        for update_call in mock_update.call_args_list:
            status_dict = update_call.args[1]
            assert status_dict["status"] == "closed"
            assert status_dict["execution_result"] == "compound"

    @patch("scripts.execute_recommendation.subprocess.run")
    @patch("scripts.executor.jsonl_store.update_recommendation_status")
    @patch("scripts.executor.step_runner._append_step_telemetry")
    @patch("scripts.executor.step_runner.commit_step", return_value=(True, "1 file changed"))
    @patch("scripts.executor.step_runner.implement_step")
    @patch("scripts.executor.plan.save_plan")
    @patch("scripts.executor.plan._detect_critique_cycling", return_value=False)
    @patch("scripts.executor.plan.refine_plan")
    @patch("scripts.executor.plan.critique_plan", return_value={"verdict": "approved", "suggestions": []})
    @patch("scripts.executor.plan.generate_initial_plan")
    @patch("scripts.executor.jsonl_store.load_recommendation")
    @patch("scripts.executor.batch._ensure_compound_branch", return_value=True)
    def test_compound_resets_commits_on_step_failure(
        self,
        mock_branch,
        mock_load,
        mock_gen,
        mock_critique,
        mock_refine,
        mock_cycling,
        mock_save,
        mock_impl,
        mock_commit,
        mock_telem,
        mock_update,
        mock_subprocess_run,
    ):
        """When a step fails, git reset HEAD~N removes commits from earlier steps."""
        from scripts.execute_recommendation import execute_compound

        fake_plan = MagicMock()
        fake_plan.steps = [
            {"n": 1, "title": "step1", "file": "a.py"},
            {"n": 2, "title": "step2", "file": "b.py"},
        ]
        fake_plan.status = "draft"
        fake_plan.critique_history = []
        mock_gen.return_value = fake_plan
        mock_impl.side_effect = [
            (StepOutcome.SUCCESS, 0.5, "h1", None),
            (StepOutcome.ACCEPTANCE_FAILED, 0.5, "h2", None),
        ]
        mock_load.return_value = {"id": "rec-400", "title": "Test", "file": "test.py"}
        mock_subprocess_run.return_value = MagicMock(returncode=0)

        result = execute_compound(["rec-400"])

        assert result["failed"] == 1
        # Find the git reset call
        reset_call = None
        for call_obj in mock_subprocess_run.call_args_list:
            args = call_obj[0][0] if call_obj[0] else call_obj.kwargs.get("args", [])
            if "git" in args and "reset" in args:
                reset_call = args
                break
        assert reset_call is not None, "git reset should be called when step fails"
        assert reset_call == ["git", "reset", "HEAD~1"], f"Expected ['git', 'reset', 'HEAD~1'], got {reset_call}"

    def test_compound_review_blocking_findings_fail_batch(self):
        """Compound execution fails and skips finalize when blocking findings remain."""
        from scripts.execute_recommendation import execute_compound

        fake_plan = MagicMock()
        fake_plan.steps = [{"n": 1, "title": "t", "file": "f.py"}]
        fake_plan.status = "draft"
        fake_plan.critique_history = []

        git_ok = MagicMock(returncode=0, stdout="scripts/execute_recommendation.py\n", stderr="")

        with (
            patch("scripts.executor.batch._ensure_compound_branch", return_value=True),
            patch(
                "scripts.executor.jsonl_store.load_recommendation",
                return_value={"id": "rec-500", "title": "A", "file": "a.py"},
            ),
            patch("scripts.executor.plan.generate_initial_plan", return_value=fake_plan),
            patch("scripts.executor.plan.critique_plan", return_value={"verdict": "approved", "suggestions": []}),
            patch("scripts.executor.plan.refine_plan"),
            patch("scripts.executor.plan._detect_critique_cycling", return_value=False),
            patch("scripts.executor.plan.save_plan"),
            patch(
                "scripts.executor.step_runner.implement_step",
                return_value=(StepOutcome.SUCCESS, 0.5, "hash", None),
            ),
            patch("scripts.executor.step_runner.commit_step", return_value=(True, "1 file changed")),
            patch("scripts.executor.step_runner._append_step_telemetry"),
            patch(
                "scripts.executor.postflight._code_review_gate",
                return_value=(False, 0.0, ["HIGH: unresolved finding"]),
            ),
            patch("scripts.executor.postflight._fix_code_review_findings", return_value=False),
            patch("scripts.executor.postflight.finalize") as mock_finalize,
            patch("scripts.executor.jsonl_store.update_recommendation_status") as mock_update,
            patch("scripts.execute_recommendation.subprocess.run", return_value=git_ok),
        ):
            result = execute_compound(["rec-500"])

        assert result["attempted"] == 1
        assert result["succeeded"] == 0
        assert result["failed"] == 1
        mock_finalize.assert_not_called()
        mock_update.assert_called_once()
        status_update = mock_update.call_args[0][1]
        assert status_update["status"] == "failed"
        assert "compound code review gate failed" in status_update["failure_reason"]
