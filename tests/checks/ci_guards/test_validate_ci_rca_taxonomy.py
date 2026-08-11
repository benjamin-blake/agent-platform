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
            "workflows": {"CI": {"tier": "CI", "ci_rca": "watched", "owner": "platform", "rationale": "test fixture"}},
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
            assert any("absent from workflows" in f for f in failed), (
                f"Expected taxonomy failure for missing workflows, got: {failed}"
            )
        finally:
            taxonomy_mod._TAXONOMY_PATH = original_path
            taxonomy_mod._TAXONOMY_CACHE = None

    def test_registry_totality_guard_fails_on_unmapped_registered_check(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Mutation-proves the registry-totality assertion can actually fail: a registered check
        absent from function_to_category (Priority-0 attribution precondition) must fail the
        guard, not silently pass."""
        import scripts.checks.ci_guards.validate_ci_rca_taxonomy as subject
        from scripts.checks.registry import Check

        real_all_checks = subject.registry.all_checks

        def _mutated() -> dict:
            checks = real_all_checks()
            checks["validate_totally_fake_unregistered_check"] = Check(name="validate_totally_fake_unregistered_check")
            return checks

        monkeypatch.setattr(subject.registry, "all_checks", _mutated)
        failed: list[str] = []
        validate_ci_rca_taxonomy(failed)
        assert any(
            "validate_totally_fake_unregistered_check" in f and "absent from function_to_category" in f for f in failed
        ), f"Expected registry-totality failure, got: {failed}"

    def test_evidence_insufficient_sentinel_is_exempt_from_dead_enum_branch_check(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """evidence_insufficient is declared in failure_categories but never appears in
        function_to_category/step_name_to_category/log_pattern_to_category (it is emitted at
        the classify_failure/classify_failures call sites, never via a map entry) -- the
        hardcoded code-level sentinel exemption (beside "unknown") must keep this from tripping
        the reverse dead-enum-branch check."""
        import scripts.checks.ci_guards.validate_ci_rca_taxonomy as subject

        synthetic = {
            "schema_version": 1,
            "taxonomy_version": 1,
            "failure_categories": ["sloc_violation", "unknown", "evidence_insufficient"],
            "function_to_category": {"validate_sloc_limits": "sloc_violation"},
            "step_name_to_category": {},
            "log_pattern_to_category": [],
            "workflows": {},
        }
        monkeypatch.setattr(subject.registry, "all_checks", lambda: {"validate_sloc_limits": object()})
        monkeypatch.setattr("scripts.ci_rca.taxonomy.enumerate_workflow_names", lambda: [])
        monkeypatch.setattr("scripts.ci_rca.taxonomy.load_taxonomy", lambda: synthetic)
        failed: list[str] = []
        validate_ci_rca_taxonomy(failed)
        assert not failed, f"Expected no failures (sentinel exemption), got: {failed}"

    def test_missing_failure_categories_key_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import scripts.checks.ci_guards.validate_ci_rca_taxonomy as subject

        synthetic = {
            "schema_version": 1,
            "taxonomy_version": 1,
            "function_to_category": {"validate_sloc_limits": "sloc_violation"},
            "step_name_to_category": {},
            "log_pattern_to_category": [],
            "workflows": {},
        }
        monkeypatch.setattr(subject.registry, "all_checks", lambda: {"validate_sloc_limits": object()})
        monkeypatch.setattr("scripts.ci_rca.taxonomy.enumerate_workflow_names", lambda: [])
        monkeypatch.setattr("scripts.ci_rca.taxonomy.load_taxonomy", lambda: synthetic)
        failed: list[str] = []
        validate_ci_rca_taxonomy(failed)
        assert any("missing top-level 'failure_categories:' list" in f for f in failed), failed

    def test_used_category_absent_from_failure_categories_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import scripts.checks.ci_guards.validate_ci_rca_taxonomy as subject

        synthetic = {
            "schema_version": 1,
            "taxonomy_version": 1,
            "failure_categories": ["unknown", "evidence_insufficient"],
            "function_to_category": {"validate_sloc_limits": "sloc_violation"},
            "step_name_to_category": {},
            "log_pattern_to_category": [],
            "workflows": {},
        }
        monkeypatch.setattr(subject.registry, "all_checks", lambda: {"validate_sloc_limits": object()})
        monkeypatch.setattr("scripts.ci_rca.taxonomy.enumerate_workflow_names", lambda: [])
        monkeypatch.setattr("scripts.ci_rca.taxonomy.load_taxonomy", lambda: synthetic)
        failed: list[str] = []
        validate_ci_rca_taxonomy(failed)
        assert any("sloc_violation" in f and "used in taxonomy maps but absent" in f for f in failed), failed

    def test_declared_category_unclassifiable_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import scripts.checks.ci_guards.validate_ci_rca_taxonomy as subject

        synthetic = {
            "schema_version": 1,
            "taxonomy_version": 1,
            "failure_categories": ["sloc_violation", "unknown", "evidence_insufficient", "orphaned_category"],
            "function_to_category": {"validate_sloc_limits": "sloc_violation"},
            "step_name_to_category": {},
            "log_pattern_to_category": [],
            "workflows": {},
        }
        monkeypatch.setattr(subject.registry, "all_checks", lambda: {"validate_sloc_limits": object()})
        monkeypatch.setattr("scripts.ci_rca.taxonomy.enumerate_workflow_names", lambda: [])
        monkeypatch.setattr("scripts.ci_rca.taxonomy.load_taxonomy", lambda: synthetic)
        failed: list[str] = []
        validate_ci_rca_taxonomy(failed)
        assert any("orphaned_category" in f and "absent from all classifier maps" in f for f in failed), failed

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
