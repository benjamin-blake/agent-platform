"""Tests for scripts/ci_rca/taxonomy.py: load_taxonomy, classify_failure (singular),
resolve_workflow_tier, enumerate_workflow_names. Split from the former flat
tests/test_ci_rca_taxonomy.py (ci-rca-evidence-fidelity, Decision 128 decompose-by-default).
"""

from pathlib import Path

import pytest

from scripts.ci_rca.taxonomy import classify_failure, enumerate_workflow_names, load_taxonomy, resolve_workflow_tier
from tests.fixtures.ci_rca.taxonomy_data import FAILED_CHECKS_TAXONOMY, MINIMAL_TAXONOMY, oracle_workflow_names, write_taxonomy

ROOT = Path(__file__).parents[3]


class TestLoadTaxonomy:
    def test_happy_path(self, tmp_path):
        p = write_taxonomy(tmp_path, MINIMAL_TAXONOMY)
        result = load_taxonomy(p)
        assert result["taxonomy_version"] == 1

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_taxonomy(tmp_path / "nonexistent.yaml")

    def test_malformed_yaml_raises(self, tmp_path):
        p = tmp_path / "bad.yaml"
        p.write_text("key: [unclosed", encoding="utf-8")
        with pytest.raises(ValueError, match="Malformed taxonomy YAML"):
            load_taxonomy(p)

    def test_non_mapping_raises(self, tmp_path):
        p = tmp_path / "list.yaml"
        p.write_text("- a\n- b\n", encoding="utf-8")
        with pytest.raises(ValueError, match="must be a mapping"):
            load_taxonomy(p)

    def test_missing_required_keys_raises(self, tmp_path):
        import yaml

        p = tmp_path / "partial.yaml"
        p.write_text(yaml.dump({"function_to_category": {}}), encoding="utf-8")
        with pytest.raises(ValueError, match="missing required keys"):
            load_taxonomy(p)


class TestClassifyFailure:
    def test_function_to_category_primary_match(self, tmp_path):
        p = write_taxonomy(tmp_path, MINIMAL_TAXONOMY)
        cat, check, src = classify_failure("validate_sloc_limits FAILED", path=p)
        assert cat == "sloc_violation"
        assert check == "validate_sloc_limits"
        assert src == "function_to_category"

    def test_log_pattern_fallback(self, tmp_path):
        p = write_taxonomy(tmp_path, MINIMAL_TAXONOMY)
        cat, check, src = classify_failure("Error: ImportError at line 5", path=p)
        assert cat == "dependency_gap"
        assert check == "import_error"
        assert src == "log_pattern_to_category"

    def test_taxonomy_fallback_unknown(self, tmp_path):
        p = write_taxonomy(tmp_path, MINIMAL_TAXONOMY)
        cat, check, src = classify_failure("something unrecognized", path=p)
        assert cat == "unknown"
        assert check == "unknown"
        assert src == "taxonomy_fallback"

    def test_invalid_regex_skipped(self, tmp_path):
        data = dict(MINIMAL_TAXONOMY)
        data["log_pattern_to_category"] = [
            {"pattern": "[invalid(", "category": "x", "check_name": "y"},
            {"pattern": "ImportError", "category": "dependency_gap", "check_name": "import_error"},
        ]
        p = write_taxonomy(tmp_path, data)
        cat, check, src = classify_failure("ImportError", path=p)
        assert cat == "dependency_gap"

    def test_priority_2_jobs_step_name_matches_function_to_category_directly(self, tmp_path):
        """A failed step whose NAME happens to equal a function_to_category key (not a
        step_name_to_category key) matches via Priority 2's direct func_map lookup."""
        p = write_taxonomy(tmp_path, MINIMAL_TAXONOMY)
        jobs = [{"steps": [{"name": "validate_sloc_limits", "conclusion": "failure"}]}]
        cat, check, src = classify_failure("irrelevant log", jobs=jobs, path=p)
        assert cat == "sloc_violation"
        assert check == "validate_sloc_limits"
        assert src == "function_to_category"

    def test_failed_checks_block_terminates_on_blank_line_after_entries(self, tmp_path):
        """_parse_failed_checks_block's early-break branch: once at least one entry has been
        collected, a blank line (or a "===" banner / "Fix all failures" line) ends the block --
        exercised here via trailing prose AFTER the block that must not be treated as more
        entries."""
        p = write_taxonomy(tmp_path, FAILED_CHECKS_TAXONOMY)
        log = "Failed checks:\n  - validate_platform_roadmap\n\nFix all failures before committing.\n"
        cat, check, src = classify_failure(log, path=p)
        assert cat == "schema_drift"
        assert check == "validate_platform_roadmap"
        assert src == "validate_failed_checks_block"


class TestResolveWorkflowTier:
    def test_ci_maps_to_CI(self, tmp_path):
        p = write_taxonomy(tmp_path, MINIMAL_TAXONOMY)
        assert resolve_workflow_tier("CI", p) == "CI"

    def test_not_a_gate_returns_unknown(self, tmp_path):
        p = write_taxonomy(tmp_path, MINIMAL_TAXONOMY)
        assert resolve_workflow_tier("Deploy", p) == "unknown"

    def test_miss_returns_unknown(self, tmp_path):
        p = write_taxonomy(tmp_path, MINIMAL_TAXONOMY)
        assert resolve_workflow_tier("NotInMap", p) == "unknown"

    def test_return_contract_unchanged_against_real_taxonomy(self):
        """Migration-seam guard (PLAN-ci-rca-adjudication-guard): resolve_workflow_tier's str
        return contract ('unknown' for a miss/not_a_gate) must be identical for every real
        workflow name after the flat-to-nested `workflows:` map migration -- proving the nesting
        did not alter downstream evidence-bundle behaviour."""
        got = {n: resolve_workflow_tier(n) for n in enumerate_workflow_names()}
        assert got["CI"] == "CI"
        assert got["Main Canary"] == "CI"
        assert all(v == "unknown" for k, v in got.items() if k not in ("CI", "Main Canary")), got


class TestEnumerateWorkflowNames:
    def test_extracts_names(self, tmp_path):
        wf = tmp_path / "test.yml"
        wf.write_text("name: My Workflow\non:\n  push:\n", encoding="utf-8")
        result = enumerate_workflow_names(tmp_path)
        assert "My Workflow" in result

    def test_skips_unreadable(self, tmp_path):
        bad = tmp_path / "bad.yml"
        bad.write_text("key: [unclosed", encoding="utf-8")
        result = enumerate_workflow_names(tmp_path)
        assert isinstance(result, list)

    def test_real_workflows_dir(self):
        names = enumerate_workflow_names()
        assert "CI" in names
        assert set(names) == oracle_workflow_names(ROOT / ".github" / "workflows")

    def test_drift_immunity_tracks_added_and_removed_workflow(self, tmp_path):
        (tmp_path / "a.yml").write_text("name: Alpha\non:\n  push:\n", encoding="utf-8")
        (tmp_path / "b.yml").write_text("name: Bravo\non:\n  push:\n", encoding="utf-8")
        assert set(enumerate_workflow_names(tmp_path)) == {"Alpha", "Bravo"}

        (tmp_path / "c.yml").write_text("name: Charlie\non:\n  push:\n", encoding="utf-8")
        assert set(enumerate_workflow_names(tmp_path)) == {"Alpha", "Bravo", "Charlie"}

        (tmp_path / "b.yml").unlink()
        assert set(enumerate_workflow_names(tmp_path)) == {"Alpha", "Charlie"}
