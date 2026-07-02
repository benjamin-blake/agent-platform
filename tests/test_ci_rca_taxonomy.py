"""Tests for scripts/ci_rca_taxonomy.py (100% coverage)."""

import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import scripts.ci_rca_taxonomy as taxonomy_mod  # noqa: E402
from scripts.ci_rca_taxonomy import (  # noqa: E402
    classify_failure,
    classify_failures,
    enumerate_workflow_names,
    load_taxonomy,
    resolve_workflow_tier,
)

MINIMAL_TAXONOMY = {
    "schema_version": 1,
    "taxonomy_version": 1,
    "function_to_category": {"validate_sloc_limits": "sloc_violation"},
    "log_pattern_to_category": [{"pattern": "ImportError", "category": "dependency_gap", "check_name": "import_error"}],
    "workflow_to_tier": {"CI": "CI", "Deploy": "not_a_gate"},
}


@pytest.fixture(autouse=True)
def reset_cache():
    taxonomy_mod._TAXONOMY_CACHE = None
    yield
    taxonomy_mod._TAXONOMY_CACHE = None


def _write_taxonomy(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "taxonomy.yaml"
    p.write_text(yaml.dump(data), encoding="utf-8")
    return p


class TestLoadTaxonomy:
    def test_happy_path(self, tmp_path):
        p = _write_taxonomy(tmp_path, MINIMAL_TAXONOMY)
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
        p = tmp_path / "partial.yaml"
        p.write_text(yaml.dump({"function_to_category": {}}), encoding="utf-8")
        with pytest.raises(ValueError, match="missing required keys"):
            load_taxonomy(p)


class TestClassifyFailure:
    def test_function_to_category_primary_match(self, tmp_path):
        p = _write_taxonomy(tmp_path, MINIMAL_TAXONOMY)
        cat, check, src = classify_failure("validate_sloc_limits FAILED", path=p)
        assert cat == "sloc_violation"
        assert check == "validate_sloc_limits"
        assert src == "function_to_category"

    def test_log_pattern_fallback(self, tmp_path):
        p = _write_taxonomy(tmp_path, MINIMAL_TAXONOMY)
        cat, check, src = classify_failure("Error: ImportError at line 5", path=p)
        assert cat == "dependency_gap"
        assert check == "import_error"
        assert src == "log_pattern_to_category"

    def test_taxonomy_fallback_unknown(self, tmp_path):
        p = _write_taxonomy(tmp_path, MINIMAL_TAXONOMY)
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
        p = _write_taxonomy(tmp_path, data)
        cat, check, src = classify_failure("ImportError", path=p)
        assert cat == "dependency_gap"


class TestResolveWorkflowTier:
    def test_ci_maps_to_CI(self, tmp_path):
        p = _write_taxonomy(tmp_path, MINIMAL_TAXONOMY)
        assert resolve_workflow_tier("CI", p) == "CI"

    def test_not_a_gate_returns_unknown(self, tmp_path):
        p = _write_taxonomy(tmp_path, MINIMAL_TAXONOMY)
        assert resolve_workflow_tier("Deploy", p) == "unknown"

    def test_miss_returns_unknown(self, tmp_path):
        p = _write_taxonomy(tmp_path, MINIMAL_TAXONOMY)
        assert resolve_workflow_tier("NotInMap", p) == "unknown"


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
        assert len(names) == 13


MULTI_TAXONOMY = dict(MINIMAL_TAXONOMY)
MULTI_TAXONOMY["function_to_category"] = {
    "validate_sloc_limits": "sloc_violation",
    "validate_iam_runner_policy": "iam_policy_gap",
}


class TestClassifyFailures:
    def test_single_match_returns_list_of_one(self, tmp_path):
        p = _write_taxonomy(tmp_path, MINIMAL_TAXONOMY)
        results = classify_failures("validate_sloc_limits FAILED", path=p)
        assert isinstance(results, list)
        assert len(results) == 1
        cat, check, src = results[0]
        assert cat == "sloc_violation"
        assert check == "validate_sloc_limits"
        assert src == "function_to_category"

    def test_multiple_matches_returns_list_of_n(self, tmp_path):
        p = _write_taxonomy(tmp_path, MULTI_TAXONOMY)
        log = "validate_sloc_limits FAILED\nvalidate_iam_runner_policy FAILED\n"
        results = classify_failures(log, path=p)
        assert len(results) == 2
        checks = {r[1] for r in results}
        assert "validate_sloc_limits" in checks
        assert "validate_iam_runner_policy" in checks

    def test_no_match_returns_taxonomy_fallback(self, tmp_path):
        p = _write_taxonomy(tmp_path, MINIMAL_TAXONOMY)
        results = classify_failures("nothing matched here", path=p)
        assert isinstance(results, list)
        assert len(results) == 1
        cat, check, src = results[0]
        assert src == "taxonomy_fallback"

    def test_deduplicates_same_function_name(self, tmp_path):
        p = _write_taxonomy(tmp_path, MINIMAL_TAXONOMY)
        # function name appears twice in log -- should produce exactly one result
        log = "validate_sloc_limits FAILED\nvalidate_sloc_limits also here\n"
        results = classify_failures(log, path=p)
        assert len(results) == 1


class TestJobsJsonPreference:
    """c9b: jobs-JSON step names take priority over log text substring scan."""

    def test_jobs_step_name_wins_over_log_text(self, tmp_path):
        taxonomy_data = {
            "schema_version": 1,
            "taxonomy_version": 1,
            "failure_categories": ["sloc_violation", "code_regression", "unknown"],
            "function_to_category": {"validate_sloc_limits": "sloc_violation"},
            "step_name_to_category": {"Run pytest": "code_regression"},
            "log_pattern_to_category": [],
            "workflow_to_tier": {"CI": "CI"},
        }
        p = _write_taxonomy(tmp_path, taxonomy_data)
        jobs = [{"name": "test", "steps": [{"name": "Run pytest", "conclusion": "failure", "number": 1}]}]
        cat, check, src = classify_failure("validate_sloc_limits FAILED in output", jobs=jobs, path=p)
        assert cat == "code_regression"
        assert check == "Run pytest"
        assert src == "step_name_to_category"

    def test_jobs_json_none_falls_back_to_log_text(self, tmp_path):
        taxonomy_data = {
            "schema_version": 1,
            "taxonomy_version": 1,
            "failure_categories": ["sloc_violation", "unknown"],
            "function_to_category": {"validate_sloc_limits": "sloc_violation"},
            "step_name_to_category": {},
            "log_pattern_to_category": [],
            "workflow_to_tier": {"CI": "CI"},
        }
        p = _write_taxonomy(tmp_path, taxonomy_data)
        cat, check, src = classify_failure("validate_sloc_limits FAILED", jobs=None, path=p)
        assert cat == "sloc_violation"
        assert src == "function_to_category"

    def test_new_categories_in_taxonomy(self, tmp_path):
        taxonomy_data = {
            "schema_version": 1,
            "taxonomy_version": 1,
            "failure_categories": ["test_collection_empty", "gate_escape", "unknown"],
            "function_to_category": {},
            "step_name_to_category": {"pytest --collect-only": "test_collection_empty"},
            "log_pattern_to_category": [],
            "workflow_to_tier": {"CI": "CI"},
        }
        p = _write_taxonomy(tmp_path, taxonomy_data)
        jobs = [{"name": "j", "steps": [{"name": "pytest --collect-only", "conclusion": "failure", "number": 1}]}]
        cat, check, src = classify_failure("collected 0 items", jobs=jobs, path=p)
        assert cat == "test_collection_empty"
        assert src == "step_name_to_category"
