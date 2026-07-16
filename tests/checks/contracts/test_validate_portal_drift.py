"""Tests for validate_portal_drift() -- ULF-11 portal-artefact drift gate."""

from pathlib import Path
from unittest.mock import patch

from scripts.checks.contracts.validate_portal_drift import validate_portal_drift


class TestValidatePortalDrift:
    """Tests for validate_portal_drift() -- ULF-11 portal-artefact drift gate."""

    _BASELINE_PROMPTS = (
        "projection: >-\n"
        "  Test projection header for the curated evaluator index.\n"
        "questions:\n"
        "  - id: Q1\n"
        "    theme: test\n"
        "    question: test question\n"
        "    answer_loci:\n"
        "      - README.md\n"
    )
    _BASELINE_README = "# agent-platform\n\nThis file is a projection of CLAUDE.md.\n"
    _BASELINE_SECURITY = "# Security Policy\n\nThis file is a projection of the security posture.\n"

    def _write_baseline(self, tmp_path: Path) -> None:
        (tmp_path / "EVALUATION-PROMPTS.yaml").write_text(self._BASELINE_PROMPTS, encoding="utf-8")
        (tmp_path / "README.md").write_text(self._BASELINE_README, encoding="utf-8")
        (tmp_path / "SECURITY.md").write_text(self._BASELINE_SECURITY, encoding="utf-8")

    def test_live_repo_is_clean(self) -> None:
        """The live repo passes today: no answer-locus, header, or token drift."""
        failed: list[str] = []
        validate_portal_drift(failed)
        assert failed == []

    def test_baseline_fixture_is_clean(self, tmp_path: Path) -> None:
        """Sanity: the synthetic baseline used by the failure-mode tests passes on its own."""
        self._write_baseline(tmp_path)
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_portal_drift(failed)
        assert failed == []

    def test_fails_when_answer_locus_does_not_resolve(self, tmp_path: Path) -> None:
        self._write_baseline(tmp_path)
        prompts_path = tmp_path / "EVALUATION-PROMPTS.yaml"
        prompts_path.write_text(self._BASELINE_PROMPTS.replace("README.md", "docs/does-not-exist.md"), encoding="utf-8")
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_portal_drift(failed)
        assert any("answer-locus does not resolve" in f for f in failed)

    def test_fails_when_portal_file_missing_projection_header(self, tmp_path: Path) -> None:
        self._write_baseline(tmp_path)
        (tmp_path / "README.md").write_text("# agent-platform\n\nNo header claim here.\n", encoding="utf-8")
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_portal_drift(failed)
        assert any("missing a 'projection of' line" in f for f in failed)

    def test_fails_when_evaluation_prompts_missing_top_level_projection_key(self, tmp_path: Path) -> None:
        self._write_baseline(tmp_path)
        (tmp_path / "EVALUATION-PROMPTS.yaml").write_text(
            "questions:\n  - id: Q1\n    answer_loci:\n      - README.md\n", encoding="utf-8"
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_portal_drift(failed)
        assert any("missing its top-level `projection:` header" in f for f in failed)

    def test_fails_when_ops_table_token_leaks_into_evaluation_prompts(self, tmp_path: Path) -> None:
        self._write_baseline(tmp_path)
        (tmp_path / "EVALUATION-PROMPTS.yaml").write_text(
            self._BASELINE_PROMPTS + "    # references ops_recommendations internally\n", encoding="utf-8"
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_portal_drift(failed)
        assert any("ops_recommendations" in f for f in failed)

    def test_fails_when_yaml_import_fails(self, tmp_path: Path) -> None:
        import builtins

        real_import = builtins.__import__

        def _fake_import(name, *args, **kwargs):
            if name == "yaml":
                raise ImportError("no yaml")
            return real_import(name, *args, **kwargs)

        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("builtins.__import__", side_effect=_fake_import),
        ):
            failed: list[str] = []
            validate_portal_drift(failed)
        assert any("yaml import failed" in f for f in failed)

    def test_fails_when_evaluation_prompts_missing(self, tmp_path: Path) -> None:
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_portal_drift(failed)
        assert any("EVALUATION-PROMPTS.yaml is missing" in f for f in failed)

    def test_fails_when_evaluation_prompts_is_invalid_yaml(self, tmp_path: Path) -> None:
        self._write_baseline(tmp_path)
        (tmp_path / "EVALUATION-PROMPTS.yaml").write_text("projection: [unterminated\n", encoding="utf-8")
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_portal_drift(failed)
        assert any("failed to parse" in f for f in failed)

    def test_skips_empty_answer_locus_entry(self, tmp_path: Path) -> None:
        self._write_baseline(tmp_path)
        (tmp_path / "EVALUATION-PROMPTS.yaml").write_text(
            self._BASELINE_PROMPTS.replace("- README.md", "- ''\n      - README.md"), encoding="utf-8"
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_portal_drift(failed)
        assert failed == []

    def test_fails_when_readme_or_security_file_missing(self, tmp_path: Path) -> None:
        self._write_baseline(tmp_path)
        (tmp_path / "README.md").unlink()
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_portal_drift(failed)
        assert any("portal file missing: README.md" in f for f in failed)
