"""Tests for validate_ci_rca_taxonomy (wired into both --pre and run_python_checks)."""

from pathlib import Path

import pytest

from scripts.checks._common import ROOT
from scripts.checks.ci_guards.validate_ci_rca_taxonomy import validate_ci_rca_taxonomy


class TestValidateCiRcaTaxonomy:
    """Tests for validate_ci_rca_taxonomy (wired into both --pre and run_python_checks)."""

    def test_complete_map_passes(self) -> None:
        failed: list[str] = []
        validate_ci_rca_taxonomy(failed)
        assert not failed, f"Expected no failures, got: {failed}"

    def test_missing_workflow_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import scripts.ci_rca.taxonomy as taxonomy_mod  # noqa: I001
        import yaml

        incomplete_taxonomy = {
            "schema_version": 1,
            "taxonomy_version": 1,
            "function_to_category": {},
            "log_pattern_to_category": [],
            "workflow_to_tier": {"CI": "CI"},
        }
        tax_path = tmp_path / "taxonomy.yaml"
        tax_path.write_text(yaml.dump(incomplete_taxonomy))

        taxonomy_mod._TAXONOMY_CACHE = None
        original_path = taxonomy_mod._TAXONOMY_PATH
        taxonomy_mod._TAXONOMY_PATH = tax_path
        try:
            from scripts.ci_rca.taxonomy import enumerate_workflow_names

            workflows_dir = ROOT / ".github" / "workflows"
            actual_names = enumerate_workflow_names(workflows_dir)
            missing = [n for n in actual_names if n != "CI"]
            if not missing:
                pytest.skip("All workflows happen to be in the minimal map")

            failed: list[str] = []
            validate_ci_rca_taxonomy(failed)
            assert any("absent from workflow_to_tier" in f for f in failed), (
                f"Expected taxonomy failure for missing workflows, got: {failed}"
            )
        finally:
            taxonomy_mod._TAXONOMY_PATH = original_path
            taxonomy_mod._TAXONOMY_CACHE = None

    def test_taxonomy_file_missing_fails(self, tmp_path: Path) -> None:
        import scripts.ci_rca.taxonomy as taxonomy_mod

        taxonomy_mod._TAXONOMY_CACHE = None
        original_path = taxonomy_mod._TAXONOMY_PATH
        taxonomy_mod._TAXONOMY_PATH = tmp_path / "nonexistent.yaml"
        try:
            failed: list[str] = []
            validate_ci_rca_taxonomy(failed)
            assert any("CI-RCA taxonomy" in f for f in failed), f"Expected taxonomy error, got: {failed}"
        finally:
            taxonomy_mod._TAXONOMY_PATH = original_path
            taxonomy_mod._TAXONOMY_CACHE = None
