"""generate_bundles + bundle-field/schema-version + schema-integration concern:
tests/ci_rca/evidence/test_generate.py (rec-2709 Wave 10).

Split from the former tests/test_ci_rca_evidence.py monolith: TestGenerateBundles,
TestNewBundleFields, TestSchemaVersion3, TestBundleToSchema. TestBundleToSchema's lazy `from
scripts.ops_data_portal import CiRcaContext` is a FIRST-PARTY import (not a heavy-dep NAME) -- no
marker (preserves the monolith's no-marker state).
"""

import json
from unittest.mock import patch

from scripts.ci_rca.evidence import _sha256_of, generate_bundles


class TestGenerateBundles:
    def test_happy_path(self, log_file, taxonomy_file):
        with patch("scripts.ci_rca.tier_map.probe_runtime", return_value=("median=50ms", 0.05)):
            with patch("scripts.ci_rca.tier_map.build_tier_membership", return_value={"validate_sloc_limits": ["presubmit"]}):
                bundles = generate_bundles(
                    log_file=log_file,
                    workflow_name="CI",
                    workflow_run_id=12345,
                    taxonomy_path=taxonomy_file,
                )
        assert len(bundles) == 1
        b = bundles[0]
        assert b["failed_check"] == "validate_sloc_limits"
        assert b["failure_category"] == "sloc_violation"
        sha = b.pop("sha256")
        assert len(sha) == 64
        recomputed = _sha256_of({**b, "sha256": sha})
        assert recomputed == sha

    def test_taxonomy_missing_returns_error_bundle(self, tmp_path, log_file):
        bundles = generate_bundles(
            log_file=log_file,
            workflow_name="CI",
            workflow_run_id=99,
            taxonomy_path=tmp_path / "nonexistent.yaml",
        )
        assert len(bundles) == 1
        assert "taxonomy_error" in bundles[0]
        assert bundles[0]["failure_category"] == "unknown"

    def test_sha_roundtrip(self, log_file, taxonomy_file):
        with patch("scripts.ci_rca.tier_map.probe_runtime", return_value=("median=50ms", 0.05)):
            with patch("scripts.ci_rca.tier_map.build_tier_membership", return_value={}):
                bundles = generate_bundles(
                    log_file=log_file,
                    workflow_name="CI",
                    workflow_run_id=1,
                    taxonomy_path=taxonomy_file,
                )
        b = bundles[0]
        sha_stored = b["sha256"]
        sha_recomputed = _sha256_of({k: v for k, v in b.items() if k != "sha256"})
        assert sha_stored == sha_recomputed

    def test_with_jobs_file(self, log_file, taxonomy_file, tmp_path):
        jobs_file = tmp_path / "jobs.json"
        jobs_file.write_text(json.dumps({"jobs": []}))
        with patch("scripts.ci_rca.tier_map.probe_runtime", return_value=("median=50ms", 0.05)):
            with patch("scripts.ci_rca.tier_map.build_tier_membership", return_value={}):
                bundles = generate_bundles(
                    log_file=log_file,
                    workflow_name="CI",
                    workflow_run_id=1,
                    jobs_file=jobs_file,
                    taxonomy_path=taxonomy_file,
                )
        assert len(bundles) == 1


class TestBundleToSchema:
    """Integration: bundle fields from generate_bundles() populate a valid CiRcaContext."""

    def test_bundle_to_schema(self, log_file, taxonomy_file):
        """generate_bundles() output feeds a composed CiRcaContext that model_validate accepts."""
        from scripts.ops_data_portal import CiRcaContext

        with patch("scripts.ci_rca.tier_map.probe_runtime", return_value=("median=30ms", 0.03)):
            with patch(
                "scripts.ci_rca.tier_map.build_tier_membership",
                return_value={"validate_sloc_limits": ["presubmit"]},
            ):
                bundles = generate_bundles(
                    log_file=log_file,
                    workflow_name="CI",
                    workflow_run_id=777,
                    taxonomy_path=taxonomy_file,
                )
        assert len(bundles) == 1
        bundle = bundles[0]

        earliest = bundle.get("earliest_viable_gate") or "CI"
        actual = bundle.get("actual_gate_that_caught_it") or "CI"

        ctx = {
            "schema_version": 1,
            "proximate_cause": (
                f"validate_sloc_limits() failed (check={bundle['failed_check']}, "
                f"category={bundle['failure_category']}): scripts/product.py is 810 SLOC, exceeds 500 limit."
            ),
            "why_chain": [
                "The file was committed without an incremental refactor plan.",
                "No --pre check caught this because validate_sloc_limits is presubmit-tier only.",
                "The tier placement at scripts/validate.py:2294 gates on scope=='all', unreachable from --pre.",
            ],
            "detection_gap": {
                "earliest_viable_gate": earliest,
                "actual_gate_that_caught_it": actual,
                "gap_explanation": (
                    f"Bundle's earliest_viable_gate={earliest!r} vs actual={actual!r}. "
                    f"Rationale: {bundle.get('earliest_viable_gate_rationale', 'N/A')[:100]}. "
                    "Gap is tier-placement at scripts/validate.py:2294."
                ),
            },
            "recurrence_class": "instance_of_known_pattern",
            "corrective_action": (
                "Add a complexity-waiver header or refactor the module below 500 SLOC "
                "to satisfy validate_sloc_limits() and unblock CI."
            ),
            "preventive_action": (
                "Promote validate_sloc_limits() to the --pre tier at scripts/validate.py so the "
                "check fires during local development and prevents the same pattern in future PRs."
            ),
            "evidence_bundle_ref": {
                "sha256": bundle["sha256"],
                "s3_uri": "s3://agent-platform-data-lake/ci-rca-evidence/" + bundle["sha256"] + ".json",
                "upload_status": "ok",
            },
        }

        validated = CiRcaContext.model_validate(ctx)
        assert validated.schema_version == 1
        assert validated.detection_gap.earliest_viable_gate == earliest


class TestNewBundleFields:
    """schema_version=3 and the new evidence fields are present in every bundle."""

    def test_schema_version_is_2(self, log_file, taxonomy_file):
        with patch("scripts.ci_rca.tier_map.probe_runtime", return_value=("median=50ms", 0.05)):
            with patch("scripts.ci_rca.tier_map.build_tier_membership", return_value={}):
                bundles = generate_bundles(
                    log_file=log_file,
                    workflow_name="CI",
                    workflow_run_id=1,
                    taxonomy_path=taxonomy_file,
                )
        assert bundles[0]["schema_version"] == 3

    def test_new_fields_present(self, log_file, taxonomy_file):
        with patch("scripts.ci_rca.tier_map.probe_runtime", return_value=("median=50ms", 0.05)):
            with patch("scripts.ci_rca.tier_map.build_tier_membership", return_value={}):
                bundles = generate_bundles(
                    log_file=log_file,
                    workflow_name="CI",
                    workflow_run_id=1,
                    taxonomy_path=taxonomy_file,
                )
        b = bundles[0]
        for field in ("vacuous_pass", "merge_gate_test_coverage", "gate_is_postmerge_canary", "coverage_regression"):
            assert field in b, f"bundle missing field {field!r}"

    def test_gate_is_postmerge_canary_true_for_ci(self, log_file, taxonomy_file):
        with patch("scripts.ci_rca.tier_map.probe_runtime", return_value=("median=50ms", 0.05)):
            with patch("scripts.ci_rca.tier_map.build_tier_membership", return_value={}):
                bundles = generate_bundles(
                    log_file=log_file,
                    workflow_name="CI",
                    workflow_run_id=1,
                    taxonomy_path=taxonomy_file,
                )
        assert bundles[0]["gate_is_postmerge_canary"] is True

    def test_gate_is_postmerge_canary_false_for_unknown_workflow(self, log_file, taxonomy_file):
        with patch("scripts.ci_rca.tier_map.probe_runtime", return_value=("median=50ms", 0.05)):
            with patch("scripts.ci_rca.tier_map.build_tier_membership", return_value={}):
                bundles = generate_bundles(
                    log_file=log_file,
                    workflow_name="UnknownWorkflow",
                    workflow_run_id=1,
                    taxonomy_path=taxonomy_file,
                )
        assert bundles[0]["gate_is_postmerge_canary"] is False

    def test_taxonomy_error_bundle_schema_version_is_2(self, tmp_path, log_file):
        bundles = generate_bundles(
            log_file=log_file,
            workflow_name="CI",
            workflow_run_id=99,
            taxonomy_path=tmp_path / "nonexistent.yaml",
        )
        assert bundles[0]["schema_version"] == 3


class TestSchemaVersion3:
    """c9/c10: schema_version=3 bundles include escape_mode."""

    def test_escape_mode_present_in_bundle(self, log_file, taxonomy_file):
        with patch("scripts.ci_rca.tier_map.probe_runtime", return_value=("median=50ms", 0.05)):
            with patch("scripts.ci_rca.tier_map.build_tier_membership", return_value={}):
                bundles = generate_bundles(
                    log_file=log_file,
                    workflow_name="CI",
                    workflow_run_id=1,
                    taxonomy_path=taxonomy_file,
                )
        b = bundles[0]
        assert b["schema_version"] == 3
        assert "escape_mode" in b

    def test_escape_mode_is_string(self, log_file, taxonomy_file):
        with patch("scripts.ci_rca.tier_map.probe_runtime", return_value=("median=50ms", 0.05)):
            with patch("scripts.ci_rca.tier_map.build_tier_membership", return_value={}):
                bundles = generate_bundles(
                    log_file=log_file,
                    workflow_name="CI",
                    workflow_run_id=1,
                    taxonomy_path=taxonomy_file,
                )
        assert isinstance(bundles[0]["escape_mode"], str)

    def test_taxonomy_error_bundle_has_escape_mode(self, tmp_path, log_file):
        bundles = generate_bundles(
            log_file=log_file,
            workflow_name="CI",
            workflow_run_id=99,
            taxonomy_path=tmp_path / "nonexistent.yaml",
        )
        b = bundles[0]
        assert "escape_mode" in b
        assert b["escape_mode"] == "undetermined"
