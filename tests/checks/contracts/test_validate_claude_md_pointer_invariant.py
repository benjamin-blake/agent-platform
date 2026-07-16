"""Tests for check_claude_md_pointer_invariant()."""

from pathlib import Path

from scripts.checks.contracts.validate_claude_md_pointer_invariant import check_claude_md_pointer_invariant


class TestClaudeMdPointerInvariant:
    """Tests for check_claude_md_pointer_invariant()."""

    def test_claude_md_pointer_happy_path(self, tmp_path: Path) -> None:
        p = tmp_path / "CLAUDE.md"
        p.write_text("@AGENTS.md\n", encoding="utf-8")
        assert check_claude_md_pointer_invariant(str(p)) is True

    def test_claude_md_pointer_extra_content(self, tmp_path: Path) -> None:
        p = tmp_path / "CLAUDE.md"
        p.write_text("@AGENTS.md\nstray content\n", encoding="utf-8")
        assert check_claude_md_pointer_invariant(str(p)) is False

    def test_claude_md_pointer_wrong_target(self, tmp_path: Path) -> None:
        p = tmp_path / "CLAUDE.md"
        p.write_text("@OTHER.md\n", encoding="utf-8")
        assert check_claude_md_pointer_invariant(str(p)) is False

    def test_claude_md_pointer_empty_file(self, tmp_path: Path) -> None:
        p = tmp_path / "CLAUDE.md"
        p.write_text("", encoding="utf-8")
        assert check_claude_md_pointer_invariant(str(p)) is False
