"""Tests for run_lint_checks() -- VTS-18 whole-tree default lint targets (audit validate-test-suite-4df4d48)."""

from unittest.mock import MagicMock, patch

from scripts.checks._scaffolding import run_lint_checks


class TestRunLintChecksWholeTreeTargets:
    """VTS-18: run_lint_checks(failed, files=None) (the whole-tree/full-tier default) must
    include scripts/ alongside src/ and tests/ in its ruff check + ruff format --check targets."""

    def test_whole_tree_default_includes_scripts(self) -> None:
        mock_result = MagicMock(returncode=0)
        with patch("scripts.checks._common.run", return_value=mock_result) as mock_run:
            failed: list[str] = []
            run_lint_checks(failed, files=None)

        assert mock_run.call_count == 2
        for call in mock_run.call_args_list:
            cmd = call.args[0]
            assert "scripts/" in cmd

    def test_whole_tree_default_still_includes_src_and_tests(self) -> None:
        mock_result = MagicMock(returncode=0)
        with patch("scripts.checks._common.run", return_value=mock_result) as mock_run:
            failed: list[str] = []
            run_lint_checks(failed, files=None)

        for call in mock_run.call_args_list:
            cmd = call.args[0]
            assert "src/" in cmd
            assert "tests/" in cmd

    def test_ruff_check_and_format_check_both_invoked(self) -> None:
        mock_result = MagicMock(returncode=0)
        with patch("scripts.checks._common.run", return_value=mock_result) as mock_run:
            failed: list[str] = []
            run_lint_checks(failed, files=None)

        commands = [call.args[0] for call in mock_run.call_args_list]
        assert any("check" in cmd for cmd in commands)
        assert any("format" in cmd for cmd in commands)

    def test_no_failure_appended_when_ruff_passes(self) -> None:
        mock_result = MagicMock(returncode=0)
        with patch("scripts.checks._common.run", return_value=mock_result):
            failed: list[str] = []
            run_lint_checks(failed, files=None)
        assert failed == []

    def test_explicit_files_scope_is_unaffected(self) -> None:
        """files=[...] (the --pre diff-scoped path) must NOT gain scripts/ -- only the
        files-is-None whole-tree default does."""
        mock_result = MagicMock(returncode=0)
        with patch("scripts.checks._common.run", return_value=mock_result) as mock_run:
            failed: list[str] = []
            run_lint_checks(failed, files=["scripts/checks/_scaffolding.py"])

        for call in mock_run.call_args_list:
            cmd = call.args[0]
            assert cmd[-1] == "scripts/checks/_scaffolding.py"
            assert "scripts/" not in cmd

    def test_no_op_when_files_is_empty_list(self) -> None:
        with patch("scripts.checks._common.run") as mock_run:
            failed: list[str] = []
            run_lint_checks(failed, files=[])

        mock_run.assert_not_called()
        assert failed == []
