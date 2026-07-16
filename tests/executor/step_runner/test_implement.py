"""step_runner implement-step / ghost-detection / resume-skip tests: implement_step
(rec-2709 Wave 5).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import scripts.executor.step_runner as sr_mod
from scripts.executor.step_runner import StepOutcome, implement_step


class TestImplementStep:
    """Tests for implement_step() integration with auto_format_test_files()."""

    def _make_step(self, title: str = "do something", file: str = "src/mymodule.py", action: str = "modify") -> dict:
        return {
            "n": 1,
            "title": title,
            "file": file,
            "action": action,
            "description": "test step",
            "acceptance": "",
        }

    def test_calls_auto_format_test_files_and_fails_when_formatting_fails(self) -> None:
        """Verifies that implement_step() calls auto_format_test_files() and fails if it returns False."""
        step = self._make_step()

        # Mock llm_call to succeed
        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.model = "claude-opus-4.6"
        mock_result.tokens_in = 1000
        mock_result.tokens_out = 0
        mock_result.cost_usd = 1.0

        # Mock auto_format_test_files to fail
        with (
            patch("scripts.executor.step_runner.llm_call", return_value=mock_result),
            patch("scripts.executor.step_runner.auto_format_test_files", return_value=False),
        ):
            success, reqs, prompt_hash, session_id = implement_step(step, "rec-001", 1, 1)

        assert success == StepOutcome.FORMAT_ERROR
        assert reqs == 1.0

    def test_calls_auto_format_test_files_and_succeeds_when_formatting_succeeds(self) -> None:
        """Verifies that implement_step() calls auto_format_test_files() and continues when it returns True."""
        step = self._make_step()

        # Mock llm_call to succeed
        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.model = "claude-opus-4.6"
        mock_result.tokens_in = 1000
        mock_result.tokens_out = 0
        mock_result.cost_usd = 1.0

        # Mock auto_format_test_files to succeed
        # Also mock validate.py to succeed
        mock_val_proc = MagicMock()
        mock_val_proc.returncode = 0
        mock_val_proc.communicate.return_value = ("validation passed", "")
        mock_val_proc.__enter__ = lambda self: self
        mock_val_proc.__exit__ = MagicMock(return_value=False)

        with (
            patch("scripts.executor.step_runner.llm_call", return_value=mock_result),
            patch("scripts.executor.step_runner.auto_format_test_files", return_value=True),
            patch("scripts.executor.step_runner._run_ruff_fix", return_value=True),
            patch("scripts.executor.step_runner._run_ruff_format", return_value=True),
            patch("subprocess.Popen", return_value=mock_val_proc),
        ):
            success, reqs, prompt_hash, session_id = implement_step(step, "rec-001", 1, 1)

        assert success == StepOutcome.SUCCESS
        assert reqs == 1.0

    def test_fails_when_ruff_fix_fails(self) -> None:
        """implement_step() fails if _run_ruff_fix returns False."""
        step = self._make_step()

        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.model = "claude-opus-4.6"
        mock_result.tokens_in = 1000
        mock_result.tokens_out = 0
        mock_result.cost_usd = 1.0

        with (
            patch("scripts.executor.step_runner.llm_call", return_value=mock_result),
            patch("scripts.executor.step_runner.auto_format_test_files", return_value=True),
            patch("scripts.executor.step_runner._run_ruff_fix", return_value=False),
        ):
            success, reqs, prompt_hash, session_id = implement_step(step, "rec-001", 1, 1)

        assert success == StepOutcome.RUFF_ERROR
        assert reqs == 1.0

    def test_implement_step_uses_context_file(self) -> None:
        """Verify implement_step passes context_file_path and inline_instruction."""
        step = self._make_step()

        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.model = "claude-opus-4.6"
        mock_result.tokens_in = 1000
        mock_result.tokens_out = 0
        mock_result.cost_usd = 1.0

        mock_val_proc = MagicMock()
        mock_val_proc.returncode = 0
        mock_val_proc.communicate.return_value = ("validation passed", "")
        mock_val_proc.__enter__ = lambda self: self
        mock_val_proc.__exit__ = MagicMock(return_value=False)

        with (
            patch.object(sr_mod, "llm_call", return_value=mock_result) as mock_call,
            patch("scripts.executor.step_runner.auto_format_test_files", return_value=True),
            patch("scripts.executor.step_runner._run_ruff_fix", return_value=True),
            patch("scripts.executor.step_runner._run_ruff_format", return_value=True),
            patch("subprocess.Popen", return_value=mock_val_proc),
        ):
            success, reqs, prompt_hash, session_id = implement_step(step, "rec-254", step_n=2, total_steps=3)

            # Verify llm_call was called with context_file_path and inline_instruction
            mock_call.assert_called_once()
            call_kwargs = mock_call.call_args[1]
            assert "context_file_path" in call_kwargs
            context_file = call_kwargs["context_file_path"]
            assert "impl" in context_file
            assert "rec-254" in context_file
            assert "inline_instruction" in call_kwargs
            inline_instr = call_kwargs["inline_instruction"]
            assert "Implement step 2/3" in inline_instr
            # Per custom instruction, @context_file_path must be inline in the instruction
            assert "@" in inline_instr
            assert context_file in inline_instr
            assert success == StepOutcome.SUCCESS

    def test_runs_post_fix_ruff_format_before_validate(self) -> None:
        """Regression: validate should see the file after ruff auto-fixes and formatting."""
        step = self._make_step(file="tests/test_execute_recommendation.py")

        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.model = "claude-opus-4.6"
        mock_result.tokens_in = 1000
        mock_result.tokens_out = 0
        mock_result.cost_usd = 1.0

        mock_val_proc = MagicMock()
        mock_val_proc.returncode = 0
        mock_val_proc.communicate.return_value = ("validation passed", "")
        mock_val_proc.__enter__ = lambda self: self
        mock_val_proc.__exit__ = MagicMock(return_value=False)

        call_order: list[str] = []

        with (
            patch("scripts.executor.step_runner.llm_call", return_value=mock_result),
            patch(
                "scripts.executor.step_runner.auto_format_test_files",
                side_effect=lambda _: call_order.append("auto_format") or True,
            ),
            patch(
                "scripts.executor.step_runner._run_ruff_fix",
                side_effect=lambda _: call_order.append("ruff_fix") or True,
            ),
            patch(
                "scripts.executor.step_runner._run_ruff_format",
                side_effect=lambda _: call_order.append("ruff_format") or True,
            ),
            patch(
                "subprocess.Popen",
                side_effect=lambda *args, **kwargs: (
                    (
                        call_order.append("validate")
                        if list(args[0])[0:3] == [sr_mod._PROJECT_PYTHON, "scripts/validate.py", "--pre"]
                        else None
                    )
                    or mock_val_proc
                ),
            ),
        ):
            success, reqs, prompt_hash, session_id = implement_step(step, "rec-001", 1, 1)

        assert success == StepOutcome.SUCCESS
        assert call_order == ["auto_format", "ruff_fix", "ruff_format", "validate"]


class TestGhostStepDetection:
    """Tests for _detect_ghost_step() and ghost step detection in implement_step()."""

    def _make_step(self, title: str = "do something", file: str = "src/mymodule.py", action: str = "modify") -> dict:
        return {
            "n": 1,
            "title": title,
            "file": file,
            "action": action,
            "description": "test step",
            "acceptance": "",
        }

    def test_ghost_step_detected_when_modify_action_with_no_changes(self) -> None:
        """implement_step() detects and fails when modify action has no file changes."""
        step = self._make_step()

        # Mock llm_call to succeed
        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.model = "claude-opus-4.6"
        mock_result.tokens_in = 1000
        mock_result.tokens_out = 0
        mock_result.cost_usd = 1.0

        # Mock subprocess.run to return empty output (git diff --name-only has no changes)
        def subprocess_run_side_effect(*args, **kwargs):
            result = MagicMock()
            result.returncode = 0
            result.stdout = ""
            return result

        with (
            patch("scripts.executor.step_runner.llm_call", return_value=mock_result),
            patch("subprocess.run", side_effect=subprocess_run_side_effect),
            patch("scripts.executor.step_runner.auto_format_test_files") as mock_auto_format,  # Should NOT be called
        ):
            success, reqs, prompt_hash, session_id = implement_step(step, "rec-001", 1, 1)

        assert success == StepOutcome.GHOST_STEP
        assert reqs == 1.0
        mock_auto_format.assert_not_called()

    def test_ghost_step_not_detected_when_files_changed(self) -> None:
        """implement_step() continues when modify action has file changes."""
        step = self._make_step()

        # Mock llm_call to succeed
        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.model = "claude-opus-4.6"
        mock_result.tokens_in = 1000
        mock_result.tokens_out = 0
        mock_result.cost_usd = 1.0

        # Mock subprocess.run to return file list (git diff shows changes)
        def subprocess_run_side_effect(*args, **kwargs):
            result = MagicMock()
            result.returncode = 0
            result.stdout = "src/mymodule.py\n"
            return result

        # Mock validation process
        mock_val_proc = MagicMock()
        mock_val_proc.returncode = 0
        mock_val_proc.communicate.return_value = ("validation passed", "")
        mock_val_proc.__enter__ = lambda self: self
        mock_val_proc.__exit__ = MagicMock(return_value=False)

        with (
            patch("scripts.executor.step_runner.llm_call", return_value=mock_result),
            patch("subprocess.run", side_effect=subprocess_run_side_effect),
            patch("scripts.executor.step_runner.auto_format_test_files", return_value=True),
            patch("scripts.executor.step_runner._run_ruff_fix", return_value=True),
            patch("subprocess.Popen", return_value=mock_val_proc),
        ):
            success, reqs, prompt_hash, session_id = implement_step(step, "rec-001", 1, 1)

        assert success == StepOutcome.SUCCESS
        assert reqs == 1.0

    def test_noop_modify_step_succeeds_when_acceptance_already_passes(self) -> None:
        """implement_step() allows a no-op modify step when acceptance already passes cleanly."""
        step = self._make_step()
        step["acceptance"] = "`python -m pytest tests/test_executor_step_runner.py -q`"

        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.model = "claude-opus-4.6"
        mock_result.tokens_in = 1000
        mock_result.tokens_out = 0
        mock_result.cost_usd = 1.0
        mock_result.session_id = "session-123"

        with (
            patch("scripts.executor.step_runner.llm_call", return_value=mock_result),
            patch("scripts.executor.step_runner._detect_ghost_step", return_value=True),
            patch("scripts.executor.step_runner._list_meaningful_worktree_changes", return_value=[]),
            patch("scripts.executor.step_runner.run_acceptance", return_value=True) as mock_acceptance,
            patch("scripts.executor.step_runner.auto_format_test_files") as mock_auto_format,
        ):
            success, reqs, prompt_hash, session_id = implement_step(step, "rec-001", 1, 1)

        assert success == StepOutcome.SUCCESS
        assert reqs == 1.0
        assert session_id == "session-123"
        mock_acceptance.assert_called_once_with(step["acceptance"])
        mock_auto_format.assert_not_called()

    def test_ghost_step_still_fails_when_other_files_changed(self) -> None:
        """implement_step() still fails if the target file is unchanged but other files changed."""
        step = self._make_step()
        step["acceptance"] = "`python -m pytest tests/test_executor_step_runner.py -q`"

        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.model = "claude-opus-4.6"
        mock_result.tokens_in = 1000
        mock_result.tokens_out = 0
        mock_result.cost_usd = 1.0

        with (
            patch("scripts.executor.step_runner.llm_call", return_value=mock_result),
            patch("scripts.executor.step_runner._detect_ghost_step", return_value=True),
            patch(
                "scripts.executor.step_runner._list_meaningful_worktree_changes",
                return_value=["src/unexpected.py"],
            ),
            patch("scripts.executor.step_runner.run_acceptance") as mock_acceptance,
            patch("scripts.executor.step_runner.auto_format_test_files") as mock_auto_format,
        ):
            success, reqs, prompt_hash, session_id = implement_step(step, "rec-001", 1, 1)

        assert success == StepOutcome.GHOST_STEP
        assert reqs == 1.0
        mock_acceptance.assert_not_called()
        mock_auto_format.assert_not_called()


class TestImplementStepResumeSkip:
    """Tests for resume_session_id skip logic in implement_step()."""

    @staticmethod
    def _make_step() -> dict:
        return {
            "n": 1,
            "title": "Add function",
            "file": "scripts/example.py",
            "action": "modify",
            "description": "Add a helper function",
            "acceptance": "",
            "effort": "XS",
        }

    def test_implement_step_xs_skips_resume(self) -> None:
        """implement_step with effort=XS should pass resume_session_id=None to llm_call."""
        step = self._make_step()

        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.model = "test-model"
        mock_result.tokens_in = 100
        mock_result.tokens_out = 0
        mock_result.cost_usd = 0.0
        mock_result.content = ""
        mock_result.session_id = ""

        with (
            patch("scripts.executor.step_runner.llm_call", return_value=mock_result) as mock_llm,
            patch("scripts.executor.step_runner.auto_format_test_files", return_value=True),
            patch("scripts.executor.step_runner._run_ruff_fix", return_value=True),
            patch("scripts.executor.step_runner.emit_step"),
            patch("scripts.executor.step_runner.emit_transcript"),
            patch("scripts.executor.step_runner.emit_process_event"),
            patch("scripts.executor.step_runner.run_acceptance", return_value=(True, "")),
        ):
            implement_step(step, "rec-xs-001", 1, 1, resume_session_id="fake-session-id", effort="XS")

        # Assert llm_call was called with resume_session_id=None (skip applied)
        assert mock_llm.called
        call_kwargs = mock_llm.call_args.kwargs
        assert call_kwargs.get("resume_session_id") is None

    def test_implement_step_m_keeps_resume(self) -> None:
        """implement_step with effort=M should preserve resume_session_id."""
        step = {**self._make_step(), "effort": "M"}

        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.model = "test-model"
        mock_result.tokens_in = 100
        mock_result.tokens_out = 0
        mock_result.cost_usd = 0.0
        mock_result.content = ""
        mock_result.session_id = ""

        with (
            patch("scripts.executor.step_runner.llm_call", return_value=mock_result) as mock_llm,
            patch("scripts.executor.step_runner.auto_format_test_files", return_value=True),
            patch("scripts.executor.step_runner._run_ruff_fix", return_value=True),
            patch("scripts.executor.step_runner.emit_step"),
            patch("scripts.executor.step_runner.emit_transcript"),
            patch("scripts.executor.step_runner.emit_process_event"),
            patch("scripts.executor.step_runner.run_acceptance", return_value=(True, "")),
        ):
            implement_step(step, "rec-m-001", 1, 1, resume_session_id="my-session", effort="M")

        assert mock_llm.called
        call_kwargs = mock_llm.call_args.kwargs
        assert call_kwargs.get("resume_session_id") == "my-session"
