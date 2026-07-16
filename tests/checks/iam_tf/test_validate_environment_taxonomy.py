"""Tests for validate_environment_taxonomy()."""

from pathlib import Path
from unittest.mock import patch

from scripts.checks.iam_tf.validate_environment_taxonomy import validate_environment_taxonomy


class TestValidateEnvironmentTaxonomy:
    """Tests for validate_environment_taxonomy (two-axis vocabulary reservation lint)."""

    def _run(self, tmp_path: Path, files: dict[str, str], changed: list[str]) -> list[str]:
        for rel, content in files.items():
            p = tmp_path / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
        failed: list[str] = []
        with (
            patch("scripts.checks._common.get_changed_files", return_value=changed),
            patch("scripts.checks._common.ROOT", tmp_path),
        ):
            validate_environment_taxonomy(failed)
        return failed

    def test_flags_phase_used_as_environment(self, tmp_path: Path) -> None:
        failed = self._run(tmp_path, {"docs/x.md": "We run the live_full environment nightly.\n"}, ["docs/x.md"])
        assert failed == ["Environment/phase taxonomy"]

    def test_flags_tier_used_as_phase(self, tmp_path: Path) -> None:
        failed = self._run(tmp_path, {"docs/x.md": "The sandbox phase mocks externals.\n"}, ["docs/x.md"])
        assert failed == ["Environment/phase taxonomy"]

    def test_clean_doc_passes(self, tmp_path: Path) -> None:
        failed = self._run(
            tmp_path,
            {"docs/x.md": "The sandbox environment auto-applies; research is a phase.\n"},
            ["docs/x.md"],
        )
        assert failed == []

    def test_compound_tokens_allowed(self, tmp_path: Path) -> None:
        failed = self._run(
            tmp_path,
            {"docs/x.md": "research_sandbox environment and production_ensemble phase are fine.\n"},
            ["docs/x.md"],
        )
        assert failed == []

    def test_allowlisted_file_skipped(self, tmp_path: Path) -> None:
        failed = self._run(
            tmp_path,
            {"docs/DECISIONS.md": "The live_full environment and sandbox phase appear here.\n"},
            ["docs/DECISIONS.md"],
        )
        assert failed == []

    def test_github_and_tests_paths_skipped(self, tmp_path: Path) -> None:
        failed = self._run(
            tmp_path,
            {".github/workflows/w.yml": "name: sandbox phase\n", "tests/fixture.md": "live_full environment\n"},
            [".github/workflows/w.yml", "tests/fixture.md"],
        )
        assert failed == []

    def test_non_doc_suffix_skipped(self, tmp_path: Path) -> None:
        failed = self._run(
            tmp_path,
            {"scripts/foo.py": "# sandbox phase live_full environment\n"},
            ["scripts/foo.py"],
        )
        assert failed == []

    def test_missing_file_ignored(self, tmp_path: Path) -> None:
        failed: list[str] = []
        with (
            patch("scripts.checks._common.get_changed_files", return_value=["docs/gone.md"]),
            patch("scripts.checks._common.ROOT", tmp_path),
        ):
            validate_environment_taxonomy(failed)
        assert failed == []
