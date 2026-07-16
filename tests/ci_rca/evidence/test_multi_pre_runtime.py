"""multi-failure enumeration + pre-runtime env-stamp concern:
tests/ci_rca/evidence/test_multi_pre_runtime.py (rec-2709 Wave 10).

Split from the former tests/test_ci_rca_evidence.py monolith: TestMultiFailureEnumeration
(imports MULTI_TAXONOMY from the shared fixtures helper), TestPreRuntimeStamp.
"""

import json
from unittest.mock import patch

import pytest
import yaml

from scripts.ci_rca.evidence import _resolve_current_pre_runtime, generate_bundles
from tests.fixtures.ci_rca.evidence_taxonomies import MULTI_TAXONOMY


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

    @pytest.fixture
    def multi_failure_jobs_file(self, tmp_path):
        """Genuine multi-category evidence: two DISTINCT GitHub Actions steps both reporting
        conclusion=failure -- jobs-JSON is the only reliable multi-failure enumeration signal
        (log-text substring matches alone no longer fan out; see TestBundleEmissionFanOut)."""
        p = tmp_path / "multi_failure_jobs.json"
        p.write_text(
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
        return p

    def test_multi_failure_enumeration_yields_n_bundles(
        self, multi_failure_log_file, multi_failure_jobs_file, multi_taxonomy_file
    ):
        with patch("scripts.ci_rca.tier_map.probe_runtime", return_value=("median=50ms", 0.05)):
            with patch("scripts.ci_rca.tier_map.build_tier_membership", return_value={}):
                bundles = generate_bundles(
                    log_file=multi_failure_log_file,
                    workflow_name="CI",
                    workflow_run_id=42,
                    jobs_file=multi_failure_jobs_file,
                    taxonomy_path=multi_taxonomy_file,
                )
        assert len(bundles) == 2

    def test_multi_failure_distinct_sha256(self, multi_failure_log_file, multi_failure_jobs_file, multi_taxonomy_file):
        with patch("scripts.ci_rca.tier_map.probe_runtime", return_value=("median=50ms", 0.05)):
            with patch("scripts.ci_rca.tier_map.build_tier_membership", return_value={}):
                bundles = generate_bundles(
                    log_file=multi_failure_log_file,
                    workflow_name="CI",
                    workflow_run_id=42,
                    jobs_file=multi_failure_jobs_file,
                    taxonomy_path=multi_taxonomy_file,
                )
        shas = [b["sha256"] for b in bundles]
        assert len(set(shas)) == 2

    def test_multi_failure_shared_workflow_run_id(self, multi_failure_log_file, multi_failure_jobs_file, multi_taxonomy_file):
        with patch("scripts.ci_rca.tier_map.probe_runtime", return_value=("median=50ms", 0.05)):
            with patch("scripts.ci_rca.tier_map.build_tier_membership", return_value={}):
                bundles = generate_bundles(
                    log_file=multi_failure_log_file,
                    workflow_name="CI",
                    workflow_run_id=42,
                    jobs_file=multi_failure_jobs_file,
                    taxonomy_path=multi_taxonomy_file,
                )
        assert all(b["workflow_run_id"] == 42 for b in bundles)

    def test_single_failure_still_yields_one_bundle(self, log_file, taxonomy_file):
        with patch("scripts.ci_rca.tier_map.probe_runtime", return_value=("median=50ms", 0.05)):
            with patch("scripts.ci_rca.tier_map.build_tier_membership", return_value={}):
                bundles = generate_bundles(
                    log_file=log_file,
                    workflow_name="CI",
                    workflow_run_id=1,
                    taxonomy_path=taxonomy_file,
                )
        assert len(bundles) == 1


class TestPreRuntimeStamp:
    """CIRCA-05: CI_RCA_PRE_RUNTIME_SECONDS env stamp resolution and bundle wiring."""

    def test_resolve_env_unset(self, monkeypatch):
        monkeypatch.delenv("CI_RCA_PRE_RUNTIME_SECONDS", raising=False)
        assert _resolve_current_pre_runtime() is None

    def test_resolve_env_empty(self, monkeypatch):
        monkeypatch.setenv("CI_RCA_PRE_RUNTIME_SECONDS", "")
        assert _resolve_current_pre_runtime() is None

    def test_resolve_env_non_numeric(self, monkeypatch):
        monkeypatch.setenv("CI_RCA_PRE_RUNTIME_SECONDS", "abc")
        assert _resolve_current_pre_runtime() is None

    def test_resolve_env_zero(self, monkeypatch):
        monkeypatch.setenv("CI_RCA_PRE_RUNTIME_SECONDS", "0")
        assert _resolve_current_pre_runtime() is None

    def test_resolve_env_negative(self, monkeypatch):
        monkeypatch.setenv("CI_RCA_PRE_RUNTIME_SECONDS", "-5")
        assert _resolve_current_pre_runtime() is None

    def test_resolve_env_valid(self, monkeypatch):
        monkeypatch.setenv("CI_RCA_PRE_RUNTIME_SECONDS", "42.5")
        assert _resolve_current_pre_runtime() == 42.5

    def test_bundle_env_unset_undetermined_marker(self, monkeypatch, log_file, taxonomy_file):
        monkeypatch.delenv("CI_RCA_PRE_RUNTIME_SECONDS", raising=False)
        with patch("scripts.ci_rca.tier_map.probe_runtime", return_value=("median=50ms", 0.05)):
            with patch(
                "scripts.ci_rca.tier_map.build_tier_membership",
                return_value={"validate_sloc_limits": ["presubmit"]},
            ):
                bundles = generate_bundles(
                    log_file=log_file,
                    workflow_name="CI",
                    workflow_run_id=1,
                    taxonomy_path=taxonomy_file,
                )
        b = bundles[0]
        assert "undetermined-headroom" in b["earliest_viable_gate_rationale"]
        assert "0.0s" not in b["earliest_viable_gate_rationale"]
        assert b["pre_runtime_seconds"] is None

    def test_bundle_env_set_embeds_measured_runtime(self, monkeypatch, log_file, taxonomy_file):
        monkeypatch.setenv("CI_RCA_PRE_RUNTIME_SECONDS", "150")
        with patch("scripts.ci_rca.tier_map.probe_runtime", return_value=("median=50ms", 0.05)):
            with patch(
                "scripts.ci_rca.tier_map.build_tier_membership",
                return_value={"validate_sloc_limits": ["presubmit"]},
            ):
                bundles = generate_bundles(
                    log_file=log_file,
                    workflow_name="CI",
                    workflow_run_id=1,
                    taxonomy_path=taxonomy_file,
                )
        b = bundles[0]
        assert "150.0s" in b["earliest_viable_gate_rationale"]
        assert b["pre_runtime_seconds"] == 150.0

    def test_bundle_env_invalid_falls_back_to_none(self, monkeypatch, log_file, taxonomy_file):
        monkeypatch.setenv("CI_RCA_PRE_RUNTIME_SECONDS", "not-a-number")
        with patch("scripts.ci_rca.tier_map.probe_runtime", return_value=("median=50ms", 0.05)):
            with patch(
                "scripts.ci_rca.tier_map.build_tier_membership",
                return_value={"validate_sloc_limits": ["presubmit"]},
            ):
                bundles = generate_bundles(
                    log_file=log_file,
                    workflow_name="CI",
                    workflow_run_id=1,
                    taxonomy_path=taxonomy_file,
                )
        b = bundles[0]
        assert "undetermined-headroom" in b["earliest_viable_gate_rationale"]
        assert b["pre_runtime_seconds"] is None
