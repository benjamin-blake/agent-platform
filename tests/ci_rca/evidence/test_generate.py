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


class TestV2FingerprintBundleFields:
    """ci-rca-identity-lifecycle: v2 fingerprint + affected_nodeids bundle-shape expectations."""

    def test_fingerprint_version_is_2(self, log_file, taxonomy_file):
        with patch("scripts.ci_rca.tier_map.probe_runtime", return_value=("median=50ms", 0.05)):
            with patch("scripts.ci_rca.tier_map.build_tier_membership", return_value={}):
                bundles = generate_bundles(
                    log_file=log_file, workflow_name="CI", workflow_run_id=1, taxonomy_path=taxonomy_file
                )
        assert bundles[0]["fingerprint_version"] == 2

    def test_error_signature_and_affected_nodeids_present(self, log_file, taxonomy_file):
        with patch("scripts.ci_rca.tier_map.probe_runtime", return_value=("median=50ms", 0.05)):
            with patch("scripts.ci_rca.tier_map.build_tier_membership", return_value={}):
                bundles = generate_bundles(
                    log_file=log_file, workflow_name="CI", workflow_run_id=1, taxonomy_path=taxonomy_file
                )
        b = bundles[0]
        assert "error_signature" in b
        assert isinstance(b["error_signature"], str) and b["error_signature"]
        assert "affected_nodeids" in b
        assert isinstance(b["affected_nodeids"], list)

    def test_taxonomy_error_bundle_carries_v2_fields(self, tmp_path, log_file):
        bundles = generate_bundles(
            log_file=log_file, workflow_name="CI", workflow_run_id=99, taxonomy_path=tmp_path / "nonexistent.yaml"
        )
        b = bundles[0]
        assert b["fingerprint_version"] == 2
        assert "error_signature" in b
        assert b["affected_nodeids"] == []

    def test_junit_file_produces_junit_classification_source(self, tmp_path, taxonomy_file):
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
        log_path.write_text("validate_sloc_limits FAILED -- scripts/foo.py is 631 SLOC\n")

        with patch("scripts.ci_rca.tier_map.probe_runtime", return_value=("median=50ms", 0.05)):
            with patch("scripts.ci_rca.tier_map.build_tier_membership", return_value={}):
                bundles = generate_bundles(
                    log_file=log_path,
                    workflow_name="CI",
                    workflow_run_id=1,
                    taxonomy_path=taxonomy_file,
                    junit_path=junit_path,
                )
        assert len(bundles) == 1
        assert bundles[0]["classification_source"] == "junit"
        assert bundles[0]["affected_nodeids"] == ["tests/test_a.py::test_a"]

    def test_escape_class_absent_without_selection_manifest(self, log_file, taxonomy_file):
        with patch("scripts.ci_rca.tier_map.probe_runtime", return_value=("median=50ms", 0.05)):
            with patch("scripts.ci_rca.tier_map.build_tier_membership", return_value={}):
                bundles = generate_bundles(
                    log_file=log_file, workflow_name="CI", workflow_run_id=1, taxonomy_path=taxonomy_file
                )
        assert "escape_class" not in bundles[0]

    def test_escape_class_present_with_selection_manifest(self, tmp_path, taxonomy_file):
        import json

        log_path = tmp_path / "log.txt"
        log_path.write_text("validate_sloc_limits FAILED -- scripts/foo.py is 631 SLOC\n")
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(json.dumps({"selected": [], "deferred": []}))

        with patch("scripts.ci_rca.tier_map.probe_runtime", return_value=("median=50ms", 0.05)):
            with patch("scripts.ci_rca.tier_map.build_tier_membership", return_value={}):
                bundles = generate_bundles(
                    log_file=log_path,
                    workflow_name="CI",
                    workflow_run_id=1,
                    taxonomy_path=taxonomy_file,
                    selection_manifest_path=manifest_path,
                )
        assert bundles[0]["escape_class"] == "no-edge"

    def test_junit_parse_failure_falls_back_to_log_tail(self, tmp_path, taxonomy_file):
        """A malformed junit file must never crash bundle generation -- falls back loudly."""
        junit_path = tmp_path / "junit.xml"
        junit_path.write_text("not valid xml <<<")
        log_path = tmp_path / "log.txt"
        log_path.write_text("validate_sloc_limits FAILED -- scripts/foo.py is 631 SLOC\n")

        with patch("scripts.ci_rca.tier_map.probe_runtime", return_value=("median=50ms", 0.05)):
            with patch("scripts.ci_rca.tier_map.build_tier_membership", return_value={}):
                bundles = generate_bundles(
                    log_file=log_path,
                    workflow_name="CI",
                    workflow_run_id=1,
                    taxonomy_path=taxonomy_file,
                    junit_path=junit_path,
                )
        assert len(bundles) == 1
        assert bundles[0]["classification_source"] == "log_tail"

    def test_collection_error_bundle_via_real_taxonomy(self, tmp_path):
        """End-to-end through the REAL config/ci_rca_taxonomy.yaml collection_error entry
        (added by this change) -- exercises _collecting_module_paths + the collection_entries
        branch of _resolve_error_signatures, not just the standalone fingerprint unit."""
        log_path = tmp_path / "log.txt"
        log_path.write_text(
            "ERROR collecting tests/test_broken_module.py ___________________\n"
            "ImportError while importing test module 'tests/test_broken_module.py'.\n"
            "ModuleNotFoundError: No module named 'nonexistent_module'\n"
        )
        with patch("scripts.ci_rca.tier_map.probe_runtime", return_value=("median=50ms", 0.05)):
            with patch("scripts.ci_rca.tier_map.build_tier_membership", return_value={}):
                bundles = generate_bundles(log_file=log_path, workflow_name="CI", workflow_run_id=1)
        assert len(bundles) == 1
        b = bundles[0]
        assert b["failure_category"] == "collection_error"
        assert b["failed_check"] == "tests/test_broken_module.py"
        assert b["error_signature"] == "collection_error::tests/test_broken_module.py"
        assert b["classification_source"] == "collection_error_module_path"

    def test_malformed_selection_manifest_degrades_to_no_escape_class(self, tmp_path, taxonomy_file):
        """A malformed selection-manifest file must never crash bundle generation -- degrades
        to no escape_class, loud-logged, never raised."""
        log_path = tmp_path / "log.txt"
        log_path.write_text("validate_sloc_limits FAILED -- scripts/foo.py is 631 SLOC\n")
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text("not valid json {{{")

        with patch("scripts.ci_rca.tier_map.probe_runtime", return_value=("median=50ms", 0.05)):
            with patch("scripts.ci_rca.tier_map.build_tier_membership", return_value={}):
                bundles = generate_bundles(
                    log_file=log_path,
                    workflow_name="CI",
                    workflow_run_id=1,
                    taxonomy_path=taxonomy_file,
                    selection_manifest_path=manifest_path,
                )
        assert "escape_class" not in bundles[0]

    def test_mass_failure_collapse_via_generate_bundles(self, tmp_path):
        """More than ~5 distinct junit-parsed cause-groups in one run collapse to ONE
        run-level bundle -- exercises generate_bundles' own mass-collapse branch, not just the
        standalone collapse_mass_failure() unit."""
        testcases = []
        for i in range(8):
            testcases.append(
                f'<testcase classname="tests.test_{i}" name="test_{i}" file="tests/test_{i}.py">'
                f'<failure message="AssertionError: distinct failure {i}" type="AssertionError">'
                "Traceback (most recent call last):\n"
                f'  File "tests/test_{i}.py", line 3, in test_{i}\n'
                f"    assert False, 'distinct failure {i}'\n"
                "</failure></testcase>"
            )
        junit_xml = f'<?xml version="1.0"?><testsuites><testsuite>{"".join(testcases)}</testsuite></testsuites>'
        junit_path = tmp_path / "junit.xml"
        junit_path.write_text(junit_xml)
        log_path = tmp_path / "log.txt"
        log_path.write_text("validate_sloc_limits FAILED -- scripts/foo.py is 631 SLOC\n")

        with patch("scripts.ci_rca.tier_map.probe_runtime", return_value=("median=50ms", 0.05)):
            with patch("scripts.ci_rca.tier_map.build_tier_membership", return_value={}):
                bundles = generate_bundles(
                    log_file=log_path,
                    workflow_name="CI",
                    workflow_run_id=1,
                    junit_path=junit_path,
                )
        assert len(bundles) == 1
        b = bundles[0]
        assert b["failed_check"] == "mass_failure"
        assert b["classification_source"] == "mass_failure_collapse"
        assert b["error_signature"].startswith("mass_failure::8_signatures::")
        assert len(b["affected_nodeids"]) == 8

    def test_mass_failure_collapse_carries_escape_class(self, tmp_path, taxonomy_file):
        """The mass-collapse branch also threads selection_manifest_path through to
        escape_class -- exercises _escape_class_for's call inside that branch specifically."""
        import json

        testcases = []
        for i in range(8):
            testcases.append(
                f'<testcase classname="tests.test_{i}" name="test_{i}" file="tests/test_{i}.py">'
                f'<failure message="AssertionError: distinct failure {i}" type="AssertionError">'
                "Traceback (most recent call last):\n"
                f'  File "tests/test_{i}.py", line 3, in test_{i}\n'
                f"    assert False, 'distinct failure {i}'\n"
                "</failure></testcase>"
            )
        junit_xml = f'<?xml version="1.0"?><testsuites><testsuite>{"".join(testcases)}</testsuite></testsuites>'
        junit_path = tmp_path / "junit.xml"
        junit_path.write_text(junit_xml)
        log_path = tmp_path / "log.txt"
        log_path.write_text("validate_sloc_limits FAILED -- scripts/foo.py is 631 SLOC\n")
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(json.dumps({"selected": ["tests/test_0.py"], "deferred": []}))

        with patch("scripts.ci_rca.tier_map.probe_runtime", return_value=("median=50ms", 0.05)):
            with patch("scripts.ci_rca.tier_map.build_tier_membership", return_value={}):
                bundles = generate_bundles(
                    log_file=log_path,
                    workflow_name="CI",
                    workflow_run_id=1,
                    junit_path=junit_path,
                    taxonomy_path=taxonomy_file,
                    selection_manifest_path=manifest_path,
                )
        assert bundles[0]["escape_class"] == "unknown-data-edge"


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
