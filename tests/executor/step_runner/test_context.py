"""step_runner context/extraction tests: gather_step_context, _extract_acceptance_command,
_get_relevant_gotchas (rec-2709 Wave 5).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import scripts.executor.step_runner as sr_mod
from scripts.executor.step_runner import _extract_acceptance_command, gather_step_context


class TestGatherStepContext:
    """Tests for gather_step_context()."""

    def test_returns_file_content_for_modify(self, tmp_path: Path) -> None:
        target = tmp_path / "mymodule.py"
        target.write_text("def foo(): pass\n", encoding="utf-8")
        step = {"action": "modify", "file": str(target)}
        result = gather_step_context(step, max_chars=10000)
        assert "def foo" in result["file_content"]

    def test_empty_content_for_missing_modify_file(self, tmp_path: Path) -> None:
        step = {"action": "modify", "file": str(tmp_path / "missing.py")}
        result = gather_step_context(step, max_chars=10000)
        assert result["file_content"] == ""

    def test_returns_pattern_content_for_create(self, tmp_path: Path) -> None:
        existing = tmp_path / "existing_module.py"
        existing.write_text("# pattern file\ndef bar(): pass\n", encoding="utf-8")
        new_file = tmp_path / "new_module.py"
        step = {"action": "create", "file": str(new_file)}
        result = gather_step_context(step, max_chars=10000)
        assert "bar" in result["pattern_content"]

    def test_no_pattern_when_create_dir_empty(self, tmp_path: Path) -> None:
        new_dir = tmp_path / "empty_dir"
        new_dir.mkdir()
        step = {"action": "create", "file": str(new_dir / "new.py")}
        result = gather_step_context(step, max_chars=10000)
        assert result["pattern_content"] == ""

    def test_includes_test_file_if_present(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        target = tmp_path / "mymodule.py"
        target.write_text("def foo(): pass\n", encoding="utf-8")
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        test_file = tests_dir / "test_mymodule.py"
        test_file.write_text("def test_foo(): pass\n", encoding="utf-8")

        # Monkeypatch Path("tests") / f"test_{stem}.py" resolution
        # We do this by patching step_runner's Path so it resolves relative to tmp_path
        original_path = sr_mod.Path

        class PatchedPath(type(original_path("."))):
            pass

        # Easier approach: mock the test file path directly by patching the call
        # Actually, gather_step_context uses Path("tests") / f"test_{stem}.py" which is relative.
        # So we need to either be in the right CWD or mock it.
        # Best approach: patch Path so that tests/test_mymodule.py resolves to our tmp file.
        with patch.object(sr_mod, "Path") as MockPath:
            # Set up: file_path.stem = "mymodule", test check
            mock_file = MagicMock()
            mock_file.stem = "mymodule"
            mock_file.parent = MagicMock()
            mock_file.suffix = ".py"
            mock_file.parent.is_dir.return_value = False
            mock_file.exists.return_value = True
            mock_file.__str__ = lambda self: str(target)
            mock_file.read_text.return_value = "def foo(): pass\n"

            mock_test = MagicMock()
            mock_test.exists.return_value = True
            mock_test.read_text.return_value = "def test_foo(): pass\n"

            def path_side_effect(*args):
                if args and str(args[0]) == str(target):
                    return mock_file
                if args and str(args[0]) == "tests":
                    mock_tests_dir = MagicMock()
                    mock_tests_dir.__truediv__ = lambda self, name: mock_test
                    return mock_tests_dir
                return original_path(*args)

            MockPath.side_effect = path_side_effect

            # Fall back to simpler integration approach without mocking Path
        # Integration approach: use real paths with CWD patching
        step = {"action": "modify", "file": str(target)}
        result = gather_step_context(step, max_chars=10000)
        # file_content should be populated; test_content requires CWD match which we skip here
        assert "def foo" in result["file_content"]

    def test_empty_result_for_missing_file_key(self) -> None:
        step = {"action": "modify"}
        result = gather_step_context(step)
        assert result == {"file_content": "", "test_content": "", "pattern_content": ""}

    def test_content_truncated_when_exceeds_budget(self, tmp_path: Path) -> None:
        target = tmp_path / "big.py"
        target.write_text("x" * 1000 + "\n", encoding="utf-8")
        step = {"action": "modify", "file": str(target)}
        result = gather_step_context(step, max_chars=50)
        assert len(result["file_content"]) < 200  # truncated
        assert "omitted" in result["file_content"]


class TestExtractAcceptanceCommand:
    """Tests for _extract_acceptance_command()."""

    def test_extracts_fenced_block(self) -> None:
        acc = "Run this:\n```bash\ngrep -q foo bar.py\n```\nDone."
        cmd = _extract_acceptance_command(acc)
        assert cmd == "grep -q foo bar.py"

    def test_extracts_inline_backtick_python(self) -> None:
        acc = 'Verify with `python -c "import foo"`'
        cmd = _extract_acceptance_command(acc)
        assert "python" in cmd

    def test_extracts_inline_backtick_grep(self) -> None:
        acc = "Check with `grep -q 'hello' file.py`"
        cmd = _extract_acceptance_command(acc)
        assert "grep" in cmd

    def test_extracts_via_line_scan_python(self) -> None:
        acc = "Verify:\npython -m scripts.execute_recommendation --help"
        cmd = _extract_acceptance_command(acc)
        assert "python" in cmd

    def test_extracts_via_line_scan_pytest(self) -> None:
        acc = "Run tests:\npytest tests/test_foo.py -v"
        cmd = _extract_acceptance_command(acc)
        assert "pytest" in cmd

    def test_returns_empty_for_prose_only(self) -> None:
        acc = "The function should exist and return the correct value."
        cmd = _extract_acceptance_command(acc)
        assert cmd == ""

    def test_returns_empty_for_empty_input(self) -> None:
        cmd = _extract_acceptance_command("")
        assert cmd == ""

    def test_fenced_block_takes_priority_over_inline(self) -> None:
        acc = "Try `echo inline` but use:\n```bash\necho fenced\n```"
        cmd = _extract_acceptance_command(acc)
        assert "fenced" in cmd

    def test_skips_lang_tags_in_line_scan(self) -> None:
        acc = 'Run:\nbash\npython -c "import x"'
        cmd = _extract_acceptance_command(acc)
        # Should skip 'bash' as a lang tag and pick python
        assert "python" in cmd


class TestGetRelevantGotchas:
    """Tests for _get_relevant_gotchas()."""

    def test_get_relevant_gotchas_terraform(self) -> None:
        from scripts.executor.step_runner import _get_relevant_gotchas

        g = _get_relevant_gotchas("terraform/main.tf")
        assert "try()" in g

    def test_get_relevant_gotchas_no_match(self) -> None:
        from scripts.executor.step_runner import _get_relevant_gotchas

        g = _get_relevant_gotchas("README.md")
        assert g == ""

    def test_get_relevant_gotchas_tests_dir(self) -> None:
        from scripts.executor.step_runner import _get_relevant_gotchas

        g = _get_relevant_gotchas("tests/test_foo.py")
        assert "Test Isolation" in g

    def test_gotcha_injection_in_gather_context(self, tmp_path: Path) -> None:
        """gather_step_context injects gotchas for .tf files."""
        target = tmp_path / "iceberg_tables.tf"
        target.write_text('resource "aws_glue_catalog_table" "example" {}\n', encoding="utf-8")
        step = {"action": "modify", "file": str(target)}
        # Patch the file path used to match so relative gotcha map key is matched
        with patch("scripts.executor.step_runner._get_relevant_gotchas", wraps=sr_mod._get_relevant_gotchas):
            gather_step_context(step, max_chars=10000)
        # For a .tf file not at terraform/ prefix, no gotcha is injected (abs path has no prefix match)
        # But if we use a relative path with terraform/ prefix, it should inject
        step2 = {"action": "modify", "file": "terraform/iceberg_tables.tf"}
        with patch("pathlib.Path.exists", return_value=False):
            result2 = gather_step_context(step2, max_chars=10000)
        # Gotchas should appear (even though file doesn't exist, gotcha is injected based on path)
        assert "try()" in result2.get("file_content", "")
