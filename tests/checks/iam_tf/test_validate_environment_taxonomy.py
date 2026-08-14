"""Tests for validate_environment_taxonomy()."""

from pathlib import Path
from unittest.mock import patch

from scripts.checks import registry
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

    def test_taxonomy_yaml_allowlisted(self, tmp_path: Path) -> None:
        """The converted Class D contract (CFG-11 conversion) is allowlisted at its NEW path --
        it legitimately spans both axes and must not trip its own vocabulary lint."""
        failed = self._run(
            tmp_path,
            {"docs/contracts/environment-taxonomy.yaml": "axis_a:\n  sandbox:\n    apply_gating: sandbox phase\n"},
            ["docs/contracts/environment-taxonomy.yaml"],
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

    def test_declares_examined_count_of_candidate_docs(self, tmp_path: Path) -> None:
        """Decision 170: declares the examined count of candidate docs (the files that pass the
        extension/allowlist filters and are actually scanned), not the raw changed-file count."""
        for rel in ("docs/x.md", "docs/y.md"):
            p = tmp_path / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("nothing interesting here\n", encoding="utf-8")
        with (
            patch(
                "scripts.checks._common.get_changed_files",
                return_value=["docs/x.md", "docs/y.md", "scripts/foo.py", "docs/DECISIONS.md", "docs/gone.md"],
            ),
            patch("scripts.checks._common.ROOT", tmp_path),
            patch.object(registry, "examined") as mock_examined,
        ):
            validate_environment_taxonomy([])
        # candidates: docs/x.md, docs/y.md -- scripts/foo.py fails the extension filter,
        # docs/DECISIONS.md is allowlisted, docs/gone.md fails the read (missing).
        mock_examined.assert_called_once_with(2, unit="candidate_docs")
