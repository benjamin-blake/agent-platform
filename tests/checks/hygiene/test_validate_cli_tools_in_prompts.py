"""Tests for validate_cli_tools_in_prompts()."""

from pathlib import Path
from unittest.mock import patch

from scripts.checks.hygiene.validate_cli_tools_in_prompts import validate_cli_tools_in_prompts


class TestValidateCliToolsInPrompts:
    """Tests for validate_cli_tools_in_prompts()."""

    def test_passes_when_all_tools_in_path(self, tmp_path: Path) -> None:
        """No failures when all referenced tools are found in PATH."""
        prompt_dir = tmp_path / ".github" / "prompts"
        prompt_dir.mkdir(parents=True)
        md = prompt_dir / "test.prompt.md"
        md.write_text("```bash\naws sts get-caller-identity\n```\n", encoding="utf-8")

        with (
            patch("scripts.checks.hygiene.validate_cli_tools_in_prompts._KNOWN_CLI_TOOLS", {"aws"}),
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks.hygiene.validate_cli_tools_in_prompts.shutil.which", return_value="/usr/bin/aws"),
        ):
            failed: list[str] = []
            validate_cli_tools_in_prompts(failed)

        assert failed == []

    def test_fails_when_tool_not_in_path(self, tmp_path: Path) -> None:
        """Appends to failed list when a referenced tool is not in PATH."""
        prompt_dir = tmp_path / ".github" / "prompts"
        prompt_dir.mkdir(parents=True)
        md = prompt_dir / "test.prompt.md"
        md.write_text("```bash\nterraform validate\n```\n", encoding="utf-8")

        with (
            patch("scripts.checks.hygiene.validate_cli_tools_in_prompts._KNOWN_CLI_TOOLS", {"terraform"}),
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks.hygiene.validate_cli_tools_in_prompts.shutil.which", return_value=None),
        ):
            failed: list[str] = []
            validate_cli_tools_in_prompts(failed)

        assert len(failed) == 1
        assert "CLI tool verification" in failed[0]

    def test_optional_tool_gh_missing_is_skipped(self, tmp_path: Path) -> None:
        """gh is optional (Decision 76); a referenced-but-missing gh does not fail the gate."""
        prompt_dir = tmp_path / ".github" / "prompts"
        prompt_dir.mkdir(parents=True)
        md = prompt_dir / "ci.prompt.md"
        md.write_text("```bash\ngh pr view\n```\n", encoding="utf-8")

        with (
            patch("scripts.checks.hygiene.validate_cli_tools_in_prompts._KNOWN_CLI_TOOLS", {"gh"}),
            patch("scripts.checks.hygiene.validate_cli_tools_in_prompts._OPTIONAL_CLI_TOOLS", {"gh"}),
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks.hygiene.validate_cli_tools_in_prompts.shutil.which", return_value=None),
        ):
            failed: list[str] = []
            validate_cli_tools_in_prompts(failed)

        assert failed == []

    def test_skips_comment_lines_in_code_blocks(self, tmp_path: Path) -> None:
        """Lines starting with # inside code blocks are not treated as commands."""
        prompt_dir = tmp_path / ".github" / "prompts"
        prompt_dir.mkdir(parents=True)
        md = prompt_dir / "test.prompt.md"
        md.write_text("```bash\n# aws sts get-caller-identity\n```\n", encoding="utf-8")

        with (
            patch("scripts.checks.hygiene.validate_cli_tools_in_prompts._KNOWN_CLI_TOOLS", {"aws"}),
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks.hygiene.validate_cli_tools_in_prompts.shutil.which", return_value=None),
        ):
            failed: list[str] = []
            validate_cli_tools_in_prompts(failed)

        # aws appears only in a comment — not in referenced, so not checked
        assert failed == []

    def test_no_failures_when_no_md_files(self, tmp_path: Path) -> None:
        """No failures when no markdown files exist in the search dirs."""
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_cli_tools_in_prompts(failed)

        assert failed == []
