"""Tests for scripts/ci_rca_evidence.py (100% coverage)."""

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import scripts.ci_rca_taxonomy as taxonomy_mod  # noqa: E402
from scripts.ci_rca_evidence import (  # noqa: E402
    _canonical_json,
    _resolve_bucket,
    _sha256_of,
    _write_pending,
    generate_bundles,
    main,
    upload_and_persist,
)

MINI_TAXONOMY = {
    "schema_version": 1,
    "taxonomy_version": 1,
    "function_to_category": {"validate_sloc_limits": "sloc_violation"},
    "log_pattern_to_category": [],
    "workflow_to_tier": {"CI": "CI"},
}


@pytest.fixture(autouse=True)
def reset_taxonomy_cache():
    taxonomy_mod._TAXONOMY_CACHE = None
    yield
    taxonomy_mod._TAXONOMY_CACHE = None


@pytest.fixture
def taxonomy_file(tmp_path):
    p = tmp_path / "taxonomy.yaml"
    p.write_text(yaml.dump(MINI_TAXONOMY))
    return p


@pytest.fixture
def log_file(tmp_path):
    p = tmp_path / "ci-failed.log"
    p.write_text("validate_sloc_limits FAILED -- scripts/foo.py is 631 SLOC\n")
    return p


class TestCanonicalJson:
    def test_sort_keys(self):
        obj = {"b": 2, "a": 1}
        result = _canonical_json(obj)
        assert result == b'{"a":1,"b":2}'

    def test_no_spaces(self):
        obj = {"key": "val"}
        assert b" " not in _canonical_json(obj)

    def test_ensure_ascii(self):
        obj = {"k": "café"}
        result = _canonical_json(obj)
        assert b"\\u" in result

    def test_stability(self):
        obj = {"z": 3, "a": 1, "m": 2}
        assert _canonical_json(obj) == _canonical_json(obj)


class TestSha256Of:
    def test_excludes_sha256_field(self):
        obj = {"a": 1, "sha256": "xyz"}
        sha = _sha256_of(obj)
        obj2 = {"a": 1}
        assert sha == _sha256_of(obj2)

    def test_stability(self):
        obj = {"b": 2, "a": 1}
        assert _sha256_of(obj) == _sha256_of(obj)

    def test_hash_length(self):
        assert len(_sha256_of({"k": "v"})) == 64


class TestResolveBucket:
    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("S3_LOG_BUCKET", "my-bucket")
        assert _resolve_bucket() == "my-bucket"

    def test_env_override_strips_whitespace(self, monkeypatch):
        monkeypatch.setenv("S3_LOG_BUCKET", "  my-bucket  ")
        assert _resolve_bucket() == "my-bucket"

    def test_returns_string_without_env(self, monkeypatch):
        monkeypatch.delenv("S3_LOG_BUCKET", raising=False)
        result = _resolve_bucket()
        assert isinstance(result, str)


class TestWritePending:
    def test_creates_file(self, tmp_path):
        import scripts.ci_rca_evidence as ev_mod

        original = ev_mod._PENDING_DIR
        ev_mod._PENDING_DIR = tmp_path / "pending"
        try:
            bundle = {"a": 1, "sha256": "abc123"}
            dest = _write_pending(bundle, "abc123")
            assert dest.exists()
            data = json.loads(dest.read_bytes())
            assert data["a"] == 1
        finally:
            ev_mod._PENDING_DIR = original


class TestUploadAndPersist:
    def test_successful_upload(self, tmp_path):
        bundle = {"sha256": "a" * 64, "data": "x"}
        with patch("scripts.ci_rca_evidence._upload_to_s3") as mock_up:
            result = upload_and_persist(bundle, "my-bucket")
        assert result["upload_status"] == "ok"
        assert "my-bucket" in result["s3_uri"]
        mock_up.assert_called_once()

    def test_upload_failure_writes_pending(self, tmp_path):
        import scripts.ci_rca_evidence as ev_mod

        original = ev_mod._PENDING_DIR
        ev_mod._PENDING_DIR = tmp_path / "pending"
        try:
            bundle = {"sha256": "b" * 64, "data": "y"}
            with patch("scripts.ci_rca_evidence._upload_to_s3", side_effect=Exception("S3 down")):
                result = upload_and_persist(bundle, "my-bucket")
            assert result["upload_status"] == "upload_failed"
            assert result["s3_uri"] == ""
            assert Path(result["pending_path"]).exists()
        finally:
            ev_mod._PENDING_DIR = original

    def test_empty_bucket_writes_pending(self, tmp_path):
        import scripts.ci_rca_evidence as ev_mod

        original = ev_mod._PENDING_DIR
        ev_mod._PENDING_DIR = tmp_path / "pending"
        try:
            bundle = {"sha256": "c" * 64}
            result = upload_and_persist(bundle, "")
            assert result["upload_status"] == "upload_failed"
        finally:
            ev_mod._PENDING_DIR = original


class TestGenerateBundles:
    def test_happy_path(self, log_file, taxonomy_file):
        with patch("scripts.ci_rca_tier_map.probe_runtime", return_value=("median=50ms", 0.05)):
            with patch("scripts.ci_rca_tier_map.build_tier_membership", return_value={"validate_sloc_limits": ["presubmit"]}):
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
        with patch("scripts.ci_rca_tier_map.probe_runtime", return_value=("median=50ms", 0.05)):
            with patch("scripts.ci_rca_tier_map.build_tier_membership", return_value={}):
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
        with patch("scripts.ci_rca_tier_map.probe_runtime", return_value=("median=50ms", 0.05)):
            with patch("scripts.ci_rca_tier_map.build_tier_membership", return_value={}):
                bundles = generate_bundles(
                    log_file=log_file,
                    workflow_name="CI",
                    workflow_run_id=1,
                    jobs_file=jobs_file,
                    taxonomy_path=taxonomy_file,
                )
        assert len(bundles) == 1


class TestEmitDir:
    def test_emit_dir_writes_local_bundle(self, log_file, taxonomy_file, tmp_path, capsys):
        """--emit-dir writes <dir>/<sha>.json independent of S3 outcome and prints BUNDLE_LOCAL=<path>."""
        emit_dir = tmp_path / "emit"
        with patch("scripts.ci_rca_tier_map.probe_runtime", return_value=("median=50ms", 0.05)):
            with patch("scripts.ci_rca_tier_map.build_tier_membership", return_value={}):
                with patch("scripts.ci_rca_evidence._upload_to_s3"):
                    with patch("scripts.ci_rca_evidence._resolve_bucket", return_value="test-bucket"):
                        main(
                            [
                                "--log-file",
                                str(log_file),
                                "--workflow-name",
                                "CI",
                                "--workflow-run-id",
                                "42",
                                "--taxonomy-path",
                                str(taxonomy_file),
                                "--emit-dir",
                                str(emit_dir),
                            ]
                        )
        out = capsys.readouterr().out
        assert "BUNDLE_LOCAL=" in out
        local_line = next(ln for ln in out.splitlines() if ln.startswith("BUNDLE_LOCAL="))
        local_path = local_line.split("=", 1)[1]
        assert Path(local_path).exists()
        parsed = json.loads(Path(local_path).read_bytes())
        assert "sha256" in parsed
        assert len(parsed["sha256"]) == 64

    def test_emit_dir_writes_on_s3_failure(self, log_file, taxonomy_file, tmp_path, capsys):
        """--emit-dir writes the local bundle even when S3 upload fails."""
        import scripts.ci_rca_evidence as ev_mod

        emit_dir = tmp_path / "emit_fail"
        original_pending = ev_mod._PENDING_DIR
        ev_mod._PENDING_DIR = tmp_path / "pending"
        try:
            with patch("scripts.ci_rca_tier_map.probe_runtime", return_value=("median=50ms", 0.05)):
                with patch("scripts.ci_rca_tier_map.build_tier_membership", return_value={}):
                    with patch("scripts.ci_rca_evidence._upload_to_s3", side_effect=Exception("S3 down")):
                        with patch("scripts.ci_rca_evidence._resolve_bucket", return_value="test-bucket"):
                            main(
                                [
                                    "--log-file",
                                    str(log_file),
                                    "--workflow-name",
                                    "CI",
                                    "--workflow-run-id",
                                    "99",
                                    "--taxonomy-path",
                                    str(taxonomy_file),
                                    "--emit-dir",
                                    str(emit_dir),
                                ]
                            )
        finally:
            ev_mod._PENDING_DIR = original_pending
        out = capsys.readouterr().out
        assert "BUNDLE_LOCAL=" in out
        local_line = next(ln for ln in out.splitlines() if ln.startswith("BUNDLE_LOCAL="))
        local_path = local_line.split("=", 1)[1]
        assert Path(local_path).exists()
        parsed = json.loads(Path(local_path).read_bytes())
        assert "sha256" in parsed


class TestMain:
    def test_missing_log_file_exits(self, tmp_path):
        with pytest.raises(SystemExit) as exc_info:
            main(["--log-file", str(tmp_path / "nope.log"), "--workflow-name", "CI", "--workflow-run-id", "1"])
        assert exc_info.value.code != 0

    def test_print_bundle(self, log_file, taxonomy_file, capsys):
        with patch("scripts.ci_rca_tier_map.probe_runtime", return_value=("median=50ms", 0.05)):
            with patch("scripts.ci_rca_tier_map.build_tier_membership", return_value={}):
                with patch("scripts.ci_rca_evidence._upload_to_s3"):
                    with patch("scripts.ci_rca_evidence._resolve_bucket", return_value="test-bucket"):
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
                                "--print-bundle",
                            ]
                        )
        out = capsys.readouterr().out
        assert "BUNDLE_SHA=" in out


class TestBundleToSchema:
    """Integration: bundle fields from generate_bundles() populate a valid CiRcaContext."""

    def test_bundle_to_schema(self, log_file, taxonomy_file):
        """generate_bundles() output feeds a composed CiRcaContext that model_validate accepts."""
        from scripts.ops_data_portal import CiRcaContext

        with patch("scripts.ci_rca_tier_map.probe_runtime", return_value=("median=30ms", 0.03)):
            with patch(
                "scripts.ci_rca_tier_map.build_tier_membership",
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
        with patch("scripts.ci_rca_tier_map.probe_runtime", return_value=("median=50ms", 0.05)):
            with patch("scripts.ci_rca_tier_map.build_tier_membership", return_value={}):
                bundles = generate_bundles(
                    log_file=log_file,
                    workflow_name="CI",
                    workflow_run_id=1,
                    taxonomy_path=taxonomy_file,
                )
        assert bundles[0]["schema_version"] == 3

    def test_new_fields_present(self, log_file, taxonomy_file):
        with patch("scripts.ci_rca_tier_map.probe_runtime", return_value=("median=50ms", 0.05)):
            with patch("scripts.ci_rca_tier_map.build_tier_membership", return_value={}):
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
        with patch("scripts.ci_rca_tier_map.probe_runtime", return_value=("median=50ms", 0.05)):
            with patch("scripts.ci_rca_tier_map.build_tier_membership", return_value={}):
                bundles = generate_bundles(
                    log_file=log_file,
                    workflow_name="CI",
                    workflow_run_id=1,
                    taxonomy_path=taxonomy_file,
                )
        assert bundles[0]["gate_is_postmerge_canary"] is True

    def test_gate_is_postmerge_canary_false_for_unknown_workflow(self, log_file, taxonomy_file):
        with patch("scripts.ci_rca_tier_map.probe_runtime", return_value=("median=50ms", 0.05)):
            with patch("scripts.ci_rca_tier_map.build_tier_membership", return_value={}):
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
        with patch("scripts.ci_rca_tier_map.probe_runtime", return_value=("median=50ms", 0.05)):
            with patch("scripts.ci_rca_tier_map.build_tier_membership", return_value={}):
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
        with patch("scripts.ci_rca_tier_map.probe_runtime", return_value=("median=50ms", 0.05)):
            with patch("scripts.ci_rca_tier_map.build_tier_membership", return_value={}):
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


class TestMultiFailureEnumeration:
    """N distinct failed checks -> N bundles with distinct sha256 and shared workflow_run_id."""

    @pytest.fixture
    def multi_taxonomy_file(self, tmp_path):
        p = tmp_path / "multi_taxonomy.yaml"
        p.write_text(yaml.dump(MULTI_TAXONOMY))
        return p

    @pytest.fixture
    def multi_failure_log_file(self, tmp_path):
        p = tmp_path / "multi_failure.log"
        p.write_text(
            "validate_sloc_limits FAILED -- scripts/foo.py is 631 SLOC\n"
            "validate_iam_runner_policy FAILED -- missing iam:PutRolePolicy\n"
        )
        return p

    def test_multi_failure_enumeration_yields_n_bundles(self, multi_failure_log_file, multi_taxonomy_file):
        with patch("scripts.ci_rca_tier_map.probe_runtime", return_value=("median=50ms", 0.05)):
            with patch("scripts.ci_rca_tier_map.build_tier_membership", return_value={}):
                bundles = generate_bundles(
                    log_file=multi_failure_log_file,
                    workflow_name="CI",
                    workflow_run_id=42,
                    taxonomy_path=multi_taxonomy_file,
                )
        assert len(bundles) == 2

    def test_multi_failure_distinct_sha256(self, multi_failure_log_file, multi_taxonomy_file):
        with patch("scripts.ci_rca_tier_map.probe_runtime", return_value=("median=50ms", 0.05)):
            with patch("scripts.ci_rca_tier_map.build_tier_membership", return_value={}):
                bundles = generate_bundles(
                    log_file=multi_failure_log_file,
                    workflow_name="CI",
                    workflow_run_id=42,
                    taxonomy_path=multi_taxonomy_file,
                )
        shas = [b["sha256"] for b in bundles]
        assert len(set(shas)) == 2

    def test_multi_failure_shared_workflow_run_id(self, multi_failure_log_file, multi_taxonomy_file):
        with patch("scripts.ci_rca_tier_map.probe_runtime", return_value=("median=50ms", 0.05)):
            with patch("scripts.ci_rca_tier_map.build_tier_membership", return_value={}):
                bundles = generate_bundles(
                    log_file=multi_failure_log_file,
                    workflow_name="CI",
                    workflow_run_id=42,
                    taxonomy_path=multi_taxonomy_file,
                )
        assert all(b["workflow_run_id"] == 42 for b in bundles)

    def test_single_failure_still_yields_one_bundle(self, log_file, taxonomy_file):
        with patch("scripts.ci_rca_tier_map.probe_runtime", return_value=("median=50ms", 0.05)):
            with patch("scripts.ci_rca_tier_map.build_tier_membership", return_value={}):
                bundles = generate_bundles(
                    log_file=log_file,
                    workflow_name="CI",
                    workflow_run_id=1,
                    taxonomy_path=taxonomy_file,
                )
        assert len(bundles) == 1


class TestFingerprint:
    """CIRCA-03(a): grouping fingerprint determinism/distinctness (VP step 1)."""

    def test_fingerprint_present_and_hex64(self, log_file, taxonomy_file):
        with patch("scripts.ci_rca_tier_map.probe_runtime", return_value=("median=50ms", 0.05)):
            with patch("scripts.ci_rca_tier_map.build_tier_membership", return_value={}):
                bundles = generate_bundles(
                    log_file=log_file, workflow_name="CI", workflow_run_id=1, taxonomy_path=taxonomy_file
                )
        fp = bundles[0]["fingerprint"]
        assert isinstance(fp, str)
        assert len(fp) == 64
        int(fp, 16)  # must be valid hex

    def test_fingerprint_invariant_to_run_id_timestamp_head_sha(self, log_file, taxonomy_file):
        """Identical (workflow, failed_check, failure_category) with differing run_id yields the same fingerprint."""
        with patch("scripts.ci_rca_tier_map.probe_runtime", return_value=("median=50ms", 0.05)):
            with patch("scripts.ci_rca_tier_map.build_tier_membership", return_value={}):
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
        import scripts.ci_rca_evidence as ev_mod

        fp1 = ev_mod._compute_fingerprint("ci", "check_a", "sloc_violation")
        fp2 = ev_mod._compute_fingerprint("ci", "check_b", "sloc_violation")
        assert fp1 != fp2

    def test_fingerprint_distinct_across_failure_category(self):
        import scripts.ci_rca_evidence as ev_mod

        fp1 = ev_mod._compute_fingerprint("ci", "check_a", "sloc_violation")
        fp2 = ev_mod._compute_fingerprint("ci", "check_a", "iam_policy_gap")
        assert fp1 != fp2

    def test_fingerprint_deterministic_same_inputs(self):
        import scripts.ci_rca_evidence as ev_mod

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
        with patch("scripts.ci_rca_tier_map.probe_runtime", return_value=("median=50ms", 0.05)):
            with patch("scripts.ci_rca_tier_map.build_tier_membership", return_value={}):
                bundles = generate_bundles(
                    log_file=log_path, workflow_name="CI", workflow_run_id=42, taxonomy_path=taxonomy_path
                )
        fingerprints = [b["fingerprint"] for b in bundles]
        assert len(set(fingerprints)) == 2

    def test_slugify_workflow(self):
        import scripts.ci_rca_evidence as ev_mod

        assert ev_mod._slugify_workflow("CI") == "ci"
        assert ev_mod._slugify_workflow("Main Canary") == "main_canary"
        assert ev_mod._slugify_workflow("terraform-apply-sandbox") == "terraform-apply-sandbox"

    def test_first_error_signature_present(self, log_file, taxonomy_file):
        with patch("scripts.ci_rca_tier_map.probe_runtime", return_value=("median=50ms", 0.05)):
            with patch("scripts.ci_rca_tier_map.build_tier_membership", return_value={}):
                bundles = generate_bundles(
                    log_file=log_file, workflow_name="CI", workflow_run_id=1, taxonomy_path=taxonomy_file
                )
        assert "first_error_signature" in bundles[0]
        assert isinstance(bundles[0]["first_error_signature"], str)

    def test_first_error_signature_normalizes_digits(self):
        import scripts.ci_rca_evidence as ev_mod

        sig = ev_mod._normalize_first_error_signature(
            "validate_sloc_limits FAILED -- foo.py is 631 SLOC\n", "validate_sloc_limits"
        )
        assert "631" not in sig
        assert "#" in sig

    def test_main_prints_fingerprint(self, log_file, taxonomy_file, capsys):
        with patch("scripts.ci_rca_tier_map.probe_runtime", return_value=("median=50ms", 0.05)):
            with patch("scripts.ci_rca_tier_map.build_tier_membership", return_value={}):
                with patch("scripts.ci_rca_evidence._upload_to_s3"):
                    with patch("scripts.ci_rca_evidence._resolve_bucket", return_value="test-bucket"):
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


@pytest.mark.skipif(not os.environ.get("RUN_LIVE_S3"), reason="RUN_LIVE_S3 not set")
@pytest.mark.integration
class TestLiveS3Roundtrip:
    @pytest.mark.integration
    @pytest.mark.enable_socket
    def test_live_s3_roundtrip(self, log_file, tmp_path):
        import boto3  # noqa: PLC0415, I001
        from scripts.ci_rca_evidence import _EVIDENCE_PREFIX, _resolve_bucket, generate_bundles  # noqa: PLC0415

        taxonomy_file = tmp_path / "taxonomy.yaml"
        taxonomy_file.write_text(yaml.dump(MINI_TAXONOMY))

        with patch("scripts.ci_rca_tier_map.probe_runtime", return_value=("median=50ms", 0.05)):
            with patch("scripts.ci_rca_tier_map.build_tier_membership", return_value={}):
                bundles = generate_bundles(
                    log_file=log_file,
                    workflow_name="CI",
                    workflow_run_id=0,
                    taxonomy_path=taxonomy_file,
                )
        b = bundles[0]
        sha = b["sha256"]
        bucket = _resolve_bucket()
        assert bucket, "Could not resolve S3 bucket"

        key = f"{_EVIDENCE_PREFIX}/{sha}.json"
        body = json.dumps(b, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")

        profile = os.environ.get("AWS_PROFILE")
        session = boto3.Session(profile_name=profile) if profile else boto3.Session()
        s3 = session.client("s3", region_name="eu-west-2")

        s3.put_object(Bucket=bucket, Key=key, Body=body, ContentType="application/json")
        try:
            head = s3.head_object(Bucket=bucket, Key=key)
            assert head["ContentLength"] == len(body)
            response = s3.get_object(Bucket=bucket, Key=key)
            downloaded = response["Body"].read()
            assert downloaded == body
        finally:
            s3.delete_object(Bucket=bucket, Key=key)
