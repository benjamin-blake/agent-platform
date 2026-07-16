"""Shared taxonomy fixture dicts for tests/ci_rca/evidence/ (rec-2709 Wave 10).

Hoisted VERBATIM from the former tests/test_ci_rca_evidence.py monolith. MINI_TAXONOMY is
genuinely cross-module: the package conftest's `taxonomy_file` fixture writes it to disk, AND
tests/ci_rca/evidence/test_live_s3.py's TestLiveS3Roundtrip re-derives its own taxonomy_file
directly from this dict (not via the conftest fixture, since the tmp_path there is test-local) --
so it must live in tests/fixtures/ (an importable package whose names never start with `test_`,
exempt from the no-cross-test-import guard) rather than in the conftest alongside the fixture
that wraps it. MULTI_TAXONOMY and MULTI_FUNC_TAXONOMY are single-module-use (test_multi_pre_runtime.py
and test_fingerprint.py respectively) but are co-located here for a single taxonomy-data home.
"""

MINI_TAXONOMY = {
    "schema_version": 1,
    "taxonomy_version": 1,
    "function_to_category": {"validate_sloc_limits": "sloc_violation"},
    "log_pattern_to_category": [],
    "workflow_to_tier": {"CI": "CI"},
}

MULTI_TAXONOMY = {
    "schema_version": 1,
    "taxonomy_version": 1,
    "function_to_category": {
        "validate_sloc_limits": "sloc_violation",
        "validate_iam_runner_policy": "iam_policy_gap",
    },
    "log_pattern_to_category": [],
    "workflow_to_tier": {"CI": "CI"},
}

MULTI_FUNC_TAXONOMY = {
    "schema_version": 1,
    "taxonomy_version": 1,
    "function_to_category": {
        "validate_sloc_limits": "sloc_violation",
        "validate_iam_runner_policy": "iam_gap",
    },
    "log_pattern_to_category": [],
    "workflow_to_tier": {"CI": "CI"},
}
