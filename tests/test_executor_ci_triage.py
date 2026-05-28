"""Unit tests for scripts/executor/ci_triage.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import scripts.executor.ci_triage as triage_mod
from scripts.executor.ci_triage import (
    TriageResult,
    _classify,
    _extract_test_errors,
    _extract_type_errors,
    triage_ci_failure,
)
from scripts.executor.errors import CIFailureCategory


class TestTriageResultDataclass:
    """Tests for the TriageResult dataclass."""

    def test_default_values(self) -> None:
        result = TriageResult(category=CIFailureCategory.LINT, fixed=True)
        assert result.files_changed == []
        assert result.escalate_to_llm is False
        assert result.context_for_llm == ""

    def test_all_fields_stored(self) -> None:
        result = TriageResult(
            category=CIFailureCategory.TEST,
            fixed=False,
            files_changed=["foo.py"],
            escalate_to_llm=True,
            context_for_llm="errors here",
        )
        assert result.category == CIFailureCategory.TEST
        assert result.fixed is False
        assert result.files_changed == ["foo.py"]
        assert result.escalate_to_llm is True
        assert result.context_for_llm == "errors here"


class TestClassify:
    """Tests for _classify()."""

    def test_classifies_lint_ruff(self) -> None:
        output = "scripts/foo.py:10:1: E302 expected 2 blank lines, ruff found 1"
        assert _classify(output) == CIFailureCategory.LINT

    def test_classifies_lint_style_code(self) -> None:
        output = "file.py: E501 line too long (92 > 79)"
        assert _classify(output) == CIFailureCategory.LINT

    def test_classifies_import_with_i_code(self) -> None:
        output = "scripts/foo.py:1:1: I001 Import block is unsorted or unformatted; ruff"
        assert _classify(output) == CIFailureCategory.IMPORT

    def test_classifies_mypy_type_error(self) -> None:
        output = "scripts/foo.py:42: error: Argument 1 has incompatible type; mypy"
        assert _classify(output) == CIFailureCategory.TYPE

    def test_classifies_pytest_failure(self) -> None:
        output = "FAILED tests/test_foo.py::test_bar - AssertionError\npytest"
        assert _classify(output) == CIFailureCategory.TEST

    def test_classifies_test_session_start(self) -> None:
        output = "====== test session starts ======\n1 failed"
        assert _classify(output) == CIFailureCategory.TEST

    def test_classifies_unknown(self) -> None:
        output = "Some completely unrecognised error from terraform or something"
        assert _classify(output) == CIFailureCategory.UNKNOWN

    def test_import_takes_priority_over_lint_when_i_code(self) -> None:
        # Output has both ruff and I-code — should be classified as IMPORT
        output = "ruff check failed: I001 import order; E302 blank lines"
        result = _classify(output)
        assert result == CIFailureCategory.IMPORT


class TestTriageCiFailure:
    """Tests for triage_ci_failure() — integration over classify + fix."""

    def test_returns_triage_result_for_unknown(self) -> None:
        result = triage_ci_failure("Some random CI error with no recognisable pattern here")
        assert isinstance(result, TriageResult)
        assert result.category == CIFailureCategory.UNKNOWN
        assert result.escalate_to_llm is True
        assert result.fixed is False

    def test_escalates_test_failures_with_context(self) -> None:
        output = "pytest\nFAILED tests/test_foo.py::test_bar - AssertionError: expected 1 got 2\n1 failed"
        result = triage_ci_failure(output)
        assert result.category == CIFailureCategory.TEST
        assert result.escalate_to_llm is True
        assert "test_foo.py" in result.context_for_llm or "FAILED" in result.context_for_llm

    def test_escalates_type_errors_with_context(self) -> None:
        output = "mypy\nscripts/foo.py:10: error: Incompatible types in assignment"
        result = triage_ci_failure(output)
        assert result.category == CIFailureCategory.TYPE
        assert result.escalate_to_llm is True
        assert "error" in result.context_for_llm.lower()

    def test_lint_fix_with_ruff_success(self) -> None:
        lint_output = "ruff\nscripts/foo.py:1:1: E302 expected 2 blank lines"
        before_diff = {"scripts/old.py"}
        after_diff = {"scripts/old.py", "scripts/foo.py"}

        mock_ruff = MagicMock(returncode=0, stdout="", stderr="")

        with (
            patch("shutil.which", return_value="/usr/bin/ruff"),
            patch("subprocess.run", return_value=mock_ruff),
            patch.object(triage_mod, "_get_tracked_changes", side_effect=[before_diff, after_diff]),
        ):
            result = triage_ci_failure(lint_output)

        assert result.category == CIFailureCategory.LINT
        assert result.fixed is True
        assert "scripts/foo.py" in result.files_changed
        assert result.escalate_to_llm is False

    def test_lint_fix_with_ruff_failure(self) -> None:
        lint_output = "ruff\nE302 error"
        mock_ruff = MagicMock(returncode=1, stderr="could not fix", stdout="")

        with (
            patch("shutil.which", return_value="/usr/bin/ruff"),
            patch("subprocess.run", return_value=mock_ruff),
            patch.object(triage_mod, "_get_tracked_changes", return_value=set()),
        ):
            result = triage_ci_failure(lint_output)

        assert result.category == CIFailureCategory.LINT
        assert result.fixed is False
        assert result.escalate_to_llm is True

    def test_import_fix_calls_ruff_select_i(self) -> None:
        import_output = "ruff\nI001 import order"
        captured_cmds: list = []

        def track_run(*args, **kwargs):
            if args:
                captured_cmds.append(list(args[0]))
            return MagicMock(returncode=0, stdout="", stderr="")

        with (
            patch("shutil.which", return_value="/usr/bin/ruff"),
            patch("subprocess.run", side_effect=track_run),
            patch.object(triage_mod, "_get_tracked_changes", return_value=set()),
        ):
            triage_ci_failure(import_output)

        ruff_calls = [c for c in captured_cmds if "ruff" in " ".join(str(x) for x in c)]
        assert any("--select" in " ".join(str(x) for x in c) and "I" in c for c in ruff_calls)

    def test_unknown_context_is_capped(self) -> None:
        long_output = "x" * 10000
        result = triage_ci_failure(long_output)
        assert result.category == CIFailureCategory.UNKNOWN
        assert len(result.context_for_llm) <= 3200  # 3000 + small prefix overhead

    def test_lint_escalates_when_ruff_not_found(self) -> None:
        lint_output = "ruff E302 error"
        with (
            patch("shutil.which", return_value=None),
            patch("scripts.executor.ci_triage._try_ruff_via_python", return_value=False),
        ):
            result = triage_ci_failure(lint_output)
        assert result.category == CIFailureCategory.LINT
        assert result.escalate_to_llm is True
        assert result.fixed is False


class TestExtractTypeErrors:
    """Tests for _extract_type_errors()."""

    def test_extracts_mypy_error_lines(self) -> None:
        output = (
            "scripts/foo.py:10: error: Arg has wrong type\n"
            "scripts/bar.py:20: error: Return type incompatible\n"
            "Some other line\n"
        )
        result = _extract_type_errors(output)
        assert "scripts/foo.py:10: error" in result
        assert "scripts/bar.py:20: error" in result
        assert "Some other line" not in result

    def test_caps_at_2000_chars(self) -> None:
        output = "\n".join(f"f.py:{i}: error: long error message" + "x" * 50 for i in range(100))
        result = _extract_type_errors(output)
        assert len(result) <= 2000

    def test_returns_empty_for_no_errors(self) -> None:
        result = _extract_type_errors("some clean output without errors")
        assert result == ""


class TestExtractTestErrors:
    """Tests for _extract_test_errors()."""

    def test_extracts_failed_lines(self) -> None:
        output = "collected 10 items\nFAILED tests/test_foo.py::test_bar - AssertionError\nPASSED tests/test_foo.py::test_ok\n"
        result = _extract_test_errors(output)
        assert "FAILED tests/test_foo.py::test_bar" in result
        assert "PASSED" not in result

    def test_extracts_assertion_error_lines(self) -> None:
        output = "    assert x == 1\nAssertionError: assert 2 == 1\n"
        result = _extract_test_errors(output)
        assert "AssertionError" in result

    def test_caps_at_2000_chars(self) -> None:
        output = "\n".join(f"FAILED tests/test_{i}.py::test - AssertionError" for i in range(100))
        result = _extract_test_errors(output)
        assert len(result) <= 2000

    def test_returns_empty_for_clean_output(self) -> None:
        result = _extract_test_errors("All tests passed.\n10 passed in 1.23s")
        assert result == ""
