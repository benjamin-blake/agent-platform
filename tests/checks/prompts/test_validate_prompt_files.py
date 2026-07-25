"""Tests for validate_prompt_files() (VTS-08: rescoped to .github/prompts/scheduled/)."""

from pathlib import Path
from unittest.mock import patch

from scripts.checks import _common
from scripts.checks.prompts.validate_prompt_files import validate_prompt_files


class TestValidatePromptFiles:
    """Tests for validate_prompt_files() against the scheduled-prompt structural contract."""

    def _write(self, tmp_path: Path, name: str, content: str) -> Path:
        prompts_dir = tmp_path / ".github" / "prompts" / "scheduled"
        prompts_dir.mkdir(parents=True, exist_ok=True)
        f = prompts_dir / name
        f.write_text(content, encoding="utf-8")
        return f

    def test_passes_with_h1_and_section(self, tmp_path: Path) -> None:
        """A well-formed scheduled prompt (H1 + a '## ' section) passes with no errors."""
        self._write(tmp_path, "ok.prompt.md", "# ok\n\n## Instructions\n\ndo the thing\n")
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_prompt_files(failed)
        assert failed == []

    def test_fails_when_no_prompt_files_found(self, tmp_path: Path) -> None:
        """Acceptance criterion: a zero-file result fails loudly (the old "All 0 ... passed" no-op is gone)."""
        (tmp_path / ".github" / "prompts" / "scheduled").mkdir(parents=True)
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_prompt_files(failed)
        assert failed == ["Prompt file validation"]

    def test_fails_when_h1_missing(self, tmp_path: Path) -> None:
        self._write(tmp_path, "bad.prompt.md", "## Instructions\n\nno title here\n")
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_prompt_files(failed)
        assert failed == ["Prompt file validation"]

    def test_fails_when_section_missing(self, tmp_path: Path) -> None:
        self._write(tmp_path, "bad.prompt.md", "# bad\n\nno section headers at all\n")
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_prompt_files(failed)
        assert failed == ["Prompt file validation"]

    def test_fails_on_dead_relative_reference(self, tmp_path: Path) -> None:
        self._write(
            tmp_path,
            "bad.prompt.md",
            "# bad\n\n## Instructions\n\nsee [other](../missing-file.md) for detail\n",
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_prompt_files(failed)
        assert failed == ["Prompt file validation"]

    def test_passes_on_live_relative_reference(self, tmp_path: Path) -> None:
        """A relative reference that resolves to a real file is not flagged as dead."""
        (tmp_path / ".github" / "prompts").mkdir(parents=True)
        (tmp_path / ".github" / "prompts" / "sibling.md").write_text("x", encoding="utf-8")
        self._write(
            tmp_path,
            "ok.prompt.md",
            "# ok\n\n## Instructions\n\nsee [other](../sibling.md) for detail\n",
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_prompt_files(failed)
        assert failed == []

    def test_no_longer_requires_frontmatter_or_intent_section(self, tmp_path: Path) -> None:
        """NOTE 1: the VS-Code-format assertions (YAML frontmatter / name / description /
        inline model / '## Intent') are removed -- a plain H1 + '## ' section file with none
        of that passes clean."""
        self._write(tmp_path, "plain.prompt.md", "# plain\n\n## Output\n\nno frontmatter, no Intent section\n")
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_prompt_files(failed)
        assert failed == []

    def test_live_surface_passes_with_nonzero_count(self) -> None:
        """Substantive rec-2396 closure evidence: the real .github/prompts/scheduled/ tree
        (unmocked _common.ROOT) validates clean with a non-zero file count."""
        prompts_dir = _common.ROOT / ".github" / "prompts" / "scheduled"
        assert list(prompts_dir.glob("*.prompt.md")), "expected a non-empty live scheduled-prompt surface"

        failed: list[str] = []
        validate_prompt_files(failed)
        assert failed == []
