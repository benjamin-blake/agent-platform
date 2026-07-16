"""grouping-fingerprint + slugify + first-error-signature + single-bundle fan-out concern:
tests/ci_rca/evidence/test_fingerprint.py (rec-2709 Wave 10).

Split from the former tests/test_ci_rca_evidence.py monolith: TestFingerprint,
TestBundleEmissionFanOut (MULTI_FUNC_TAXONOMY imported from the shared fixtures helper -- it is
single-use here).
"""

import json
from unittest.mock import patch

import yaml

from scripts.ci_rca.evidence import generate_bundles, main
from tests.fixtures.ci_rca.evidence_taxonomies import MULTI_FUNC_TAXONOMY


class TestFingerprint:
    """CIRCA-03(a): grouping fingerprint determinism/distinctness (VP step 1)."""

    def test_fingerprint_present_and_hex64(self, log_file, taxonomy_file):
        with patch("scripts.ci_rca.tier_map.probe_runtime", return_value=("median=50ms", 0.05)):
            with patch("scripts.ci_rca.tier_map.build_tier_membership", return_value={}):
                bundles = generate_bundles(
                    log_file=log_file, workflow_name="CI", workflow_run_id=1, taxonomy_path=taxonomy_file
                )
        fp = bundles[0]["fingerprint"]
        assert isinstance(fp, str)
        assert len(fp) == 64
        int(fp, 16)  # must be valid hex

    def test_fingerprint_invariant_to_run_id_timestamp_head_sha(self, log_file, taxonomy_file):
        """Identical (workflow, failed_check, failure_category) with differing run_id yields the same fingerprint."""
        with patch("scripts.ci_rca.tier_map.probe_runtime", return_value=("median=50ms", 0.05)):
            with patch("scripts.ci_rca.tier_map.build_tier_membership", return_value={}):
                bundles_a = generate_bundles(
                    log_file=log_file, workflow_name="CI", workflow_run_id=111, taxonomy_path=taxonomy_file
                )
                bundles_b = generate_bundles(
                    log_file=log_file, workflow_name="CI", workflow_run_id=999999, taxonomy_path=taxonomy_file
                )
        assert bundles_a[0]["fingerprint"] == bundles_b[0]["fingerprint"]
        # workflow_run_id (a run-only field) still differs -- proves the perturbation was real.
        assert bundles_a[0]["workflow_run_id"] != bundles_b[0]["workflow_run_id"]

    def test_fingerprint_distinct_across_failed_check(self):
        import scripts.ci_rca.evidence as ev_mod

        fp1 = ev_mod._compute_fingerprint("ci", "check_a", "sloc_violation")
        fp2 = ev_mod._compute_fingerprint("ci", "check_b", "sloc_violation")
        assert fp1 != fp2

    def test_fingerprint_distinct_across_failure_category(self):
        import scripts.ci_rca.evidence as ev_mod

        fp1 = ev_mod._compute_fingerprint("ci", "check_a", "sloc_violation")
        fp2 = ev_mod._compute_fingerprint("ci", "check_a", "iam_policy_gap")
        assert fp1 != fp2

    def test_fingerprint_deterministic_same_inputs(self):
        import scripts.ci_rca.evidence as ev_mod

        assert ev_mod._compute_fingerprint("ci", "check_a", "sloc_violation") == ev_mod._compute_fingerprint(
            "ci", "check_a", "sloc_violation"
        )

    def test_taxonomy_error_bundle_has_fingerprint(self, tmp_path, log_file):
        bundles = generate_bundles(
            log_file=log_file, workflow_name="CI", workflow_run_id=99, taxonomy_path=tmp_path / "nonexistent.yaml"
        )
        assert "fingerprint" in bundles[0]
        assert len(bundles[0]["fingerprint"]) == 64

    def test_multi_failure_distinct_fingerprints(self, tmp_path):
        multi_taxonomy = {
            "schema_version": 1,
            "taxonomy_version": 1,
            "function_to_category": {
                "validate_sloc_limits": "sloc_violation",
                "validate_iam_runner_policy": "iam_policy_gap",
            },
            "log_pattern_to_category": [],
            "workflow_to_tier": {"CI": "CI"},
        }
        taxonomy_path = tmp_path / "multi.yaml"
        taxonomy_path.write_text(yaml.dump(multi_taxonomy))
        log_path = tmp_path / "multi.log"
        log_path.write_text(
            "validate_sloc_limits FAILED -- scripts/foo.py is 631 SLOC\n"
            "validate_iam_runner_policy FAILED -- missing iam:PutRolePolicy\n"
        )
        jobs_path = tmp_path / "multi_jobs.json"
        jobs_path.write_text(
            json.dumps(
                {
                    "jobs": [
                        {
                            "name": "validate",
                            "steps": [
                                {"name": "validate_sloc_limits", "conclusion": "failure"},
                                {"name": "validate_iam_runner_policy", "conclusion": "failure"},
                            ],
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
                    workflow_run_id=42,
                    jobs_file=jobs_path,
                    taxonomy_path=taxonomy_path,
                )
        fingerprints = [b["fingerprint"] for b in bundles]
        assert len(set(fingerprints)) == 2

    def test_slugify_workflow(self):
        import scripts.ci_rca.evidence as ev_mod

        assert ev_mod._slugify_workflow("CI") == "ci"
        assert ev_mod._slugify_workflow("Main Canary") == "main_canary"
        assert ev_mod._slugify_workflow("terraform-apply-sandbox") == "terraform-apply-sandbox"

    def test_first_error_signature_present(self, log_file, taxonomy_file):
        with patch("scripts.ci_rca.tier_map.probe_runtime", return_value=("median=50ms", 0.05)):
            with patch("scripts.ci_rca.tier_map.build_tier_membership", return_value={}):
                bundles = generate_bundles(
                    log_file=log_file, workflow_name="CI", workflow_run_id=1, taxonomy_path=taxonomy_file
                )
        assert "first_error_signature" in bundles[0]
        assert isinstance(bundles[0]["first_error_signature"], str)

    def test_first_error_signature_normalizes_digits(self):
        import scripts.ci_rca.evidence as ev_mod

        sig = ev_mod._normalize_first_error_signature(
            "validate_sloc_limits FAILED -- foo.py is 631 SLOC\n", "validate_sloc_limits"
        )
        assert "631" not in sig
        assert "#" in sig

    def test_main_prints_fingerprint(self, log_file, taxonomy_file, capsys):
        with patch("scripts.ci_rca.tier_map.probe_runtime", return_value=("median=50ms", 0.05)):
            with patch("scripts.ci_rca.tier_map.build_tier_membership", return_value={}):
                with patch("scripts.ci_rca.evidence._upload_to_s3"):
                    with patch("scripts.ci_rca.evidence._resolve_bucket", return_value="test-bucket"):
                        main(
                            [
                                "--log-file",
                                str(log_file),
                                "--workflow-name",
                                "CI",
                                "--workflow-run-id",
                                "1",
                                "--taxonomy-path",
                                str(taxonomy_file),
                            ]
                        )
        out = capsys.readouterr().out
        assert "FINGERPRINT=" in out
        fp_line = next(ln for ln in out.splitlines() if ln.startswith("FINGERPRINT="))
        assert len(fp_line.split("=", 1)[1]) == 64


class TestBundleEmissionFanOut:
    """generate_bundles() end-to-end regression test (2026-07 incident): a single failing check
    must not fan out into multiple bundles just because its FULL job log mentions other,
    unrelated validate_* function names from checks that ran and passed earlier in the same job.
    Genuine multi-category preservation is covered by TestMultiFailureEnumeration /
    TestFingerprint.test_multi_failure_distinct_fingerprints (jobs-JSON-driven)."""

    def test_single_failing_check_emits_exactly_one_bundle(self, tmp_path):
        taxonomy_file = tmp_path / "taxonomy.yaml"
        taxonomy_file.write_text(yaml.dump(MULTI_FUNC_TAXONOMY))
        log_file = tmp_path / "ci-failed.log"
        log_file.write_text(
            "Running validate_iam_runner_policy... PASS\nvalidate_sloc_limits FAILED -- scripts/foo.py is 631 SLOC\n"
        )
        with patch("scripts.ci_rca.tier_map.probe_runtime", return_value=("median=50ms", 0.05)):
            with patch("scripts.ci_rca.tier_map.build_tier_membership", return_value={}):
                bundles = generate_bundles(
                    log_file=log_file,
                    workflow_name="CI",
                    workflow_run_id=1,
                    taxonomy_path=taxonomy_file,
                )
        assert len(bundles) == 1
