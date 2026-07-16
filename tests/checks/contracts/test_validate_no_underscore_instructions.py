"""Tests for validate_no_underscore_instructions()."""

from pathlib import Path
from unittest.mock import patch

from scripts.checks.contracts.validate_no_underscore_instructions import validate_no_underscore_instructions


class TestValidateNoUnderscoreInstructions:
    """Tests for validate_no_underscore_instructions()."""

    def test_underscore_check_passes_when_file_absent(self, tmp_path: Path) -> None:
        """Validation passes when the underscore instruction file is not present."""
        github_dir = tmp_path / ".github"
        github_dir.mkdir(parents=True)
        # Only the hyphen variant exists -- underscore must be absent
        (github_dir / "copilot-instructions.md").write_text("# instructions\n", encoding="utf-8")

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_no_underscore_instructions(failed)

        assert failed == []

    def test_underscore_check_fails_when_file_present(self, tmp_path: Path) -> None:
        """Validation fails when .github/copilot_instructions.md exists."""
        github_dir = tmp_path / ".github"
        github_dir.mkdir(parents=True)
        (github_dir / "copilot_instructions.md").write_text("# ghost\n", encoding="utf-8")

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_no_underscore_instructions(failed)

        assert "Underscore instruction file check" in failed
