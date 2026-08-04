"""Tests for validate_prompt_files() (VTS-08: rescoped to .github/prompts/scheduled/;
SGE-06: size ceiling added over both governed .prompt.md directories)."""

from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.checks import _common
from scripts.checks.prompts.validate_prompt_files import (
    _MAX_PROMPT_LINES,
    _SIZE_GOVERNED_PROMPT_DIRS,
    validate_prompt_files,
)

# 3 header lines ("# t", "", "## s") + 2998 filler lines = 3,001 raw lines: one over the ceiling.
_OVERSIZED_PROMPT = "# t\n\n## s\n" + "x\n" * 2998
# 3 header lines + 2997 filler lines = exactly 3,000 raw lines: the boundary, still compliant.
_AT_LIMIT_PROMPT = "# t\n\n## s\n" + "x\n" * 2997


def _write_scheduled(tmp_path: Path, name: str, content: str) -> Path:
    prompts_dir = tmp_path / ".github" / "prompts" / "scheduled"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    f = prompts_dir / name
    f.write_text(content, encoding="utf-8")
    return f


def _write_executor(tmp_path: Path, name: str, content: str) -> Path:
    prompts_dir = tmp_path / "config" / "agent" / "executor" / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    f = prompts_dir / name
    f.write_text(content, encoding="utf-8")
    return f


class TestValidatePromptFiles:
    """Tests for validate_prompt_files() against the scheduled-prompt structural contract."""

    def test_passes_with_h1_and_section(self, tmp_path: Path) -> None:
        """A well-formed scheduled prompt (H1 + a '## ' section) passes with no errors."""
        _write_scheduled(tmp_path, "ok.prompt.md", "# ok\n\n## Instructions\n\ndo the thing\n")
        _write_executor(tmp_path, "ok.prompt.md", _AT_LIMIT_PROMPT)
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_prompt_files(failed)
        assert failed == []

    def test_fails_when_no_prompt_files_found(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Acceptance criterion: a zero-file result fails loudly (the old "All 0 ... passed" no-op is gone).

        Pins the SCHEDULED directory specifically (mirrors
        TestPromptSizeLimit.test_fails_when_a_governed_directory_is_empty, which pins the
        executor directory) -- both governed dirs are empty here, so without this path
        assertion the executor guard alone could satisfy the generic substring check while a
        narrowed scheduled-only guard silently regressed undetected.
        """
        (tmp_path / ".github" / "prompts" / "scheduled").mkdir(parents=True)
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_prompt_files(failed)
        assert failed == ["Prompt file validation"]
        out = capsys.readouterr().out
        assert "no *.prompt.md files found under " in out
        assert str(tmp_path / ".github" / "prompts" / "scheduled") in out

    def test_fails_when_h1_missing(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        _write_scheduled(tmp_path, "bad.prompt.md", "## Instructions\n\nno title here\n")
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_prompt_files(failed)
        assert failed == ["Prompt file validation"]
        out = capsys.readouterr().out
        assert "missing H1 title line" in out

    def test_fails_when_section_missing(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        _write_scheduled(tmp_path, "bad.prompt.md", "# bad\n\nno section headers at all\n")
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_prompt_files(failed)
        assert failed == ["Prompt file validation"]
        out = capsys.readouterr().out
        assert "missing at least one '## ' section" in out

    def test_fails_on_dead_relative_reference(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        _write_scheduled(
            tmp_path,
            "bad.prompt.md",
            "# bad\n\n## Instructions\n\nsee [other](../missing-file.md) for detail\n",
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_prompt_files(failed)
        assert failed == ["Prompt file validation"]
        out = capsys.readouterr().out
        assert "dead reference '" in out

    def test_passes_on_live_relative_reference(self, tmp_path: Path) -> None:
        """A relative reference that resolves to a real file is not flagged as dead."""
        (tmp_path / ".github" / "prompts").mkdir(parents=True)
        (tmp_path / ".github" / "prompts" / "sibling.md").write_text("x", encoding="utf-8")
        _write_scheduled(
            tmp_path,
            "ok.prompt.md",
            "# ok\n\n## Instructions\n\nsee [other](../sibling.md) for detail\n",
        )
        _write_executor(tmp_path, "ok.prompt.md", _AT_LIMIT_PROMPT)
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_prompt_files(failed)
        assert failed == []

    def test_no_longer_requires_frontmatter_or_intent_section(self, tmp_path: Path) -> None:
        """NOTE 1: the VS-Code-format assertions (YAML frontmatter / name / description /
        inline model / '## Intent') are removed -- a plain H1 + '## ' section file with none
        of that passes clean."""
        _write_scheduled(tmp_path, "plain.prompt.md", "# plain\n\n## Output\n\nno frontmatter, no Intent section\n")
        _write_executor(tmp_path, "plain.prompt.md", _AT_LIMIT_PROMPT)
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


class TestPromptSizeLimit:
    """SGE-06: the raw-line size ceiling (Decision 43) fires, and only strictly above it."""

    def test_fails_on_oversized_scheduled_prompt(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """A 3,001-raw-line, otherwise-valid scheduled prompt fails on size alone."""
        _write_scheduled(tmp_path, "big.prompt.md", _OVERSIZED_PROMPT)
        _write_executor(tmp_path, "ok.prompt.md", _AT_LIMIT_PROMPT)
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_prompt_files(failed)
        assert failed == ["Prompt file validation"]
        out = capsys.readouterr().out
        assert ".github/prompts/scheduled/big.prompt.md : 3001 raw lines exceeds the 3000-line limit" in out

    def test_passes_at_exactly_the_line_limit(self, tmp_path: Path) -> None:
        """Exactly 3,000 raw lines is compliant (strict `>`, not `>=`)."""
        _write_scheduled(tmp_path, "boundary.prompt.md", _AT_LIMIT_PROMPT)
        _write_executor(tmp_path, "ok.prompt.md", _AT_LIMIT_PROMPT)
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_prompt_files(failed)
        assert failed == []

    def test_fails_when_a_governed_directory_is_empty(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """An empty governed directory fails the check itself rather than passing vacuously."""
        _write_scheduled(tmp_path, "ok.prompt.md", "# t\n\n## s\n\nbody\n")
        # config/agent/executor/prompts/ is never created: zero *.prompt.md files there.
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_prompt_files(failed)
        assert failed == ["Prompt file validation"]
        out = capsys.readouterr().out
        assert "no *.prompt.md files found under " in out
        assert str(tmp_path / "config" / "agent" / "executor" / "prompts") in out


class TestExecutorPromptScope:
    """SGE-06 critical seam: executor prompts are size-governed but NOT structure-governed."""

    def test_fails_on_oversized_executor_prompt(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """The executor directory IS swept for size."""
        _write_scheduled(tmp_path, "ok.prompt.md", "# t\n\n## s\n\nbody\n")
        _write_executor(tmp_path, "big.prompt.md", _OVERSIZED_PROMPT)
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_prompt_files(failed)
        assert failed == ["Prompt file validation"]
        out = capsys.readouterr().out
        assert "config/agent/executor/prompts/big.prompt.md : 3001 raw lines exceeds the 3000-line limit" in out

    def test_executor_prompts_are_not_structure_checked(self, tmp_path: Path) -> None:
        """No H1, no '## ' section, and a dead relative reference: still passes when under
        the limit, because the structure contract stays scoped to the scheduled directory."""
        _write_scheduled(tmp_path, "ok.prompt.md", "# t\n\n## s\n\nbody\n")
        _write_executor(
            tmp_path,
            "no-structure.prompt.md",
            "no title, no section, see [other](../missing-file.md)\n",
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_prompt_files(failed)
        assert failed == []


class TestPromptSizeLiveSurface:
    """Second-tier anti-vacuity anchor: the constant is aimed at something real in the live tree."""

    def test_governed_dirs_are_non_empty_on_the_live_tree(self) -> None:
        for dir_parts in _SIZE_GOVERNED_PROMPT_DIRS:
            prompts_dir = _common.ROOT.joinpath(*dir_parts)
            count = len(list(prompts_dir.glob("*.prompt.md")))
            assert count > 0, f"expected a non-empty *.prompt.md surface under {prompts_dir}"

    def test_live_tree_max_raw_lines_is_under_the_limit(self) -> None:
        max_lines = 0
        for dir_parts in _SIZE_GOVERNED_PROMPT_DIRS:
            prompts_dir = _common.ROOT.joinpath(*dir_parts)
            for f in prompts_dir.glob("*.prompt.md"):
                max_lines = max(max_lines, len(f.read_text(encoding="utf-8").splitlines()))
        assert max_lines < _MAX_PROMPT_LINES

    def test_limit_matches_decision_43_row(self) -> None:
        assert _MAX_PROMPT_LINES == 3000
