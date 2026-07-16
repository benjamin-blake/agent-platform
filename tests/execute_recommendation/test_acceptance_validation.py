"""Acceptance-command lint and feasibility validation tests (rec-2709 Wave 2)."""

from unittest.mock import MagicMock, patch

from scripts.execute_recommendation import (
    AcceptanceFeasibility,
    lint_acceptance_command,
    validate_acceptance_feasibility,
)


@patch("shutil.which", return_value=None)
class TestLintAcceptanceCommand:
    """Test acceptance command validation."""

    def test_empty_command_is_valid(self, mock_shutil):
        """Empty or whitespace-only commands should be valid."""
        ok, error = lint_acceptance_command("")
        assert ok is True
        assert error is None

        ok, error = lint_acceptance_command("   ")
        assert ok is True
        assert error is None

    def test_reject_python_c_one_liner(self, mock_shutil):
        """Reject python -c one-liners."""
        cmd = 'python -c "import sys; print(sys.version)"'
        ok, error = lint_acceptance_command(cmd)
        assert ok is False
        assert error is not None
        assert "python -c" in error.lower()

    def test_reject_python_m_with_quotes(self, mock_shutil):
        """Reject python -m patterns with immediate quotes."""
        cmd = 'python -m "pytest"'
        ok, error = lint_acceptance_command(cmd)
        assert ok is False
        assert error is not None
        assert "python" in error.lower()

    def test_accept_valid_pytest_command(self, mock_shutil):
        """Accept valid pytest commands without quotes."""
        cmd = "python -m pytest tests/test_file.py::TestClass -q"
        ok, error = lint_acceptance_command(cmd)
        assert ok is True
        assert error is None

    def test_accept_valid_grep_command(self, mock_shutil):
        """Accept valid single-pattern grep commands."""
        cmd = "grep -q 'def function_name' src/file.py"
        ok, error = lint_acceptance_command(cmd)
        assert ok is True
        assert error is None

    def test_warn_multi_word_grep_pattern(self, mock_shutil, capsys):
        """Detect and warn about multi-word grep patterns with regex operators."""
        cmd = "grep -E 'word1.*word2' file.py"
        ok, error = lint_acceptance_command(cmd)
        assert ok is True
        captured = capsys.readouterr()
        assert "WARNING" in captured.out or "Multi-word" in captured.out

    def test_warn_grep_with_pipe_operator(self, mock_shutil, capsys):
        """Detect multi-word grep with pipe operator."""
        cmd = "grep -E 'pattern1|pattern2' file.py"
        ok, error = lint_acceptance_command(cmd)
        assert ok is True
        captured = capsys.readouterr()
        if "grep" in cmd:
            assert "WARNING" in captured.out or len(captured.out) > 0

    def test_reject_invalid_bash_syntax(self, mock_shutil):
        """Reject commands with invalid bash syntax."""
        cmd = "grep -q 'test' file.py &&& invalid"
        # Since shutil.which is None, this will return True!
        # I need to mock shutil.which to return a path and subprocess.run to fail
        with patch("shutil.which", return_value="/bin/bash"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=1, stderr="syntax error")
                ok, error = lint_acceptance_command(cmd)
                assert ok is False
                assert error is not None
                assert "syntax" in error.lower() or "bash" in error.lower()

    def test_accept_valid_bash_syntax(self, mock_shutil):
        """Accept commands with valid bash syntax."""
        cmd = "grep -q 'test' file.py && echo 'found'"
        ok, error = lint_acceptance_command(cmd)
        assert ok is True
        assert error is None


@patch("shutil.which", return_value=None)
class TestValidateAcceptanceFeasibility:
    """Test acceptance command feasibility validation."""

    def test_pytest_target_nonexistent_file(self, mock_shutil):
        """Test that pytest commands are FEASIBLE even when test file doesn't exist yet."""
        acceptance = "python -m pytest tests/test_pysr_factory.py::TestPySRFactory -q"

        with patch("pathlib.Path.exists", return_value=False):
            feasibility, message = validate_acceptance_feasibility(acceptance)

        assert feasibility == AcceptanceFeasibility.FEASIBLE, (
            "Expected FEASIBLE for pytest command when test file doesn't exist yet"
        )
        assert message == "", f"Expected empty message for FEASIBLE result, got: {message}"

    def test_infeasible_handler_updates_status_with_dict(self, mock_shutil):
        """Test INFEASIBLE exit path in _execute_recommendation_inner updates status with dict."""
        from scripts.execute_recommendation import _execute_recommendation_inner

        with patch("scripts.execute_recommendation.ensure_feature_branch", return_value=True):
            with patch("scripts.execute_recommendation.load_checkpoint", return_value=None):
                with patch(
                    "scripts.execute_recommendation.load_recommendation",
                    return_value={"id": "rec-test", "acceptance": "grep file.py"},
                ):
                    with patch(
                        "scripts.execute_recommendation.validate_acceptance_feasibility",
                        return_value=(
                            AcceptanceFeasibility.INFEASIBLE,
                            "grep target file does not exist: src/no.py",
                        ),
                    ):
                        with patch("scripts.execute_recommendation.is_eligible", return_value=True):
                            with patch("scripts.execute_recommendation.write_run_summary"):
                                with patch("scripts.execute_recommendation.update_recommendation_status") as mock_update:
                                    result = _execute_recommendation_inner("rec-test", None, True)
                                    assert result is False, "Expected False when acceptance is INFEASIBLE"
                                    mock_update.assert_called_once_with("rec-test", {"status": "failed"})

    def test_accept_complex_valid_command(self, mock_shutil):
        """Accept complex but valid multi-command bash."""
        cmd = "git status --short && python -m pytest tests/ -q"
        ok, error = lint_acceptance_command(cmd)
        assert ok is True
        assert error is None

    def test_error_message_includes_command(self, mock_shutil):
        """Error messages should include the problematic command."""
        cmd = 'python -c "bad"'
        # Re-patch within method to simulate bash failure
        with (
            patch("shutil.which", return_value="/bin/bash"),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=1, stderr="syntax error")
            ok, error = lint_acceptance_command(cmd)
            assert ok is False
            assert cmd in error

    def test_rejection_returns_false_tuple(self, mock_shutil):
        """Rejection should return (False, error_msg) tuple."""
        cmd = "invalid &&& bash"
        # Re-patch within method to simulate bash failure
        with (
            patch("shutil.which", return_value="/bin/bash"),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=1, stderr="syntax error")
            ok, error = lint_acceptance_command(cmd)
            assert isinstance(ok, bool)
            assert ok is False
            assert isinstance(error, str)

    def test_acceptance_returns_true_tuple(self, mock_shutil):
        """Acceptance should return (True, None) tuple."""
        cmd = "grep -q 'test' file.py"
        ok, error = lint_acceptance_command(cmd)
        assert isinstance(ok, bool)
        assert ok is True
        assert error is None

    def test_warn_grep_q_co_location(self, mock_shutil, capsys):
        """Detect multi-word grep with -q flag and co-location pattern."""
        cmd = "grep -q 'word1.*word2' file.py"
        ok, error = lint_acceptance_command(cmd)
        assert ok is True
        captured = capsys.readouterr()
        assert "WARNING" in captured.out or "Multi-word" in captured.out

    def test_warn_grep_qi_co_location(self, mock_shutil, capsys):
        """Detect multi-word grep with -qi flags and co-location pattern."""
        cmd = "grep -qi 'word1|word2' file.py"
        ok, error = lint_acceptance_command(cmd)
        assert ok is True
        captured = capsys.readouterr()
        assert "WARNING" in captured.out or "Multi-word" in captured.out

    def test_warn_grep_qE_co_location(self, mock_shutil, capsys):
        """Detect multi-word grep with -qE flags and co-location pattern."""
        cmd = "grep -qE 'pattern1.*pattern2' file.py"
        ok, error = lint_acceptance_command(cmd)
        assert ok is True
        captured = capsys.readouterr()
        assert "WARNING" in captured.out or "Multi-word" in captured.out

    def test_backtick_delimited_with_and_operator_real_file(self, mock_shutil):
        """Test backtick-delimited acceptance with && operator and real file resolves to FEASIBLE."""
        acceptance = "`grep -q 'import json' scripts/execute_recommendation.py && echo 'ok'`"

        feasibility, message = validate_acceptance_feasibility(acceptance)

        assert feasibility == AcceptanceFeasibility.FEASIBLE, (
            f"Expected FEASIBLE for backtick-delimited command with &&, got: {feasibility}"
        )
        assert message == "", f"Expected empty message for FEASIBLE result, got: {message}"


class TestValidateAcceptanceFeasibilityActionAware:
    """Regression tests for action-aware validate_acceptance_feasibility() (rec-461, rec-401)."""

    def test_grep_nonexistent_file_create_action_is_feasible(self):
        """Pattern 1: grep on a nonexistent file is FEASIBLE when action='create'."""
        with patch("pathlib.Path.exists", return_value=False):
            feasibility, message = validate_acceptance_feasibility(
                "grep -q 'def my_func' nonexistent.md",
                action="create",
            )
        assert feasibility == AcceptanceFeasibility.FEASIBLE
        assert message == ""

    def test_grep_nonexistent_file_no_action_is_infeasible(self):
        """Pattern 1: grep on a nonexistent file is INFEASIBLE when no action is given."""
        with patch("pathlib.Path.exists", return_value=False):
            feasibility, message = validate_acceptance_feasibility(
                "grep -q 'def my_func' nonexistent.md",
            )
        assert feasibility == AcceptanceFeasibility.INFEASIBLE
        assert "nonexistent.md" in message

    def test_python_m_nonexistent_module_is_feasible(self):
        """Pattern 3 (rec-401): python -m for a nonexistent module is FEASIBLE (module-creation recs)."""
        with patch("pathlib.Path.exists", return_value=False):
            feasibility, message = validate_acceptance_feasibility(
                "python -m scripts.new_nonexistent_module",
            )
        assert feasibility == AcceptanceFeasibility.FEASIBLE
        assert message == ""

    def test_test_f_nonexistent_file_create_action_is_feasible(self):
        """test -f on a nonexistent file is FEASIBLE when action='create' (no Pattern 1 match, falls through)."""
        with patch("pathlib.Path.exists", return_value=False):
            feasibility, message = validate_acceptance_feasibility(
                "test -f nonexistent.md",
                action="create",
            )
        assert feasibility == AcceptanceFeasibility.FEASIBLE
