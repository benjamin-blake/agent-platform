"""Shared taxonomy fixtures for tests/ci_rca/taxonomy/ (ci-rca-evidence-fidelity concern-split).

Hoisted out of the former tests/test_ci_rca_taxonomy.py monolith when its Priority-0/refusal
coverage pushed it past the 500-SLOC budget (Decision 128: decompose, never raise). Lives in
tests/fixtures/ (importable, exempt from the no-cross-test-import guard) since these constants
and helpers are shared across multiple test_*.py modules in the concern-split package.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

MINIMAL_TAXONOMY = {
    "schema_version": 1,
    "taxonomy_version": 1,
    "function_to_category": {"validate_sloc_limits": "sloc_violation"},
    "log_pattern_to_category": [{"pattern": "ImportError", "category": "dependency_gap", "check_name": "import_error"}],
    "workflows": {
        "CI": {"tier": "CI", "ci_rca": "watched", "owner": "platform", "rationale": "test fixture"},
        "Deploy": {"tier": "not_a_gate", "ci_rca": "excluded", "owner": "platform", "rationale": "test fixture"},
    },
}

MULTI_TAXONOMY = dict(MINIMAL_TAXONOMY)
MULTI_TAXONOMY["function_to_category"] = {
    "validate_sloc_limits": "sloc_violation",
    "validate_iam_runner_policy": "iam_policy_gap",
}

FAILED_CHECKS_TAXONOMY = dict(MINIMAL_TAXONOMY)
FAILED_CHECKS_TAXONOMY["function_to_category"] = {
    "validate_sloc_limits": "sloc_violation",
    "validate_platform_roadmap": "schema_drift",
}

STEP_NAME_MAP_TAXONOMY = dict(MINIMAL_TAXONOMY)
STEP_NAME_MAP_TAXONOMY["function_to_category"] = {"validate_test_coverage": "code_regression"}
STEP_NAME_MAP_TAXONOMY["step_name_to_category"] = {
    "Validate full tier (ruff, mypy, pytest, DQ runner, verifier harness)": "code_regression"
}


def write_taxonomy(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "taxonomy.yaml"
    p.write_text(yaml.dump(data), encoding="utf-8")
    return p


def write_validation_result(
    tmp_path: Path,
    attributions: list[dict],
    *,
    schema_version: int = 2,
    check_outcomes: list[dict] | None = None,
) -> Path:
    """schema_version defaults to 2 (the incumbent shape every existing caller pins). Passing
    schema_version=3 (Decision 170) additionally emits `check_outcomes` (empty unless overridden)
    plus the four rollup counts, so a consumer test can prove it still resolves
    (check, label) pairs from the v3 shape's unchanged failed_check_attributions field."""
    p = tmp_path / "validation-result.json"
    record: dict = {
        "schema_version": schema_version,
        "exit_code": 1,
        "failed_checks": [a["label"] for a in attributions],
        "failed_check_attributions": attributions,
    }
    if schema_version >= 3:
        record["check_outcomes"] = check_outcomes if check_outcomes is not None else []
        record["ran_checks"] = 0
        record["skipped_checks"] = 0
        record["vacuous_checks"] = 0
        record["undeclared_checks"] = 0
    p.write_text(json.dumps(record), encoding="utf-8")
    return p


_TOP_LEVEL_NAME_RE = re.compile(r"^name:\s*(.+?)\s*$")


def oracle_workflow_names(workflows_dir: Path) -> set[str]:
    """Independent expected-name oracle: line-scans for the top-level 'name:' key.

    Deliberately avoids yaml.safe_load (the SUT's parse mechanism) so the
    differential retains bug-catching power instead of being circular.
    """
    expected = set()
    for wf_path in Path(workflows_dir).glob("*.yml"):
        for line in wf_path.read_text(encoding="utf-8").splitlines():
            match = _TOP_LEVEL_NAME_RE.match(line)
            if match:
                expected.add(match.group(1).strip("\"'"))
                break
    return expected
