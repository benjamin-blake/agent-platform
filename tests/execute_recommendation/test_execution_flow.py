"""Top-level execute_recommendation and per-step execution tests (rec-2709 Wave 2)."""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from scripts.execute_recommendation import (
    ExecutionPlan,
    commit_step,
    execute_recommendation,
    gather_step_context,
    implement_step,
    run_acceptance,
)
from scripts.executor.step_runner import StepOutcome


class TestExecuteRecommendation:
    """Test full recommendation execution flow."""

    def test_execute_recommendation_not_found(self):
        """Test execution when recommendation not found."""
        with patch("scripts.execute_recommendation.load_recommendation") as mock_load:
            mock_load.return_value = None
            success = execute_recommendation("rec-999")
            assert success is False

    def test_execute_recommendation_not_eligible(self):
        """Test execution when recommendation not eligible."""
        with patch("scripts.execute_recommendation.load_recommendation") as mock_load:
            mock_load.return_value = {"risk": "high", "automatable": False}
            success = execute_recommendation("rec-100")
            assert success is False

    def test_cost_budget_exceeded(self, tmp_path):
        """Budget exceeded after plan generation causes early abort (returns False)."""
        plans_file = tmp_path / "logs" / ".execution-plans.jsonl"
        plans_file.parent.mkdir(parents=True)
        plans_file.write_text("")

        with (
            patch("scripts.execute_recommendation.load_recommendation") as mock_load,
            patch("scripts.execute_recommendation.ensure_feature_branch") as mock_branch,
            patch("scripts.execute_recommendation._commits_ahead_of_main", return_value=0),
            patch("scripts.execute_recommendation.load_checkpoint", return_value=None),
            patch("scripts.execute_recommendation.generate_initial_plan") as mock_gen,
            patch("scripts.execute_recommendation.save_plan"),
            patch("scripts.executor.plan.PLANS_JSONL", plans_file),
            patch.dict("os.environ", {"PLAN_TOKEN_BUDGET": "500"}),
        ):
            mock_load.return_value = {"id": "rec-100", "title": "Test", "risk": "low", "automatable": True, "effort": "S"}
            mock_branch.return_value = True
            mock_gen.return_value = ExecutionPlan(
                rec_id="rec-100",
                slug="test",
                revision=1,
                timestamp="2026-03-31T10:00:00Z",
                status="draft",
                model="test",
                tokens_used=1000,
                steps=[{"n": 1, "title": "Step", "file": "", "action": "modify", "description": "", "acceptance": ""}],
                plan_text="Test plan",
            )

            success = execute_recommendation("rec-100")
            assert success is False

    def test_review_gate_blocking_findings_fails_before_finalize(self):
        """Unresolved blocking findings after retries fail execution and skip finalize()."""
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
        git_ok = MagicMock(returncode=0, stdout="scripts/execute_recommendation.py\n", stderr="")

        with (
            patch("scripts.execute_recommendation.load_recommendation") as mock_load,
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
            patch(
                "scripts.execute_recommendation._code_review_gate",
                return_value=(False, 0.0, ["HIGH: unresolved finding"]),
            ),
            patch("scripts.execute_recommendation._fix_code_review_findings", return_value=False),
            patch("scripts.execute_recommendation.finalize") as mock_finalize,
            patch("scripts.execute_recommendation.update_recommendation_status") as mock_update,
            patch("scripts.execute_recommendation._handle_failure") as mock_handle_failure,
            patch("scripts.execute_recommendation._capture_executor_telemetry") as mock_telemetry,
            patch("scripts.execute_recommendation.write_run_summary") as mock_run_summary,
            patch("scripts.execute_recommendation.subprocess.run", return_value=git_ok),
        ):
            mock_load.return_value = {
                "id": "rec-100",
                "title": "Test rec",
                "risk": "low",
                "automatable": True,
                "effort": "S",
                "file": "scripts/__init__.py",
            }
            success = execute_recommendation("rec-100", skip_critique=True)

        assert success is False
        mock_finalize.assert_not_called()
        mock_handle_failure.assert_called_once()
        mock_telemetry.assert_called_once()
        mock_update.assert_called_once()
        status_update = mock_update.call_args[0][1]
        assert status_update["status"] == "failed"
        assert "code review gate failed" in status_update["failure_reason"]
        assert mock_run_summary.call_args[0][2] == "review_fail"


class TestImplementStep:
    """Test step implementation."""

    def test_implement_step_success(self):
        """Test successful step implementation returns premium request count, not cost_usd."""
        step = {"n": 1, "title": "Create file", "file": "test.py", "action": "create"}

        mock_val_proc = MagicMock()
        mock_val_proc.communicate.return_value = ("", "")
        mock_val_proc.returncode = 0
        mock_val_proc.__enter__ = MagicMock(return_value=mock_val_proc)
        mock_val_proc.__exit__ = MagicMock(return_value=False)
        with (
            patch("scripts.executor.step_runner.llm_call") as mock_call,
            patch("scripts.executor.step_runner.subprocess.Popen", return_value=mock_val_proc),
        ):
            mock_call.return_value = MagicMock(
                exit_code=0, tokens_in=100, tokens_out=0, model="claude-haiku-4.5", session_id="ses-abc123", cost_usd=0.33
            )
            success, reqs, prompt_hash, session_id = implement_step(step, "rec-test", 1, 3)
            assert success == StepOutcome.SUCCESS
            assert reqs == pytest.approx(0.33, abs=0.01)  # haiku = 0.33x
            assert isinstance(prompt_hash, str)
            assert isinstance(session_id, str)

    def test_implement_step_validation_failure(self):
        """Test step implementation with validation failure."""
        step = {"n": 1, "title": "Create file", "file": "test.py"}

        mock_val_proc = MagicMock()
        mock_val_proc.communicate.return_value = ("", "Validation error")
        mock_val_proc.returncode = 1
        mock_val_proc.__enter__ = MagicMock(return_value=mock_val_proc)
        mock_val_proc.__exit__ = MagicMock(return_value=False)
        with (
            patch("scripts.executor.step_runner.llm_call") as mock_call,
            patch("scripts.executor.step_runner.subprocess.Popen", return_value=mock_val_proc),
        ):
            mock_call.return_value = MagicMock(exit_code=0, tokens_in=100, tokens_out=0, session_id=None)
            success, cost, _, _session = implement_step(step, "rec-test", 1, 3)
            assert success == StepOutcome.VALIDATE_FAILED


class TestCommitStep:
    """Test step commit."""

    def test_commit_step_success(self):
        """Test successful commit returns (True, diff_stat_str)."""
        step = {"n": 1, "title": "Test step", "file": "f.py"}

        with (
            patch(
                "scripts.executor.step_runner._enforce_step_scope",
                return_value=True,
            ),
            patch(
                "scripts.execute_recommendation.subprocess.run",
            ) as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0, stdout="1 file changed", stderr="")
            success, diff_stat = commit_step(step, "rec-test", 1)
            assert success is True
            assert isinstance(diff_stat, str)


class TestRunAcceptance:
    """Test run_acceptance() helper function."""

    def test_run_acceptance_pass(self):
        """Command returning exit code 0 returns True."""
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("", "")
        mock_proc.returncode = 0
        mock_proc.__enter__ = MagicMock(return_value=mock_proc)
        mock_proc.__exit__ = MagicMock(return_value=False)
        with patch("scripts.execute_recommendation.subprocess.Popen", return_value=mock_proc):
            result = run_acceptance("python --version")
            assert result is True

    def test_run_acceptance_fail(self):
        """Command returning exit code 1 returns False."""
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("", "")
        mock_proc.returncode = 1
        mock_proc.__enter__ = MagicMock(return_value=mock_proc)
        mock_proc.__exit__ = MagicMock(return_value=False)
        with patch("scripts.execute_recommendation.subprocess.Popen", return_value=mock_proc):
            result = run_acceptance("python --version")
            assert result is False

    def test_run_acceptance_empty(self):
        """Empty acceptance command skips subprocess and returns True."""
        with patch("scripts.execute_recommendation.subprocess.Popen") as mock_popen:
            assert run_acceptance("") is True
            assert run_acceptance("   ") is True
            mock_popen.assert_not_called()

    def test_run_acceptance_parse_error(self):
        """Malformed command (unmatched quote) is passed to bash; bash exits non-zero."""
        with patch("shutil.which", return_value="/usr/bin/bash"):
            mock_proc = MagicMock()
            mock_proc.communicate.return_value = ("", "syntax error")
            mock_proc.returncode = 1
            mock_proc.__enter__ = MagicMock(return_value=mock_proc)
            mock_proc.__exit__ = MagicMock(return_value=False)
            with patch("scripts.execute_recommendation.subprocess.Popen", return_value=mock_proc):
                result = run_acceptance("python -c 'unclosed")
                assert result is False

    def test_run_acceptance_timeout(self):
        """TimeoutExpired from subprocess returns False."""
        mock_proc = MagicMock()
        mock_proc.communicate.side_effect = subprocess.TimeoutExpired(cmd="python", timeout=60)
        mock_proc.pid = 12345
        mock_proc.__enter__ = MagicMock(return_value=mock_proc)
        mock_proc.__exit__ = MagicMock(return_value=False)
        with patch("scripts.execute_recommendation.subprocess.Popen", return_value=mock_proc):
            with patch("scripts.execute_recommendation.kill_process_tree"):
                result = run_acceptance("python slow_command.py")
                assert result is False


class TestGatherStepContext:
    def test_modify_action_reads_file_content(self, tmp_path, monkeypatch):
        """For modify action, file_content is populated from the step file."""
        monkeypatch.chdir(tmp_path)
        target = tmp_path / "src" / "module.py"
        target.parent.mkdir(parents=True)
        target.write_text("def hello(): pass", encoding="utf-8")

        step = {"action": "modify", "file": "src/module.py"}
        ctx = gather_step_context(step)
        assert "def hello()" in ctx["file_content"]
        assert ctx["pattern_content"] == ""

    def test_create_action_uses_pattern_file(self, tmp_path, monkeypatch):
        """For create action, pattern_content comes from a similar existing file."""
        monkeypatch.chdir(tmp_path)
        existing = tmp_path / "scripts" / "existing_script.py"
        existing.parent.mkdir(parents=True)
        existing.write_text("# existing\ndef run(): pass", encoding="utf-8")

        step = {"action": "create", "file": "scripts/new_script.py"}
        ctx = gather_step_context(step)
        assert "existing" in ctx["pattern_content"] or ctx["pattern_content"] != ""
        assert ctx["file_content"] == ""

    def test_file_not_found_returns_empty_no_error(self, tmp_path, monkeypatch):
        """Missing file causes graceful empty string, no exception."""
        monkeypatch.chdir(tmp_path)
        step = {"action": "modify", "file": "scripts/nonexistent.py"}
        ctx = gather_step_context(step)
        assert ctx["file_content"] == ""
        assert ctx["test_content"] == ""
        assert ctx["pattern_content"] == ""

    def test_large_file_truncated_with_marker(self, tmp_path, monkeypatch):
        """File content exceeding max_chars is truncated with an omission marker."""
        monkeypatch.chdir(tmp_path)
        target = tmp_path / "scripts" / "big.py"
        target.parent.mkdir(parents=True)
        big_content = "x = 1\n" * 20000  # ~120K chars
        target.write_text(big_content, encoding="utf-8")

        step = {"action": "modify", "file": "scripts/big.py"}
        ctx = gather_step_context(step, max_chars=50000)
        assert len(ctx["file_content"]) <= 50000 + 200  # allow for marker overhead
        assert "omitted" in ctx["file_content"]

    def test_test_file_found(self, tmp_path, monkeypatch):
        """Corresponding test file is loaded into test_content."""
        monkeypatch.chdir(tmp_path)
        src = tmp_path / "scripts" / "my_module.py"
        src.parent.mkdir(parents=True)
        src.write_text("def fn(): pass", encoding="utf-8")
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        test_file = tests_dir / "test_my_module.py"
        test_file.write_text("def test_fn(): pass", encoding="utf-8")

        step = {"action": "modify", "file": "scripts/my_module.py"}
        ctx = gather_step_context(step)
        assert "test_fn" in ctx["test_content"]
