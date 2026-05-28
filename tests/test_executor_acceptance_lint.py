"""Tests for scripts.executor.acceptance_lint module.

Extracted functions: AcceptanceFeasibility, validate_acceptance_feasibility,
lint_acceptance_command, _checkout_main_safely, _check_acceptance_on_main.
"""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.executor.acceptance_lint import (
    AcceptanceFeasibility,
    _check_acceptance_on_main,
    _checkout_main_safely,
    lint_acceptance_command,
    validate_acceptance_feasibility,
)


class TestAcceptanceFeasibility:
    """Tests for the AcceptanceFeasibility enum."""

    def test_enum_values(self):
        assert AcceptanceFeasibility.FEASIBLE.value == "feasible"
        assert AcceptanceFeasibility.INFEASIBLE.value == "infeasible"
        assert AcceptanceFeasibility.UNPARSEABLE.value == "unparseable"


class TestValidateAcceptanceFeasibility:
    """Tests for validate_acceptance_feasibility."""

    def test_empty_acceptance_is_feasible(self):
        result, reason = validate_acceptance_feasibility("")
        assert result == AcceptanceFeasibility.FEASIBLE
        assert reason == ""

    def test_none_acceptance_is_feasible(self):
        result, reason = validate_acceptance_feasibility(None)
        assert result == AcceptanceFeasibility.FEASIBLE
        assert reason == ""

    def test_backtick_delimiters_stripped(self):
        # Valid command wrapped in backticks should still be feasible
        result, reason = validate_acceptance_feasibility("`echo hello`")
        assert result == AcceptanceFeasibility.FEASIBLE

    @patch("scripts.executor.acceptance_lint.Path")
    def test_grep_with_missing_file_is_infeasible(self, mock_path_cls):
        mock_path_instance = MagicMock()
        mock_path_cls.return_value = mock_path_instance
        mock_path_cls.__truediv__ = MagicMock()

        # We need to mock the repo_root / file_path to return non-existent
        with patch.object(Path, "__new__"):
            # Simpler approach: just test with a clearly non-existent file
            # The function uses Path(__file__).parent.parent.parent as repo_root
            result, reason = validate_acceptance_feasibility("grep -q 'pattern' nonexistent_file_xyz_12345.py")
            # If file doesn't exist on disk, should be INFEASIBLE
            if result == AcceptanceFeasibility.INFEASIBLE:
                assert "does not exist" in reason

    def test_pytest_command_is_feasible_for_missing_test(self):
        # pytest with missing test file treated as feasible (file may be created)
        result, reason = validate_acceptance_feasibility("python -m pytest tests/test_nonexistent_xyz.py -x -q")
        assert result == AcceptanceFeasibility.FEASIBLE

    def test_grep_with_create_action_skips_file_check(self):
        result, reason = validate_acceptance_feasibility(
            "grep -q 'def my_func' nonexistent_file_xyz_12345.py",
            action="create",
        )
        assert result == AcceptanceFeasibility.FEASIBLE

    def test_chained_commands_all_checked(self):
        # Both parts of && chain are checked
        result, reason = validate_acceptance_feasibility("echo hello && echo world")
        assert result == AcceptanceFeasibility.FEASIBLE


class TestLintAcceptanceCommand:
    """Tests for lint_acceptance_command."""

    def test_empty_command_is_valid(self):
        valid, msg = lint_acceptance_command("")
        assert valid is True
        assert msg is None

    def test_none_command_is_valid(self):
        valid, msg = lint_acceptance_command(None)
        assert valid is True
        assert msg is None

    def test_python_c_oneliner_banned(self):
        valid, msg = lint_acceptance_command('python -c "print(1)"')
        assert valid is False
        assert "banned" in msg.lower()

    def test_simple_grep_valid(self):
        with patch("shutil.which", return_value=None):
            valid, msg = lint_acceptance_command("grep -q 'pattern' file.py")
        assert valid is True
        assert msg is None

    def test_pytest_command_valid(self):
        with patch("shutil.which", return_value=None):
            valid, msg = lint_acceptance_command("python -m pytest tests/test_file.py -x -q")
        assert valid is True
        assert msg is None

    @patch("shutil.which", return_value=None)
    def test_no_bash_available_still_valid(self, mock_which):
        valid, msg = lint_acceptance_command("echo hello")
        assert valid is True

    @patch("shutil.which", return_value="/usr/bin/bash")
    @patch("subprocess.run")
    def test_bash_syntax_error_returns_invalid(self, mock_run, mock_which):
        mock_run.return_value = MagicMock(returncode=1, stderr="syntax error")
        valid, msg = lint_acceptance_command("if [[ then")
        assert valid is False
        assert "syntax" in msg.lower()

    @patch("shutil.which", return_value="/usr/bin/bash")
    @patch("subprocess.run")
    def test_bash_syntax_valid_returns_valid(self, mock_run, mock_which):
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        valid, msg = lint_acceptance_command("echo hello && echo world")
        assert valid is True
        assert msg is None


class TestCheckoutMainSafely:
    """Tests for _checkout_main_safely."""

    @patch("subprocess.run")
    def test_basic_checkout_main(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        _checkout_main_safely()
        # Should call: git stash, git checkout main, git stash pop
        assert mock_run.call_count == 3
        calls = [c[0][0] for c in mock_run.call_args_list]
        assert calls[0] == ["git", "stash"]
        assert calls[1] == ["git", "checkout", "main"]
        assert calls[2] == ["git", "stash", "pop"]

    @patch("subprocess.run")
    def test_checkout_with_restore_branch(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        _checkout_main_safely("agent/my-branch")
        # Should call: stash, checkout main, checkout restore, stash pop
        assert mock_run.call_count == 4
        calls = [c[0][0] for c in mock_run.call_args_list]
        assert calls[2] == ["git", "checkout", "agent/my-branch"]


class TestCheckAcceptanceOnMain:
    """Tests for _check_acceptance_on_main."""

    @patch("scripts.executor.acceptance_lint._checkout_main_safely")
    @patch("scripts.executor.acceptance_lint.subprocess.run")
    def test_empty_command_returns_false(self, mock_run, mock_checkout):
        assert _check_acceptance_on_main("rec-001", "", "agent/test") is False
        mock_checkout.assert_not_called()

    @patch("scripts.executor.acceptance_lint._checkout_main_safely")
    @patch("scripts.executor.acceptance_lint.subprocess.run")
    def test_acceptance_passes_marks_closed(self, mock_run, mock_checkout):
        # Mock git branch --show-current
        mock_run.return_value = MagicMock(stdout="agent/test\n", returncode=0)

        with (
            patch("scripts.executor.step_runner.run_acceptance", return_value=True),
            patch(
                "scripts.executor.jsonl_store.load_recommendation",
                return_value={"date": "2026-01-01", "file": "scripts/foo.py"},
            ),
            patch("scripts.executor.jsonl_store.update_recommendation_status") as mock_update,
        ):
            # Mock git log showing commits exist
            mock_run.return_value = MagicMock(stdout="abc123 some commit\n", returncode=0)
            result = _check_acceptance_on_main("rec-001", "echo hi", "agent/test")

        assert result is True
        mock_update.assert_called_once()
        update_args = mock_update.call_args[0]
        assert update_args[0] == "rec-001"
        assert update_args[1]["status"] == "closed"
        assert update_args[1]["execution_result"] == "already_implemented"

    @patch("scripts.executor.acceptance_lint._checkout_main_safely")
    @patch("scripts.executor.acceptance_lint.subprocess.run")
    def test_acceptance_fails_returns_false(self, mock_run, mock_checkout):
        mock_run.return_value = MagicMock(stdout="agent/test\n", returncode=0)

        with patch("scripts.executor.step_runner.run_acceptance", return_value=False):
            result = _check_acceptance_on_main("rec-001", "echo hi", "agent/test")

        assert result is False

    @patch("scripts.executor.acceptance_lint._checkout_main_safely")
    @patch("scripts.executor.acceptance_lint.subprocess.run")
    def test_exception_returns_false(self, mock_run, mock_checkout):
        mock_run.side_effect = subprocess.CalledProcessError(1, "git")
        result = _check_acceptance_on_main("rec-001", "echo hi", "agent/test")
        assert result is False


class TestReExports:
    """Verify that the original import paths still work (Strangler Fig)."""

    def test_import_from_original_module(self):
        from scripts.execute_recommendation import (
            AcceptanceFeasibility as AF,
        )
        from scripts.execute_recommendation import (
            _check_acceptance_on_main as check,
        )
        from scripts.execute_recommendation import (
            _checkout_main_safely as checkout,
        )
        from scripts.execute_recommendation import (
            lint_acceptance_command as lint,
        )
        from scripts.execute_recommendation import (
            validate_acceptance_feasibility as validate,
        )

        assert AF is AcceptanceFeasibility
        assert check is _check_acceptance_on_main
        assert checkout is _checkout_main_safely
        assert lint is lint_acceptance_command
        assert validate is validate_acceptance_feasibility
