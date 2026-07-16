"""Live-S3 integration roundtrip concern: tests/ci_rca/evidence/test_live_s3.py (rec-2709 Wave 10).

Split from the former tests/test_ci_rca_evidence.py monolith: TestLiveS3Roundtrip (skipif
RUN_LIVE_S3 unset + @integration). The ONLY heavy-dep module in this wave: it does a lazy `import
boto3` + boto3.Session inside the test. Module-level `import boto3  # noqa: F401` marker (the
convergence_health-style comment) so the fast tier's --collect-only collectability partition
(scripts/checks/_scaffolding.py) proactively defers this file to the full tier (boto3 excluded
from requirements-fast.txt) instead of crashing.
"""

import json
import os
from unittest.mock import patch

import boto3  # noqa: F401  -- heavy-dep marker: proactively defers this file to the full tier
import pytest
import yaml

from tests.fixtures.ci_rca.evidence_taxonomies import MINI_TAXONOMY


@pytest.mark.skipif(not os.environ.get("RUN_LIVE_S3"), reason="RUN_LIVE_S3 not set")
@pytest.mark.integration
class TestLiveS3Roundtrip:
    @pytest.mark.integration
    @pytest.mark.enable_socket
    def test_live_s3_roundtrip(self, log_file, tmp_path):
        import boto3  # noqa: PLC0415, I001, F811
        from scripts.ci_rca.evidence import _EVIDENCE_PREFIX, _resolve_bucket, generate_bundles  # noqa: PLC0415

        taxonomy_file = tmp_path / "taxonomy.yaml"
        taxonomy_file.write_text(yaml.dump(MINI_TAXONOMY))

        with patch("scripts.ci_rca.tier_map.probe_runtime", return_value=("median=50ms", 0.05)):
            with patch("scripts.ci_rca.tier_map.build_tier_membership", return_value={}):
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
