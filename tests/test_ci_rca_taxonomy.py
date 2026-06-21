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
        assert len(names) == 10
