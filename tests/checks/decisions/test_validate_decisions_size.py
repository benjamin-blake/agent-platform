"""Tests for validate_decisions_size(). Mirror of
scripts/checks/decisions/validate_decisions_size.py (Decision 134 / Decision 114 parity)."""

from pathlib import Path
from unittest.mock import patch

from scripts.checks.decisions.validate_decisions_size import (
    _DECISIONS_COMBINED_MAX_BYTES,
    _DECISIONS_LIVE_MAX_BYTES,
    _DECISIONS_LIVE_MAX_H2,
    _decisions_size_issues,
    validate_decisions_size,
)


def _live_header_block(count: int) -> str:
    """Build `count` synthetic '## Decision N:' live-file-shaped headers with a small body."""
    return "".join(f"## Decision {i}: Test entry {i}\n\nBody text.\n\n---\n\n" for i in range(1, count + 1))


class TestDecisionsSizeIssuesLiveBytes:
    """_decisions_size_issues() live-byte-ceiling boundary cases (_DECISIONS_LIVE_MAX_BYTES)."""

    def test_below_ceiling_returns_empty(self) -> None:
        live = "x" * (_DECISIONS_LIVE_MAX_BYTES - 1)
        assert _decisions_size_issues(live, "") == []

    def test_at_ceiling_returns_empty(self) -> None:
        live = "x" * _DECISIONS_LIVE_MAX_BYTES
        assert _decisions_size_issues(live, "") == []

    def test_above_ceiling_fails(self) -> None:
        live = "x" * (_DECISIONS_LIVE_MAX_BYTES + 1)
        issues = _decisions_size_issues(live, "")
        assert len(issues) == 1
        assert "DECISIONS.md" in issues[0]
        assert str(_DECISIONS_LIVE_MAX_BYTES + 1) in issues[0]
        assert str(_DECISIONS_LIVE_MAX_BYTES) in issues[0]


class TestDecisionsSizeIssuesLiveH2:
    """_decisions_size_issues() live-header-count boundary cases (_DECISIONS_LIVE_MAX_H2)."""

    def test_below_ceiling_returns_empty(self) -> None:
        live = _live_header_block(_DECISIONS_LIVE_MAX_H2 - 1)
        assert _decisions_size_issues(live, "") == []

    def test_at_ceiling_returns_empty(self) -> None:
        live = _live_header_block(_DECISIONS_LIVE_MAX_H2)
        assert _decisions_size_issues(live, "") == []

    def test_above_ceiling_fails(self) -> None:
        live = _live_header_block(_DECISIONS_LIVE_MAX_H2 + 1)
        issues = _decisions_size_issues(live, "")
        assert len(issues) == 1
        assert "live '## Decision' headers" in issues[0]
        assert str(_DECISIONS_LIVE_MAX_H2 + 1) in issues[0]


class TestDecisionsSizeIssuesCombined:
    """_decisions_size_issues() combined live+archive-byte-ceiling boundary cases
    (_DECISIONS_COMBINED_MAX_BYTES), with neither the live-byte nor live-H2 ceiling breached."""

    _LIVE_SIZE = 350_000  # comfortably under _DECISIONS_LIVE_MAX_BYTES (500_000, Decision 145)

    def test_below_ceiling_returns_empty(self) -> None:
        live = "x" * self._LIVE_SIZE
        archive = "x" * (_DECISIONS_COMBINED_MAX_BYTES - self._LIVE_SIZE - 1)
        assert _decisions_size_issues(live, archive) == []

    def test_at_ceiling_returns_empty(self) -> None:
        live = "x" * self._LIVE_SIZE
        archive = "x" * (_DECISIONS_COMBINED_MAX_BYTES - self._LIVE_SIZE)
        assert _decisions_size_issues(live, archive) == []

    def test_above_ceiling_fails(self) -> None:
        live = "x" * self._LIVE_SIZE
        archive = "x" * (_DECISIONS_COMBINED_MAX_BYTES - self._LIVE_SIZE + 1)
        issues = _decisions_size_issues(live, archive)
        assert len(issues) == 1
        assert "combined" in issues[0]
        assert str(_DECISIONS_COMBINED_MAX_BYTES) in issues[0]

    def test_archive_bytes_count_toward_combined_ceiling(self) -> None:
        """DECISIONS_ARCHIVE.md bytes alone trip the combined ceiling even with a tiny live file --
        proves the archive file is genuinely covered by the guard, not just accepted and ignored."""
        live = "tiny live file, well under every live ceiling"
        archive = "x" * (_DECISIONS_COMBINED_MAX_BYTES + 1)
        issues = _decisions_size_issues(live, archive)
        assert any("combined" in issue for issue in issues)


class TestDecisionsSizeIssuesReliefValveMessage:
    def test_message_names_relief_valves(self) -> None:
        live = "x" * (_DECISIONS_LIVE_MAX_BYTES + 1)
        issues = _decisions_size_issues(live, "")
        assert len(issues) == 1
        assert "DPI-04" in issues[0]
        assert "archive" in issues[0].lower()
        assert "compact" in issues[0].lower()


class TestValidateDecisionsSizeRegisteredCheck:
    """Exercises the REGISTERED validate_decisions_size(failed) function itself (not just the
    pure helper), via patch("scripts.checks._common.ROOT", tmp_path) over a synthetic
    docs/DECISIONS.md + docs/DECISIONS_ARCHIVE.md tree -- mirrors
    tests/checks/roadmap/test_validate_platform_roadmap.py's TestPlatformRoadmapCriteriaIntegrity
    pattern, so validate_test_coverage's 100%-of-new-code gate covers the check function's own
    file-read / count / print / failed.append branches."""

    def _write_docs(self, tmp_path: Path, live_text: str, archive_text: str) -> None:
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir(parents=True, exist_ok=True)
        (docs_dir / "DECISIONS.md").write_text(live_text, encoding="utf-8")
        (docs_dir / "DECISIONS_ARCHIVE.md").write_text(archive_text, encoding="utf-8")

    def test_pass_case(self, tmp_path: Path) -> None:
        self._write_docs(tmp_path, "## Decision 1: Small entry\n\nBody.\n\n---\n\n", "Archive body.\n")
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_decisions_size(failed)
        assert failed == []

    def test_fail_case(self, tmp_path: Path) -> None:
        self._write_docs(tmp_path, "x" * (_DECISIONS_LIVE_MAX_BYTES + 1), "")
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_decisions_size(failed)
        assert "DECISIONS size governance" in failed

    def test_missing_live_file_fails(self, tmp_path: Path) -> None:
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir(parents=True, exist_ok=True)
        (docs_dir / "DECISIONS_ARCHIVE.md").write_text("", encoding="utf-8")
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_decisions_size(failed)
        assert "DECISIONS size governance" in failed

    def test_missing_archive_file_fails(self, tmp_path: Path) -> None:
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir(parents=True, exist_ok=True)
        (docs_dir / "DECISIONS.md").write_text("## Decision 1: X\n", encoding="utf-8")
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_decisions_size(failed)
        assert "DECISIONS size governance" in failed
