"""generate_bundles Priority-0 attribution + evidence_insufficient refusal integration
(ci-rca-evidence-fidelity). Split from test_generate.py to hold the 500-SLOC budget -- same
concern-split package (tests/ci_rca/evidence/), so coverage of scripts/ci_rca/evidence stays
whole-package measured.
"""

import json
from unittest.mock import patch

from scripts.ci_rca.evidence import generate_bundles

_ATTRIBUTION_TAXONOMY = {
    "schema_version": 1,
    "taxonomy_version": 1,
    "function_to_category": {
        "validate_test_coverage": "code_regression",
        "validate_sloc_limits": "sloc_violation",
    },
    "step_name_to_category": {
        "Validate full tier (ruff, mypy, pytest, DQ runner, verifier harness)": "code_regression",
    },
    "log_pattern_to_category": [],
    "workflow_to_tier": {"CI": "CI"},
}


class TestPriorityZeroAndRefusalIntegration:
    """ci-rca-evidence-fidelity: generate_bundles end to end -- the PRODUCTION entry point
    (via classify_failures) -- with the validation-result attribution artifact present, and the
    evidence_insufficient refusal routed to its degenerate fingerprint."""

    def _taxonomy_file(self, tmp_path):
        import yaml

        p = tmp_path / "attribution-taxonomy.yaml"
        p.write_text(yaml.dump(_ATTRIBUTION_TAXONOMY))
        return p

    def _validation_result_file(self, tmp_path, attributions):
        p = tmp_path / "validation-result.json"
        p.write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "exit_code": 1,
                    "failed_checks": [a["label"] for a in attributions],
                    "failed_check_attributions": attributions,
                }
            )
        )
        return p

    def test_step_name_collision_bundle_names_real_failed_check(self, tmp_path):
        """THE regression this plan exists to fix: jobs.json's failed step name is the full-tier
        aggregate step name (a step_name_to_category key that would otherwise win at Priority 1),
        but the validation-result artifact is present -- the emitted bundle must still report
        failed_check == "validate_test_coverage", not the CI step name."""
        log_path = tmp_path / "log.txt"
        log_path.write_text("=== Validation Summary (scope: all) ===\nFailed checks:\n  - Coverage below 100%\n")
        vr = self._validation_result_file(tmp_path, [{"check": "validate_test_coverage", "label": "Coverage below 100%"}])
        jobs_file = tmp_path / "jobs.json"
        jobs_file.write_text(
            json.dumps(
                {
                    "jobs": [
                        {
                            "steps": [
                                {
                                    "name": "Validate full tier (ruff, mypy, pytest, DQ runner, verifier harness)",
                                    "conclusion": "failure",
                                }
                            ]
                        }
                    ]
                }
            )
        )
        with patch("scripts.ci_rca.tier_map.probe_runtime", return_value=("median=50ms", 0.05)):
            with patch("scripts.ci_rca.tier_map.build_tier_membership", return_value={}):
                bundles = generate_bundles(
                    log_file=log_path,
                    workflow_name="CI",
                    workflow_run_id=1,
                    jobs_file=jobs_file,
                    taxonomy_path=self._taxonomy_file(tmp_path),
                    validation_result_path=vr,
                )
        assert len(bundles) == 1
        assert bundles[0]["failed_check"] == "validate_test_coverage"
        assert bundles[0]["failure_category"] == "code_regression"

    def test_n_attributions_enumerate_to_n_bundles(self, tmp_path):
        log_path = tmp_path / "log.txt"
        log_path.write_text("irrelevant log\n")
        vr = self._validation_result_file(
            tmp_path,
            [
                {"check": "validate_test_coverage", "label": "Coverage below 100%"},
                {"check": "validate_sloc_limits", "label": "SLOC limits (Decision 43)"},
            ],
        )
        with patch("scripts.ci_rca.tier_map.probe_runtime", return_value=("median=50ms", 0.05)):
            with patch("scripts.ci_rca.tier_map.build_tier_membership", return_value={}):
                bundles = generate_bundles(
                    log_file=log_path,
                    workflow_name="CI",
                    workflow_run_id=1,
                    taxonomy_path=self._taxonomy_file(tmp_path),
                    validation_result_path=vr,
                )
        assert len(bundles) == 2
        assert {b["failed_check"] for b in bundles} == {"validate_test_coverage", "validate_sloc_limits"}
        assert {b["failure_category"] for b in bundles} == {"code_regression", "sloc_violation"}

    def test_evidence_insufficient_refusal_end_to_end(self, tmp_path, taxonomy_file):
        """The rec-2958 false-positive shape: incomplete evidence, no attribution artifact, no
        junit -- must refuse rather than substring-match the passing mention, and the refusal
        must fingerprint on the degenerate evidence_insufficient::<truncation_reason> signature."""
        log_path = tmp_path / "log.txt"
        log_path.write_text("  [PASS] validate_sloc_limits: ok\n")
        with patch("scripts.ci_rca.tier_map.probe_runtime", return_value=("median=50ms", 0.05)):
            with patch("scripts.ci_rca.tier_map.build_tier_membership", return_value={}):
                bundles = generate_bundles(
                    log_file=log_path,
                    workflow_name="CI",
                    workflow_run_id=1,
                    taxonomy_path=taxonomy_file,
                    retrieval_limits={"complete": False, "truncation_reason": "byte_limit"},
                )
        assert len(bundles) == 1
        b = bundles[0]
        assert b["failure_category"] == "evidence_insufficient"
        assert b["failed_check"] == "evidence_insufficient"
        assert b["classification_source"] == "evidence_insufficient_refusal"
        assert b["error_signature"] == "evidence_insufficient::byte_limit"

    def test_evidence_insufficient_refusal_stands_down_with_junit(self, tmp_path, taxonomy_file):
        """A junit cause-group must win over the refusal (Decision 142 anti-masking) even when
        evidence is otherwise incomplete."""
        junit_xml = (
            '<?xml version="1.0"?><testsuites><testsuite>'
            '<testcase classname="tests.test_a" name="test_a" file="tests/test_a.py">'
            '<failure message="AssertionError: x" type="AssertionError">'
            "Traceback (most recent call last):\n"
            '  File "tests/test_a.py", line 3, in test_a\n'
            "    assert False\n"
            "</failure></testcase></testsuite></testsuites>"
        )
        junit_path = tmp_path / "junit.xml"
        junit_path.write_text(junit_xml)
        log_path = tmp_path / "log.txt"
        log_path.write_text("  [PASS] validate_sloc_limits: ok\n")
        with patch("scripts.ci_rca.tier_map.probe_runtime", return_value=("median=50ms", 0.05)):
            with patch("scripts.ci_rca.tier_map.build_tier_membership", return_value={}):
                bundles = generate_bundles(
                    log_file=log_path,
                    workflow_name="CI",
                    workflow_run_id=1,
                    taxonomy_path=taxonomy_file,
                    junit_path=junit_path,
                    retrieval_limits={"complete": False, "truncation_reason": "byte_limit"},
                )
        assert len(bundles) == 1
        assert bundles[0]["classification_source"] == "junit"
        assert bundles[0]["failure_category"] != "evidence_insufficient"

    def test_complete_evidence_never_refuses(self, tmp_path, taxonomy_file):
        log_path = tmp_path / "log.txt"
        log_path.write_text("validate_sloc_limits FAILED\n")
        with patch("scripts.ci_rca.tier_map.probe_runtime", return_value=("median=50ms", 0.05)):
            with patch("scripts.ci_rca.tier_map.build_tier_membership", return_value={}):
                bundles = generate_bundles(
                    log_file=log_path,
                    workflow_name="CI",
                    workflow_run_id=1,
                    taxonomy_path=taxonomy_file,
                    retrieval_limits={"complete": True, "truncation_reason": None},
                )
        assert bundles[0]["failure_category"] == "sloc_violation"
