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
