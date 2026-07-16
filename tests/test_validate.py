"""Tests for the new functions added to scripts/validate.py in agent/infra-testing-enforcement.

Covers: validate_cli_tools_in_prompts, validate_test_coverage, validate_prompt_compliance,
and the _load_coverage_checker / _load_prompt_compliance helpers.
"""

import itertools
import re
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.checks._scaffolding import (
    _PYTEST_FLAGS,
    _excluded_heavy_import_names,
    _parse_requirement_dist_names,
    partition_changed_tests_by_collectability,
)
from tests.fixtures.subprocess_stubs import _mock_completed, _pre_mock_run  # noqa: E402
from tests.fixtures.validate_module import _validate  # noqa: E402

validate_scheduled_agent_logs = _validate.validate_scheduled_agent_logs
validate_ghas_probe = _validate.validate_ghas_probe
validate_cli_tools_in_prompts = _validate.validate_cli_tools_in_prompts
validate_test_coverage = _validate.validate_test_coverage
validate_prompt_compliance = _validate.validate_prompt_compliance
validate_instruction_architecture_layers = _validate.validate_instruction_architecture_layers
validate_invariants = _validate.validate_invariants
validate_no_underscore_instructions = _validate.validate_no_underscore_instructions
validate_recommendations_schema = _validate.validate_recommendations_schema
validate_complexity = _validate.validate_complexity
validate_sloc_limits = _validate.validate_sloc_limits
validate_cc_limits = _validate.validate_cc_limits
validate_ci_rca_trigger = _validate.validate_ci_rca_trigger
validate_ci_workflow_guards = _validate.validate_ci_workflow_guards
ensure_fresh_dq_results = _validate.ensure_fresh_dq_results
run_coverage_check = _validate.run_coverage_check
_load_coverage_checker = _validate._load_coverage_checker
_load_prompt_compliance = _validate._load_prompt_compliance
_check_graduation_guard = _validate._check_graduation_guard
_extract_enforced_map = _validate._extract_enforced_map
check_source_registry = _validate.check_source_registry
validate_iam_runner_policy = _validate.validate_iam_runner_policy
get_changed_files = _validate.get_changed_files
validate_environment_taxonomy = _validate.validate_environment_taxonomy
_file_budget_breach_rec = _validate._file_budget_breach_rec
_file_budget_bypass_rec = _validate._file_budget_bypass_rec
_FAST_TIER_BUDGET_SECONDS = _validate._FAST_TIER_BUDGET_SECONDS
ROOT = _validate.ROOT
check_claude_md_pointer_invariant = _validate.check_claude_md_pointer_invariant
validate_hermeticity_flags = _validate.validate_hermeticity_flags
_build_unit_test_cmd = _validate._build_unit_test_cmd
_UNIT_TEST_HERMETICITY_FLAGS = _validate._UNIT_TEST_HERMETICITY_FLAGS
validate_lambda_manifests = _validate.validate_lambda_manifests
validate_lambda_manifest_coverage = _validate.validate_lambda_manifest_coverage
validate_lambda_bundle_completeness = _validate.validate_lambda_bundle_completeness
validate_lambda_deploy_gating = _validate.validate_lambda_deploy_gating
validate_intent_doc_freeze = _validate.validate_intent_doc_freeze
validate_ci_rca_taxonomy = _validate.validate_ci_rca_taxonomy
validate_verifier_hermeticity = _validate.validate_verifier_hermeticity
validate_field_semantics_drift = _validate.validate_field_semantics_drift
validate_broker_env_reads = _validate.validate_broker_env_reads
validate_platform_roadmap = _validate.validate_platform_roadmap
validate_candidate_decision_ratification = _validate.validate_candidate_decision_ratification
validate_ducklake_version_lockstep = _validate.validate_ducklake_version_lockstep
validate_verifier_same_pr_guard = _validate.validate_verifier_same_pr_guard
validate_verification_registry = _validate.validate_verification_registry
validate_differential_gate_baseline = _validate.validate_differential_gate_baseline
validate_vp_replay = _validate.validate_vp_replay
validate_rec_relevance_contract = _validate.validate_rec_relevance_contract
_extract_verifier_covers = _validate._extract_verifier_covers
_load_sloc_budgets = _validate._load_sloc_budgets
_update_sloc_budgets = _validate._update_sloc_budgets
validate_sloc_budget_raises = _validate.validate_sloc_budget_raises
iter_gated_py_files = _validate.iter_gated_py_files
validate_dependency_graph_freshness = _validate.validate_dependency_graph_freshness
validate_import_contracts = _validate.validate_import_contracts
validate_lockfile_sync = _validate.validate_lockfile_sync
validate_portal_drift = _validate.validate_portal_drift
run_pytest_diff = _validate.run_pytest_diff
validate_tier_floor = _validate.validate_tier_floor
validate_invoke_implies_resolve = _validate.validate_invoke_implies_resolve
validate_ci_refresh_read_coverage = _validate.validate_ci_refresh_read_coverage


class TestLoadHelpers:
    """Tests for _load_coverage_checker and _load_prompt_compliance."""

    def test_load_coverage_checker_returns_module_when_exists(self) -> None:
        """Returns a module object when test_coverage_checker.py exists."""
        checker = _load_coverage_checker()
        assert checker is not None
        assert hasattr(checker, "extract_definitions")
        assert hasattr(checker, "get_changed_source_files")

    def test_load_coverage_checker_returns_none_when_missing(self, tmp_path: Path) -> None:
        """Returns None when the script does not exist."""
        with patch("scripts.checks._common.ROOT", tmp_path):
            result = _load_coverage_checker()
        assert result is None

    def test_load_prompt_compliance_returns_module_when_exists(self) -> None:
        """Returns a module object when prompt_compliance.py exists."""
        compliance = _load_prompt_compliance()
        assert compliance is not None
        assert hasattr(compliance, "parse_invariants")
        assert hasattr(compliance, "check_retro_lite_compliance")

    def test_load_prompt_compliance_returns_none_when_missing(self, tmp_path: Path) -> None:
        """Returns None when the script does not exist."""
        with patch("scripts.checks._common.ROOT", tmp_path):
            result = _load_prompt_compliance()
        assert result is None


class TestRunTerraformChecks:
    """Tests for run_terraform_checks() (full presubmit) and run_terraform_creds_free()."""

    def test_warns_when_personal_plan_exit_code_2(self, capsys: pytest.CaptureFixture) -> None:
        """run_terraform_checks() warns when the terraform/personal plan returns exit code 2."""

        def mock_run(cmd: list, **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.stdout = ""
            result.stderr = ""
            result.returncode = 2 if "-detailed-exitcode" in cmd else 0
            return result

        with (
            patch("scripts.checks._terraform.validate_terraform_try"),
            patch("validate.shutil.which", return_value="/usr/bin/terraform"),
            patch("scripts.checks._common.run", side_effect=mock_run),
        ):
            failed: list[str] = []
            _validate.run_terraform_checks(failed)

        captured = capsys.readouterr()
        assert "WARNING: Terraform changes pending" in captured.out
        assert "terraform/personal" in captured.out
        assert failed == []

    def test_no_warning_when_exit_code_0(self, capsys: pytest.CaptureFixture) -> None:
        """run_terraform_checks() does not warn when plan returns exit code 0."""

        def mock_run(cmd: list, **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.returncode = 0
            result.stdout = ""
            result.stderr = ""
            return result

        with (
            patch("scripts.checks._terraform.validate_terraform_try"),
            patch("validate.shutil.which", return_value="/usr/bin/terraform"),
            patch("scripts.checks._common.run", side_effect=mock_run),
        ):
            failed: list[str] = []
            _validate.run_terraform_checks(failed)

        captured = capsys.readouterr()
        assert "WARNING" not in captured.out
        assert failed == []

    def test_skips_terraform_binary_steps_when_not_found(self, capsys: pytest.CaptureFixture) -> None:
        """No terraform binary -> creds-free helper prints a skip and `run` is never invoked."""
        with (
            patch("scripts.checks._terraform.validate_terraform_try"),
            patch("validate.shutil.which", return_value=None),
            patch("scripts.checks._common.run", side_effect=AssertionError("run must not be called when terraform is absent")),
        ):
            failed: list[str] = []
            _validate.run_terraform_checks(failed)

        captured = capsys.readouterr()
        assert "skipped" in captured.out
        assert failed == []

    def test_creds_free_covers_both_roots(self) -> None:
        """run_terraform_creds_free() runs init -backend=false + validate + fmt for ALL roots, no plan."""
        calls: list[list] = []

        def mock_run(cmd: list, **kwargs: object) -> MagicMock:
            calls.append(list(cmd))
            result = MagicMock()
            result.returncode = 0
            result.stdout = ""
            result.stderr = ""
            return result

        with (
            patch("validate.shutil.which", return_value="/usr/bin/terraform"),
            patch("scripts.checks._common.run", side_effect=mock_run),
        ):
            failed: list[str] = []
            _validate.run_terraform_creds_free(failed)

        chdirs = {arg for cmd in calls for arg in cmd if isinstance(arg, str) and arg.startswith("-chdir=")}
        flat = [tok for cmd in calls for tok in cmd]
        assert "-chdir=terraform" in chdirs
        assert "-chdir=terraform/personal" in chdirs
        assert "-chdir=terraform/bootstrap" in chdirs
        assert any("-backend=false" in cmd for cmd in calls)  # creds-free init
        assert all("plan" not in cmd for cmd in calls)  # no creds-needing plan here
        assert "init" in flat and "validate" in flat and "fmt" in flat
        assert failed == []

    def test_creds_free_skips_when_terraform_absent(self, capsys: pytest.CaptureFixture) -> None:
        """run_terraform_creds_free() emits a visible skip and calls nothing when terraform is absent."""
        with (
            patch("validate.shutil.which", return_value=None),
            patch("scripts.checks._common.run", side_effect=AssertionError("run must not be called")),
        ):
            failed: list[str] = []
            _validate.run_terraform_creds_free(failed)
        assert "skipped" in capsys.readouterr().out
        assert failed == []

    def test_creds_free_init_retries_on_transient_5xx(self, capsys: pytest.CaptureFixture) -> None:
        """_terraform_init_with_retry retries on transient 5xx and succeeds on the third attempt."""
        init_call_count = 0

        def mock_run(cmd: list, **kwargs: object) -> MagicMock:
            nonlocal init_call_count
            result = MagicMock()
            if "init" in cmd:
                init_call_count += 1
                if init_call_count < 3:
                    result.returncode = 1
                    result.stdout = "Error: could not query provider registry"
                    result.stderr = ""
                else:
                    result.returncode = 0
                    result.stdout = "Terraform has been successfully initialized!"
                    result.stderr = ""
            else:
                result.returncode = 0
                result.stdout = ""
                result.stderr = ""
            return result

        with (
            patch("validate.shutil.which", return_value="/usr/bin/terraform"),
            patch("scripts.checks._common.run", side_effect=mock_run),
            patch("validate.time.sleep"),
        ):
            failed: list[str] = []
            _validate.run_terraform_creds_free(failed, roots=("terraform",))

        assert init_call_count == 3
        assert failed == []

    def test_creds_free_init_fails_fast_on_non_transient(self) -> None:
        """_terraform_init_with_retry does NOT retry on non-transient errors."""
        init_call_count = 0

        def mock_run(cmd: list, **kwargs: object) -> MagicMock:
            nonlocal init_call_count
            result = MagicMock()
            if "init" in cmd:
                init_call_count += 1
                result.returncode = 1
                result.stdout = "Error: Required token could not be found"
                result.stderr = ""
            else:
                result.returncode = 0
                result.stdout = ""
                result.stderr = ""
            return result

        with (
            patch("validate.shutil.which", return_value="/usr/bin/terraform"),
            patch("scripts.checks._common.run", side_effect=mock_run),
            patch("validate.time.sleep"),
        ):
            failed: list[str] = []
            _validate.run_terraform_creds_free(failed, roots=("terraform",))

        assert init_call_count == 1
        assert len(failed) == 1
        assert "Terraform init" in failed[0]

    def test_creds_free_init_exhausts_retries_on_persistent_transient(self) -> None:
        """A transient 5xx on all 3 attempts exhausts the retry budget and appends to failed."""
        init_call_count = 0

        def mock_run(cmd: list, **kwargs: object) -> MagicMock:
            nonlocal init_call_count
            result = MagicMock()
            if "init" in cmd:
                init_call_count += 1
                result.returncode = 1
                result.stdout = ""
                result.stderr = "Error: 502 Bad Gateway from registry.terraform.io"
            else:
                result.returncode = 0
                result.stdout = ""
                result.stderr = ""
            return result

        with (
            patch("validate.shutil.which", return_value="/usr/bin/terraform"),
            patch("scripts.checks._common.run", side_effect=mock_run),
            patch("validate.time.sleep"),
        ):
            failed: list[str] = []
            _validate.run_terraform_creds_free(failed, roots=("terraform",))

        assert init_call_count == 3  # all attempts consumed
        assert len(failed) == 1
        assert "Terraform init" in failed[0]

    def test_creds_free_init_retries_on_connection_reset(self) -> None:
        """_terraform_init_with_retry retries a provider-download connection reset and succeeds on attempt 3."""
        init_call_count = 0

        def mock_run(cmd: list, **kwargs: object) -> MagicMock:
            nonlocal init_call_count
            result = MagicMock()
            if "init" in cmd:
                init_call_count += 1
                if init_call_count < 3:
                    result.returncode = 1
                    result.stdout = ""
                    result.stderr = "read: connection reset by peer"
                else:
                    result.returncode = 0
                    result.stdout = "Terraform has been successfully initialized!"
                    result.stderr = ""
            else:
                result.returncode = 0
                result.stdout = ""
                result.stderr = ""
            return result

        with (
            patch("validate.shutil.which", return_value="/usr/bin/terraform"),
            patch("scripts.checks._common.run", side_effect=mock_run),
            patch("validate.time.sleep"),
        ):
            failed: list[str] = []
            _validate.run_terraform_creds_free(failed, roots=("terraform",))

        assert init_call_count == 3
        assert failed == []

    def test_creds_free_init_fails_fast_on_bad_pin(self) -> None:
        """A non-transient bad-pin provider error is not retried, even though it fails init."""
        init_call_count = 0

        def mock_run(cmd: list, **kwargs: object) -> MagicMock:
            nonlocal init_call_count
            result = MagicMock()
            if "init" in cmd:
                init_call_count += 1
                result.returncode = 1
                result.stdout = (
                    "Error: Failed to install provider\n"
                    "provider registry does not have a provider named registry.terraform.io/hashicorp/aws"
                )
                result.stderr = ""
            else:
                result.returncode = 0
                result.stdout = ""
                result.stderr = ""
            return result

        with (
            patch("validate.shutil.which", return_value="/usr/bin/terraform"),
            patch("scripts.checks._common.run", side_effect=mock_run),
            patch("validate.time.sleep"),
        ):
            failed: list[str] = []
            _validate.run_terraform_creds_free(failed, roots=("terraform",))

        assert init_call_count == 1
        assert len(failed) == 1
        assert "Terraform init" in failed[0]

    def test_creds_free_init_skips_on_proxy_403(self, capsys: pytest.CaptureFixture) -> None:
        """A github.com-403 auth-checksum init failure is a visible skip, not a failure, and fmt still runs."""
        calls: list[list] = []

        def mock_run(cmd: list, **kwargs: object) -> MagicMock:
            calls.append(list(cmd))
            result = MagicMock()
            if "init" in cmd:
                result.returncode = 1
                result.stdout = ""
                result.stderr = (
                    "Error: Failed to install provider\n"
                    "Error: retrieving checksums for provider: 403 Forbidden returned from github.com"
                )
            else:
                result.returncode = 0
                result.stdout = ""
                result.stderr = ""
            return result

        with (
            patch("validate.shutil.which", return_value="/usr/bin/terraform"),
            patch("scripts.checks._common.run", side_effect=mock_run),
            patch("validate.time.sleep"),
        ):
            failed: list[str] = []
            _validate.run_terraform_creds_free(failed, roots=("terraform/personal",))

        captured = capsys.readouterr()
        assert "SKIP" in captured.out
        assert failed == []
        assert not any("validate" in cmd for cmd in calls)
        assert any("fmt" in cmd for cmd in calls)

    def test_creds_free_init_still_fails_on_non_github_403(self) -> None:
        """A 403 lacking the github.com/checksum co-occurrence (e.g. an S3 backend 403) still fails."""

        def mock_run(cmd: list, **kwargs: object) -> MagicMock:
            result = MagicMock()
            if "init" in cmd:
                result.returncode = 1
                result.stdout = ""
                result.stderr = "Error: error configuring S3 Backend: 403 Forbidden: AccessDenied"
            else:
                result.returncode = 0
                result.stdout = ""
                result.stderr = ""
            return result

        with (
            patch("validate.shutil.which", return_value="/usr/bin/terraform"),
            patch("scripts.checks._common.run", side_effect=mock_run),
            patch("validate.time.sleep"),
        ):
            failed: list[str] = []
            _validate.run_terraform_creds_free(failed, roots=("terraform/personal",))

        assert len(failed) == 1
        assert "Terraform init" in failed[0]

    def test_transient_init_signatures_exact_set(self) -> None:
        """_TRANSIENT_INIT_SIGNATURES contains the expected tokens (parity with workflow retry loop)."""
        expected = frozenset(
            (
                "502",
                "Bad Gateway",
                "could not query provider registry",
                "failed after ",
                "connection reset by peer",
                "i/o timeout",
                "TLS handshake timeout",
                "unexpected EOF",
            )
        )
        assert frozenset(_validate._TRANSIENT_INIT_SIGNATURES) == expected


class TestWholeRepoScanCoverage:
    """Tests for the Decision 130 whole-repo scan extension (tests/ is now gated)."""

    def _write_budget(self, tmp_path: Path, entries: dict[str, int]) -> None:
        config_dir = tmp_path / "config"
        config_dir.mkdir(exist_ok=True)
        lines = ["budgets:"]
        for k, v in entries.items():
            lines.append(f"  {k}: {v}")
        (config_dir / "sloc_budgets.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def test_oversized_unregistered_tests_file_fails(self, tmp_path: Path) -> None:
        """A tests/ file over 500 SLOC with no budget entry fails validate_sloc_limits."""
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_big_thing.py").write_text("x = 1\n" * 501, encoding="utf-8")

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_sloc_limits(failed)

        assert len(failed) == 1
        assert "SLOC limits" in failed[0]

    def test_registered_tests_file_at_budget_passes(self, tmp_path: Path) -> None:
        """A tests/ file registered at/under its budget passes validate_sloc_limits."""
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_big_thing.py").write_text("x = 1\n" * 600, encoding="utf-8")
        self._write_budget(tmp_path, {"tests/test_big_thing.py": 600})

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_sloc_limits(failed)

        assert failed == []

    def test_excluded_dir_is_not_gated(self, tmp_path: Path) -> None:
        """A file under an excluded dir (e.g. .venv/) is never scanned, regardless of SLOC."""
        venv_dir = tmp_path / ".venv" / "foo"
        venv_dir.mkdir(parents=True)
        (venv_dir / "vendored.py").write_text("x = 1\n" * 999, encoding="utf-8")

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_sloc_limits(failed)
            gated = list(iter_gated_py_files())

        assert failed == []
        assert gated == []

    def test_all_three_gate_functions_share_one_scan(self, tmp_path: Path) -> None:
        """validate_sloc_limits, _update_sloc_budgets, and validate_cc_limits all consume the
        same iter_gated_py_files() -- one mock patched into both consumer modules is seen
        identically by all three, so the scan roots can never silently drift apart."""
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        only_file = tests_dir / "test_only.py"
        only_file.write_text("x = 1\n" * 501, encoding="utf-8")
        self._write_budget(tmp_path, {})

        shared_mock = MagicMock(side_effect=lambda: iter([only_file]))

        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks.sloc.sloc_limits.iter_gated_py_files", shared_mock),
            patch("scripts.checks.sloc.cc_limits.iter_gated_py_files", shared_mock),
        ):
            failed: list[str] = []
            validate_sloc_limits(failed)
            _update_sloc_budgets()
            validate_cc_limits(failed)

        assert shared_mock.call_count == 3  # validate_sloc_limits + _update_sloc_budgets + validate_cc_limits
        assert len(failed) == 1  # only the unregistered oversized file, from validate_sloc_limits

    def test_cc_limits_flags_branchy_function_in_tests_dir(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """validate_cc_limits now covers tests/: a >20-branch function there is flagged."""
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        branches = "\n".join(f"    if x == {i}: pass" for i in range(21))
        (tests_dir / "test_branchy.py").write_text(f"def test_heavy_dispatch(x):\n{branches}\n", encoding="utf-8")

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_cc_limits(failed)

        assert len(failed) == 1
        assert "Cyclomatic complexity" in failed[0]
        captured = capsys.readouterr()
        assert "test_heavy_dispatch" in captured.out


validate_executor_boundary = _validate.validate_executor_boundary
validate_outbox_staleness = _validate.validate_outbox_staleness
validate_rec_write_paths = _validate.validate_rec_write_paths
validate_warehouse_write_sources = _validate.validate_warehouse_write_sources


# ---------------------------------------------------------------------------
# TestValidateOutboxStaleness
# ---------------------------------------------------------------------------


class TestEnsureFreshDqResults:
    """Tests for ensure_fresh_dq_results() — the DQ runner auto-invoke."""

    @pytest.fixture(autouse=True)
    def _inject_boto3_stub(self):
        """Ensure boto3 is in sys.modules so patch("boto3.Session") resolves on CI runners where boto3 is not installed."""
        if "boto3" not in sys.modules:
            sys.modules["boto3"] = MagicMock()
            yield
            del sys.modules["boto3"]
        else:
            yield

    def test_ensure_fresh_dq_runs_when_cache_missing(self, tmp_path: Path, capsys) -> None:
        """No dq-latest.json on disk: credential check runs, then data_quality_runner is invoked."""
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("boto3.Session") as mock_session,
            patch("scripts.checks._common.run") as mock_run,
        ):
            mock_session.return_value.client.return_value.get_caller_identity.return_value = {"Account": "123"}
            mock_run.return_value = _mock_completed(0)
            failed: list[str] = []
            ensure_fresh_dq_results(failed)

        captured = capsys.readouterr()
        assert "DQ cache missing" in captured.out
        assert "data_quality_runner" in captured.out
        # One subprocess call: data_quality_runner only (credential check is boto3).
        assert mock_run.call_count == 1
        runner_cmd = mock_run.call_args_list[0].args[0]
        assert "data_quality_runner" in " ".join(runner_cmd)
        assert failed == []

    def test_ensure_fresh_dq_runs_when_cache_stale(self, tmp_path: Path, capsys) -> None:
        """dq-latest.json older than the freshness window: re-runs the runner."""
        import os
        import time

        dq_dir = tmp_path / "logs" / "debug"
        dq_dir.mkdir(parents=True)
        dq_file = dq_dir / "dq-latest.json"
        dq_file.write_text("{}", encoding="utf-8")
        # Backdate mtime by 2 hours -- well past the 1h freshness window.
        old_mtime = time.time() - 2 * 3600
        os.utime(str(dq_file), (old_mtime, old_mtime))

        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("boto3.Session") as mock_session,
            patch("scripts.checks._common.run") as mock_run,
        ):
            mock_session.return_value.client.return_value.get_caller_identity.return_value = {"Account": "123"}
            mock_run.return_value = _mock_completed(0)
            failed: list[str] = []
            ensure_fresh_dq_results(failed)

        captured = capsys.readouterr()
        assert "DQ cache stale" in captured.out
        assert "data_quality_runner" in captured.out
        assert mock_run.call_count == 1
        assert failed == []

    def test_ensure_fresh_dq_skips_when_cache_fresh(self, tmp_path: Path, capsys) -> None:
        """dq-latest.json modified within the last hour: skip with a clear message."""
        dq_dir = tmp_path / "logs" / "debug"
        dq_dir.mkdir(parents=True)
        dq_file = dq_dir / "dq-latest.json"
        dq_file.write_text("{}", encoding="utf-8")
        # Default mtime is 'now', well inside the 1h freshness window.

        with patch("scripts.checks._common.ROOT", tmp_path), patch("scripts.checks._common.run") as mock_run:
            failed: list[str] = []
            ensure_fresh_dq_results(failed)

        captured = capsys.readouterr()
        assert "DQ cache fresh" in captured.out
        # Fresh cache must short-circuit before invoking subprocess at all.
        assert mock_run.call_count == 0
        assert failed == []

    def test_ensure_fresh_dq_skips_when_sso_unavailable(self, tmp_path: Path, capsys) -> None:
        """Decision 57: failed boto3 credential check prints actionable guidance and skips."""
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("boto3.Session") as mock_session,
            patch("scripts.checks._common.run") as mock_run,
        ):
            mock_session.return_value.client.return_value.get_caller_identity.side_effect = Exception("Token has expired")
            failed: list[str] = []
            ensure_fresh_dq_results(failed)

        captured = capsys.readouterr()
        assert "credentials not available" in captured.out and "skipping" in captured.out
        # No subprocess calls -- the runner was never invoked after the credential failure.
        assert mock_run.call_count == 0
        assert failed == []

    def test_ensure_fresh_dq_skips_when_credentials_unavailable(self, tmp_path: Path, capsys) -> None:
        """Decision 57: any boto3 credential error must skip with guidance, not crash."""
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("boto3.Session") as mock_session,
            patch("scripts.checks._common.run") as mock_run,
        ):
            mock_session.side_effect = Exception("ProfileNotFound")
            failed: list[str] = []
            ensure_fresh_dq_results(failed)

        captured = capsys.readouterr()
        assert "credentials not available" in captured.out and "skipping" in captured.out
        assert mock_run.call_count == 0
        assert failed == []


class TestRunCoverageCheck:
    """Tests for run_coverage_check() — the --coverage advisory mode."""

    def test_run_coverage_check_no_changed_files_prints_message(self, capsys) -> None:
        """When there are no changed files, the function reports nothing to check."""
        with patch("scripts.checks._common.get_changed_files", return_value=[]):
            run_coverage_check()
        captured = capsys.readouterr()
        assert "coverage" in captured.out.lower()
        assert "No changed files" in captured.out

    def test_run_coverage_check_all_covered(self, capsys) -> None:
        """When every changed file is covered, the report says 'All scope files covered'."""
        with (
            patch("scripts.checks._common.get_changed_files", return_value=["scripts/ops_data_portal.py"]),
            patch("scripts.verifiers.check_coverage", return_value=[]),
        ):
            run_coverage_check()
        captured = capsys.readouterr()
        assert "All scope files covered" in captured.out

    def test_run_coverage_check_lists_uncovered(self, capsys) -> None:
        """Uncovered files are printed line-by-line under the report header."""
        with (
            patch(
                "scripts.checks._common.get_changed_files",
                return_value=["docs/foo.md", "scripts/ops_data_portal.py"],
            ),
            patch(
                "scripts.verifiers.check_coverage",
                return_value=["docs/foo.md"],
            ),
        ):
            run_coverage_check()
        captured = capsys.readouterr()
        assert "1 of 2 scope files lack verifier coverage" in captured.out
        assert "- docs/foo.md" in captured.out
        assert "Advisory only" in captured.out

    def test_run_coverage_check_uses_supplied_changed_files(self, capsys) -> None:
        """A supplied changed_files list is used verbatim, skipping the get_changed_files() call
        (VF-02(d): the --pre closure reuses its already-computed diff -- budget-safe)."""
        with (
            patch("scripts.checks._common.get_changed_files") as mock_get_changed,
            patch("scripts.verifiers.check_coverage", return_value=["docs/foo.md"]),
        ):
            run_coverage_check(changed_files=["docs/foo.md", "scripts/ops_data_portal.py"])
        captured = capsys.readouterr()
        assert "1 of 2 scope files lack verifier coverage" in captured.out
        mock_get_changed.assert_not_called()


class TestGetChangedFilesOriginMain:
    """Tests for the get_changed_files() origin/main semantics."""

    def test_uses_origin_main_on_success(self) -> None:
        calls: list[list[str]] = []

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            calls.append(list(cmd))
            result = MagicMock()
            result.returncode = 0
            result.stdout = "scripts/validate.py\ntests/test_validate.py\n"
            return result

        with patch("scripts.checks._common.run", side_effect=mock_run):
            files = get_changed_files()

        assert "scripts/validate.py" in files
        assert "tests/test_validate.py" in files
        assert any("origin/main" in c for c in calls[0])

    def test_falls_back_to_head_on_nonzero(self) -> None:
        calls: list[list[str]] = []

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            calls.append(list(cmd))
            result = MagicMock()
            if "origin/main" in cmd:
                result.returncode = 1
                result.stdout = ""
            else:
                result.returncode = 0
                result.stdout = "scripts/validate.py\n"
            return result

        with patch("scripts.checks._common.run", side_effect=mock_run):
            files = get_changed_files()

        assert "scripts/validate.py" in files
        assert any("origin/main" in c for c in calls[0])
        assert any("HEAD" in c for c in calls[1])

    def test_empty_result_returns_empty_list(self) -> None:
        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.returncode = 0
            result.stdout = ""
            return result

        with patch("scripts.checks._common.run", side_effect=mock_run):
            files = get_changed_files()

        assert files == []


class TestExcludedHeavyDeps:
    """Excluded-heavy import-name set derivation from the REAL requirements files (rec-2485)."""

    def test_heavy_deps_in_excluded_set(self) -> None:
        excluded = _excluded_heavy_import_names()
        for name in ("pyarrow", "pandas", "numpy", "duckdb"):
            assert name in excluded, f"{name} should be excluded (heavy, requirements.txt-only)"

    def test_fast_tier_deps_not_in_excluded_set(self) -> None:
        excluded = _excluded_heavy_import_names()
        for name in ("ruff", "mypy", "pytest", "pyyaml", "pydantic"):
            assert name not in excluded, f"{name} is present in requirements-fast.txt; must not be excluded"

    def test_parse_requirement_dist_names_missing_file_returns_empty_set(self, tmp_path: Path) -> None:
        assert _parse_requirement_dist_names(tmp_path / "nonexistent-requirements.txt") == set()


class TestFastTierCollectability:
    """Classifier routing: (returncode, output) -> (runnable | deferred) (rec-2485).

    Every heavy-dep-absence case below monkeypatches importlib.util.find_spec because pyarrow
    (and the other heavy deps) are actually installed in this dev venv -- only requirements-fast.txt
    (the pr-validate CI job) omits them, so genuine absence must be simulated here.
    """

    def test_heavy_dep_collection_error_defers(self) -> None:
        """A collect-only error whose root cause is a genuinely-absent excluded-heavy dep defers."""

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.stdout = ""
            if "--collect-only" in cmd:
                result.returncode = 2
                result.stderr = "ModuleNotFoundError: No module named 'pyarrow'"
            else:
                result.returncode = 0
                result.stderr = ""
            return result

        with (
            patch("scripts.checks._common.run", side_effect=mock_run),
            patch("importlib.util.find_spec", return_value=None),
        ):
            runnable, deferred = partition_changed_tests_by_collectability(["tests/test_some_heavy_dep_file.py"])

        assert runnable == []
        assert deferred == [("tests/test_some_heavy_dep_file.py", "pyarrow")]

    def test_runtime_failure_hard_fails(self) -> None:
        """A file that collects fine but fails at runtime (pytest exit 1) still hard-fails the gate."""

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.stdout = ""
            result.stderr = ""
            result.returncode = 0 if "--collect-only" in cmd else 1
            return result

        failed: list[str] = []
        with patch("scripts.checks._common.run", side_effect=mock_run):
            run_pytest_diff(["tests/test_something.py"], failed)

        assert failed == ["Tests (pytest)"]

    def test_non_heavy_modulenotfound_routes_to_runnable(self) -> None:
        """A collection error naming a repo-local (non-excluded) module routes to runnable."""

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.stdout = ""
            if "--collect-only" in cmd:
                result.returncode = 2
                result.stderr = "ModuleNotFoundError: No module named 'scripts.some_deleted_module'"
            else:
                result.returncode = 0
                result.stderr = ""
            return result

        with patch("scripts.checks._common.run", side_effect=mock_run):
            runnable, deferred = partition_changed_tests_by_collectability(["tests/test_something.py"])

        assert runnable == ["tests/test_something.py"]
        assert deferred == []

    def test_syntaxerror_collection_error_hard_fails(self) -> None:
        """A collection error with NO 'No module named' line (SyntaxError) routes to runnable, not deferred."""

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.stdout = ""
            if "--collect-only" in cmd:
                result.returncode = 2
                result.stderr = "SyntaxError: invalid syntax"
            else:
                result.returncode = 0
                result.stderr = ""
            return result

        with patch("scripts.checks._common.run", side_effect=mock_run):
            runnable, deferred = partition_changed_tests_by_collectability(["tests/test_broken.py"])

        assert runnable == ["tests/test_broken.py"]
        assert deferred == []

    def test_cannot_import_name_hard_fails(self) -> None:
        """A collection error carrying 'ImportError: cannot import name' (no 'No module named') hard-fails."""

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.stdout = ""
            if "--collect-only" in cmd:
                result.returncode = 2
                result.stderr = "ImportError: cannot import name 'Thing' from 'scripts.foo'"
            else:
                result.returncode = 0
                result.stderr = ""
            return result

        with patch("scripts.checks._common.run", side_effect=mock_run):
            runnable, deferred = partition_changed_tests_by_collectability(["tests/test_broken_import.py"])

        assert runnable == ["tests/test_broken_import.py"]
        assert deferred == []

    def test_present_module_not_deferred(self) -> None:
        """A ModuleNotFoundError naming an excluded-heavy dep that IS importable (find_spec not None) is not deferred."""

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.stdout = ""
            if "--collect-only" in cmd:
                result.returncode = 2
                result.stderr = "ModuleNotFoundError: No module named 'pyarrow'"
            else:
                result.returncode = 0
                result.stderr = ""
            return result

        with (
            patch("scripts.checks._common.run", side_effect=mock_run),
            patch("importlib.util.find_spec", return_value=MagicMock()),
        ):
            runnable, deferred = partition_changed_tests_by_collectability(["tests/test_some_heavy_dep_file.py"])

        assert runnable == ["tests/test_some_heavy_dep_file.py"]
        assert deferred == []

    def test_collect_only_passes_rs_flag(self) -> None:
        """`-rs` must be in the --collect-only invocation -- without it, a module-level
        pytest.importorskip's skip reason (which carries the 'No module named' signature) never
        appears in captured output, and the file is misrouted to runnable (rec-2707 CI follow-up)."""

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.stdout = ""
            result.stderr = ""
            result.returncode = 0
            return result

        with patch("scripts.checks._common.run", side_effect=mock_run) as mock_common_run:
            partition_changed_tests_by_collectability(["tests/test_something.py"])

        collect_only_cmd = mock_common_run.call_args[0][0]
        assert "-rs" in collect_only_cmd

    def test_module_level_importorskip_defers_not_runnable(self) -> None:
        """A module-level `pytest.importorskip("duckdb")` guard makes --collect-only exit 5
        (NO_TESTS_COLLECTED, a graceful skip -- not a collection error) with the skip reason
        only visible via -rs. This must defer, not route to runnable (rec-2707 CI follow-up:
        tests/test_ops_data_portal.py hit this when it was the sole changed test file -- the
        real run then collected 0 distributable items under -n auto and reddened the gate)."""

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.returncode = 5
            result.stderr = ""
            result.stdout = (
                "collected 0 items / 1 skipped\n\n"
                "=========================== short test summary info ============================\n"
                "SKIPPED [1] tests/test_ops_data_portal.py:33: could not import 'duckdb': "
                "No module named 'duckdb'\n"
                "========================= no tests collected in 0.06s ==========================\n"
            )
            return result

        with (
            patch("scripts.checks._common.run", side_effect=mock_run),
            patch("importlib.util.find_spec", return_value=None),
        ):
            runnable, deferred = partition_changed_tests_by_collectability(["tests/test_ops_data_portal.py"])

        assert runnable == []
        assert deferred == [("tests/test_ops_data_portal.py", "duckdb")]

    def test_module_level_importorskip_gate_not_reddened_end_to_end(self) -> None:
        """End-to-end: run_pytest_diff must not append 'Tests (pytest)' to failed when the sole
        changed file defers on a module-level importorskip (rec-2707 CI follow-up)."""

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.returncode = 5
            result.stderr = ""
            result.stdout = "SKIPPED [1] tests/test_ops_data_portal.py:33: could not import 'duckdb': No module named 'duckdb'"
            return result

        failed: list[str] = []
        with (
            patch("scripts.checks._common.run", side_effect=mock_run),
            patch("importlib.util.find_spec", return_value=None),
        ):
            run_pytest_diff(["tests/test_ops_data_portal.py"], failed)

        assert failed == []

    def test_iceberg_reader_defers_when_pyarrow_absent(self) -> None:
        """Real-file proof: the actual PR #405 offending file (tests/test_iceberg_reader.py, which
        imports pyarrow at module scope) lands in `deferred`, not `failed`, when pyarrow is simulated
        absent via find_spec."""

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.stdout = ""
            if "--collect-only" in cmd:
                result.returncode = 2
                result.stderr = "ModuleNotFoundError: No module named 'pyarrow'"
            else:
                result.returncode = 0
                result.stderr = ""
            return result

        with (
            patch("scripts.checks._common.run", side_effect=mock_run),
            patch("importlib.util.find_spec", return_value=None),
        ):
            runnable, deferred = partition_changed_tests_by_collectability(["tests/test_iceberg_reader.py"])

        assert runnable == []
        assert deferred == [("tests/test_iceberg_reader.py", "pyarrow")]


class TestRunPytestDiff:
    """Orchestration behaviours of run_pytest_diff() -- the consumer moved out of validate.py (rec-2485)."""

    def test_no_op_when_no_changed_tests(self) -> None:
        failed: list[str] = []
        with patch("scripts.checks._common.run", side_effect=AssertionError("run must not be called")):
            run_pytest_diff([], failed)
        assert failed == []

    def test_prints_loud_warning_and_does_not_redden_when_all_defer(self, capsys: pytest.CaptureFixture) -> None:
        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.returncode = 2
            result.stdout = ""
            result.stderr = "ModuleNotFoundError: No module named 'pyarrow'"
            return result

        failed: list[str] = []
        with (
            patch("scripts.checks._common.run", side_effect=mock_run),
            patch("importlib.util.find_spec", return_value=None),
        ):
            run_pytest_diff(["tests/test_iceberg_reader.py"], failed)

        captured = capsys.readouterr()
        assert "DEFERRED TO FULL TIER" in captured.out
        assert "tests/test_iceberg_reader.py" in captured.out
        assert "pyarrow" in captured.out
        assert failed == []


class TestRunPytestDiffSingleExecution:
    """Common-case single execution (acceptance criterion 1): when every changed test file
    collects and passes, run_pytest_diff issues EXACTLY ONE non-collect-only pytest invocation
    over the runnable set -- no proactive per-file isolated probe."""

    def test_runs_pytest_exactly_once_in_mixed_case(self) -> None:
        """tests/test_iceberg_reader.py defers at --collect-only (never gets a real run at all);
        tests/test_validate.py collects fine and passes, so it gets exactly one real run."""
        captured_cmds: list[list[str]] = []

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            captured_cmds.append(list(cmd))
            result = MagicMock()
            result.stdout = ""
            result.stderr = ""
            if "--collect-only" in cmd:
                if "tests/test_iceberg_reader.py" in cmd:
                    result.returncode = 2
                    result.stderr = "ModuleNotFoundError: No module named 'pyarrow'"
                else:
                    result.returncode = 0
            else:
                result.returncode = 0
            return result

        failed: list[str] = []
        with (
            patch("scripts.checks._common.run", side_effect=mock_run),
            patch("importlib.util.find_spec", return_value=None),
        ):
            run_pytest_diff(["tests/test_iceberg_reader.py", "tests/test_validate.py"], failed)

        real_run_cmds = [c for c in captured_cmds if "--collect-only" not in c]
        assert len(real_run_cmds) == 1, f"expected exactly one real pytest run, got: {real_run_cmds}"
        assert "tests/test_validate.py" in real_run_cmds[0]
        assert "tests/test_iceberg_reader.py" not in real_run_cmds[0]
        assert failed == []

    def test_runs_pytest_exactly_once_when_all_runnable_pass(self) -> None:
        captured_cmds: list[list[str]] = []

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            captured_cmds.append(list(cmd))
            result = MagicMock()
            result.stdout = ""
            result.stderr = ""
            result.returncode = 0
            return result

        failed: list[str] = []
        with patch("scripts.checks._common.run", side_effect=mock_run):
            run_pytest_diff(["tests/test_a.py", "tests/test_b.py"], failed)

        real_run_cmds = [c for c in captured_cmds if "--collect-only" not in c]
        assert len(real_run_cmds) == 1, f"expected exactly one real pytest run, got: {real_run_cmds}"
        assert "tests/test_a.py" in real_run_cmds[0]
        assert "tests/test_b.py" in real_run_cmds[0]
        assert failed == []


class TestRunPytestDiffReactiveDefer:
    """Reactive lazy-import heavy-dep defer (acceptance criterion 2): a genuinely-absent
    excluded heavy dependency imported lazily (function scope, invisible to --collect-only) is
    caught only AFTER the combined run fails, via a per-file isolated re-classification pass
    (rec-2572..2576 test_ops_writer.py shape). Every other failure shape reddens immediately."""

    def test_runtime_lazy_import_of_excluded_dep_defers(self) -> None:
        """A file that collects fine but fails at real-run time with a genuinely-absent excluded
        dep defers, via the reactive per-file probe -- and does not redden the gate."""

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.stderr = ""
            if "--collect-only" in cmd:
                result.returncode = 0
                result.stdout = ""
            else:
                result.returncode = 1
                result.stdout = (
                    "FAILED tests/test_ops_writer.py::TestCompact::test_compact_x - "
                    "ModuleNotFoundError: No module named 'pandas'\n"
                )
            return result

        failed: list[str] = []
        with (
            patch("scripts.checks._common.run", side_effect=mock_run),
            patch("importlib.util.find_spec", return_value=None),
        ):
            run_pytest_diff(["tests/test_ops_writer.py"], failed)

        assert failed == []

    def test_runtime_failure_with_no_module_error_reddens_immediately(self) -> None:
        """A file that collects fine and fails at runtime with no 'No module named' signature at
        all is a genuine failure -- must redden immediately (fail-closed), with no reactive re-run."""
        real_run_calls = {"n": 0}

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.stdout = ""
            result.stderr = ""
            if "--collect-only" in cmd:
                result.returncode = 0
            else:
                real_run_calls["n"] += 1
                result.returncode = 1
            return result

        failed: list[str] = []
        with patch("scripts.checks._common.run", side_effect=mock_run):
            run_pytest_diff(["tests/test_something.py"], failed)

        assert failed == ["Tests (pytest)"]
        assert real_run_calls["n"] == 1, "no reactive re-run should occur when there is no heavy-dep signature"

    def test_runtime_knockon_failures_still_defer_whole_file(self) -> None:
        """When one failing test names the missing excluded dep and OTHER failures in the same
        combined run look unrelated (e.g. state-pollution knock-on effects from the first
        failure), the whole file still defers -- ANY match is sufficient, not ALL, because once
        a required dependency is known absent, the other failures in that same run aren't
        independently meaningful."""

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.stderr = ""
            if "--collect-only" in cmd:
                result.returncode = 0
                result.stdout = ""
            else:
                result.returncode = 1
                result.stdout = (
                    "FAILED tests/test_ops_writer.py::A::test_a - assert 0 == 1\n"
                    "FAILED tests/test_ops_writer.py::B::test_b - "
                    "ModuleNotFoundError: No module named 'pandas'\n"
                    "FAILED tests/test_ops_writer.py::C::test_c - TypeError: 'NoneType' object is not subscriptable\n"
                )
            return result

        failed: list[str] = []
        with (
            patch("scripts.checks._common.run", side_effect=mock_run),
            patch("importlib.util.find_spec", return_value=None),
        ):
            run_pytest_diff(["tests/test_ops_writer.py"], failed)

        assert failed == []

    def test_runtime_lazy_import_of_present_dep_not_deferred(self) -> None:
        """A runtime ModuleNotFoundError naming an excluded dep that IS actually importable
        (find_spec not None) is a genuine failure, not a fast-tier absence -- must redden, not defer."""

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.stderr = ""
            if "--collect-only" in cmd:
                result.returncode = 0
                result.stdout = ""
            else:
                result.returncode = 1
                result.stdout = "FAILED tests/test_ops_writer.py::A::test_a - ModuleNotFoundError: No module named 'pandas'\n"
            return result

        failed: list[str] = []
        with (
            patch("scripts.checks._common.run", side_effect=mock_run),
            patch("importlib.util.find_spec", return_value=MagicMock()),
        ):
            run_pytest_diff(["tests/test_ops_writer.py"], failed)

        assert failed == ["Tests (pytest)"]

    def test_reactive_rerun_reddens_on_survivor_failure(self) -> None:
        """Two changed files: one's combined-run failure resolves (via the isolated probe) to a
        genuine failure (survivor), the other to a heavy-dep defer. The survivor is re-run alone;
        a real failure there still reddens the gate."""

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.stderr = ""
            if "--collect-only" in cmd:
                result.returncode = 0
                result.stdout = ""
            elif "-q" in cmd:
                # isolated per-file probe (_runtime_heavy_dep_defer_reason)
                if "tests/test_a.py" in cmd:
                    result.returncode = 1
                    result.stdout = "FAILED tests/test_a.py::test_x - assert 0 == 1\n"
                else:
                    result.returncode = 1
                    result.stdout = "FAILED tests/test_b.py::test_y - ModuleNotFoundError: No module named 'pandas'\n"
            elif "tests/test_b.py" in cmd:
                # combined gate run: both files present, mixed failure signature
                result.returncode = 1
                result.stdout = (
                    "FAILED tests/test_a.py::test_x - assert 0 == 1\n"
                    "FAILED tests/test_b.py::test_y - ModuleNotFoundError: No module named 'pandas'\n"
                )
            else:
                # reactive re-run of the survivor alone: genuine failure persists
                result.returncode = 1
                result.stdout = "FAILED tests/test_a.py::test_x - assert 0 == 1\n"
            return result

        failed: list[str] = []
        with (
            patch("scripts.checks._common.run", side_effect=mock_run),
            patch("importlib.util.find_spec", return_value=None),
        ):
            run_pytest_diff(["tests/test_a.py", "tests/test_b.py"], failed)

        assert failed == ["Tests (pytest)"]

    def test_isolated_probe_passing_makes_file_a_survivor(self) -> None:
        """A file whose combined-run failure carries a heavy-dep signature (triggering the
        reactive fallback) but whose ISOLATED single-file run actually passes (e.g. the failure
        was a cross-file interaction, not a real heavy-dep absence) is treated as a survivor, not
        deferred -- covers _runtime_heavy_dep_defer_reason's rc==0 -> None branch via the reactive
        path specifically (as opposed to the collect-only-only tests in TestFastTierCollectability)."""

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.stderr = ""
            if "--collect-only" in cmd:
                result.returncode = 0
                result.stdout = ""
            elif "-q" in cmd:
                # isolated probe: passes cleanly in isolation
                result.returncode = 0
                result.stdout = ""
            else:
                # combined run and final survivor re-run both fail identically
                result.returncode = 1
                result.stdout = "FAILED tests/test_ops_writer.py::A::test_a - ModuleNotFoundError: No module named 'pandas'\n"
            return result

        failed: list[str] = []
        with (
            patch("scripts.checks._common.run", side_effect=mock_run),
            patch("importlib.util.find_spec", return_value=None),
        ):
            run_pytest_diff(["tests/test_ops_writer.py"], failed)

        assert failed == ["Tests (pytest)"]


class TestPytestDiffParallelAndTimeout:
    """run_pytest_diff wires -n (parallel) and --timeout on both pytest invocations
    (pre-validation-performance / rec-2387)."""

    def test_primary_invocation_carries_parallel_and_timeout_flags(self) -> None:
        captured_cmds: list[list[str]] = []

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            captured_cmds.append(list(cmd))
            result = MagicMock()
            result.stdout = ""
            result.stderr = ""
            result.returncode = 0
            return result

        failed: list[str] = []
        with patch("scripts.checks._common.run", side_effect=mock_run):
            run_pytest_diff(["tests/test_a.py"], failed)

        real_run_cmds = [c for c in captured_cmds if "--collect-only" not in c]
        assert len(real_run_cmds) == 1
        cmd = real_run_cmds[0]
        assert "-n" in cmd
        assert cmd[cmd.index("-n") + 1] == "auto"
        assert "--timeout" in cmd
        assert failed == []

    def test_reactive_rerun_invocation_carries_parallel_and_timeout_flags(self) -> None:
        captured_cmds: list[list[str]] = []

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            captured_cmds.append(list(cmd))
            result = MagicMock()
            result.stderr = ""
            if "--collect-only" in cmd:
                result.returncode = 0
                result.stdout = ""
            elif len([c for c in captured_cmds if "--collect-only" not in c]) == 1:
                # the initial (non--collect-only) combined run: fail with a
                # deliberately-excluded, genuinely-absent heavy-dep signature so the
                # reactive re-run path fires
                result.returncode = 1
                result.stdout = "FAILED tests/test_ops_writer.py::A::test_a - ModuleNotFoundError: No module named 'pandas'\n"
            else:
                result.returncode = 0
                result.stdout = ""
            return result

        failed: list[str] = []
        with (
            patch("scripts.checks._common.run", side_effect=mock_run),
            patch("importlib.util.find_spec", return_value=None),
        ):
            run_pytest_diff(["tests/test_ops_writer.py"], failed)

        real_run_cmds = [c for c in captured_cmds if "--collect-only" not in c]
        assert len(real_run_cmds) >= 2, f"expected at least primary + reactive rerun, got: {captured_cmds}"
        rerun_cmd = real_run_cmds[-1]
        assert "-n" in rerun_cmd
        assert rerun_cmd[rerun_cmd.index("-n") + 1] == "auto"
        assert "--timeout" in rerun_cmd
        assert failed == []


class TestPytestFlagsPinnedSeed:
    """rec-2653: _PYTEST_FLAGS pins a fixed integer --randomly-seed so all -n auto xdist
    workers agree on collection order, instead of relying on pyproject.toml's addopts
    '--randomly-seed=last' (which resolves inconsistently across workers on a cold cache)."""

    def test_pytest_flags_pin_fixed_seed(self) -> None:
        seeds = [f for f in _PYTEST_FLAGS if f.startswith("--randomly-seed")]
        assert len(seeds) == 1, _PYTEST_FLAGS
        assert re.fullmatch(r"--randomly-seed=\d+", seeds[0]), seeds[0]

    def test_pinned_seed_reaches_pytest_at_runtime(self) -> None:
        import subprocess
        import sys

        pin = [f for f in _PYTEST_FLAGS if f.startswith("--randomly-seed")][0].split("=")[1]
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "tests/test_validate.py::TestPytestFlagsPinnedSeed::test_pytest_flags_pin_fixed_seed",
                "-o",
                "addopts=",
                "-p",
                "no:cacheprovider",
                *_PYTEST_FLAGS,
                "--collect-only",
            ],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        combined = result.stdout + result.stderr
        match = re.search(r"randomly-seed[:= ]+(\d+)", combined)
        assert match and match.group(1) == pin, combined[-600:]


@pytest.mark.usefixtures("_neutralized_pre_registry")
class TestPreModeDiffAware:
    """Tests that --pre passes changed files to ruff/mypy/pytest."""

    def test_passes_changed_py_files_to_ruff(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "argv", ["validate", "--pre"])
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("CI", raising=False)

        captured_cmds: list[list[str]] = []

        def tracking_run(cmd: list[str], **kwargs: object) -> MagicMock:
            captured_cmds.append(list(cmd))
            return _pre_mock_run(cmd, **kwargs)

        changed = ["scripts/validate.py", "tests/test_validate.py"]

        with (
            patch("scripts.checks._common.get_changed_files", return_value=changed),
            patch("scripts.checks._common.run", side_effect=tracking_run),
            patch("validate.validate_iam_runner_policy"),
            patch("validate.validate_prompt_files"),
            patch("validate.validate_cli_tools_in_prompts"),
            patch("time.monotonic", side_effect=itertools.chain([0.0], itertools.repeat(1.0))),
            pytest.raises(SystemExit) as exc_info,
        ):
            _validate.main()

        assert exc_info.value.code == 0
        ruff_check = [c for c in captured_cmds if "ruff" in c and "check" in c and "format" not in c]
        assert ruff_check, "No ruff check command issued"
        assert "scripts/validate.py" in ruff_check[0]

    def test_skips_lint_when_no_files_changed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "argv", ["validate", "--pre"])
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("CI", raising=False)

        captured_cmds: list[list[str]] = []

        def tracking_run(cmd: list[str], **kwargs: object) -> MagicMock:
            captured_cmds.append(list(cmd))
            return _pre_mock_run(cmd, **kwargs)

        with (
            patch("scripts.checks._common.get_changed_files", return_value=[]),
            patch("scripts.checks._common.run", side_effect=tracking_run),
            patch("validate.validate_iam_runner_policy"),
            patch("validate.validate_prompt_files"),
            patch("validate.validate_cli_tools_in_prompts"),
            patch("time.monotonic", side_effect=itertools.chain([0.0], itertools.repeat(1.0))),
            pytest.raises(SystemExit) as exc_info,
        ):
            _validate.main()

        assert exc_info.value.code == 0
        ruff_cmds = [c for c in captured_cmds if "ruff" in c]
        assert not ruff_cmds, f"Unexpected ruff invocation: {ruff_cmds}"

    def test_skips_pytest_when_no_test_files_changed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "argv", ["validate", "--pre"])
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("CI", raising=False)

        captured_cmds: list[list[str]] = []

        def tracking_run(cmd: list[str], **kwargs: object) -> MagicMock:
            captured_cmds.append(list(cmd))
            return _pre_mock_run(cmd, **kwargs)

        with (
            patch("scripts.checks._common.get_changed_files", return_value=["scripts/validate.py"]),
            patch("scripts.checks._common.run", side_effect=tracking_run),
            patch("validate.validate_iam_runner_policy"),
            patch("validate.validate_prompt_files"),
            patch("validate.validate_cli_tools_in_prompts"),
            patch("time.monotonic", side_effect=itertools.chain([0.0], itertools.repeat(1.0))),
            pytest.raises(SystemExit) as exc_info,
        ):
            _validate.main()

        assert exc_info.value.code == 0
        pytest_cmds = [c for c in captured_cmds if "pytest" in c]
        assert not pytest_cmds

    def test_invokes_pytest_with_explicit_files_when_test_files_changed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "argv", ["validate", "--pre"])
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("CI", raising=False)

        captured_cmds: list[list[str]] = []

        def tracking_run(cmd: list[str], **kwargs: object) -> MagicMock:
            captured_cmds.append(list(cmd))
            return _pre_mock_run(cmd, **kwargs)

        with (
            patch("scripts.checks._common.get_changed_files", return_value=["scripts/validate.py", "tests/test_validate.py"]),
            patch("scripts.checks._common.run", side_effect=tracking_run),
            patch("validate.validate_iam_runner_policy"),
            patch("validate.validate_prompt_files"),
            patch("validate.validate_cli_tools_in_prompts"),
            patch("time.monotonic", side_effect=itertools.chain([0.0], itertools.repeat(1.0))),
            pytest.raises(SystemExit) as exc_info,
        ):
            _validate.main()

        assert exc_info.value.code == 0
        pytest_cmds = [c for c in captured_cmds if "pytest" in c]
        assert pytest_cmds, "pytest not invoked"
        assert "tests/test_validate.py" in pytest_cmds[0], "explicit test file path not in pytest argv"
        assert "--picked" not in pytest_cmds[0], "--picked must not appear in pytest argv"
        assert "not integration" in pytest_cmds[0]

    def test_treats_pytest_exit_5_as_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "argv", ["validate", "--pre"])
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("CI", raising=False)

        def exit5_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.stdout = "agent/test-branch\n"
            result.stderr = ""
            result.returncode = 5 if "pytest" in cmd else 0
            return result

        with (
            patch("scripts.checks._common.get_changed_files", return_value=["tests/test_validate.py"]),
            patch("scripts.checks._common.run", side_effect=exit5_run),
            patch("validate.validate_iam_runner_policy"),
            patch("validate.validate_prompt_files"),
            patch("validate.validate_cli_tools_in_prompts"),
            patch("time.monotonic", side_effect=itertools.chain([0.0], itertools.repeat(1.0))),
            pytest.raises(SystemExit) as exc_info,
        ):
            _validate.main()

        assert exc_info.value.code != 0


@pytest.mark.usefixtures("_neutralized_pre_registry")
class TestPreModePytestSelection:
    """Regression tests locking the explicit-file pytest selection contract.

    Acceptance criteria from PLAN-ci-pre-gate-pytest-picked-noop:
    (a) changed test file -> pytest invoked with that explicit path, no --picked
    (b) exit 5 / 0-collected with changed test files -> failure (gate reddens)
    (c) no test files changed -> pytest not invoked at all
    """

    def test_explicit_path_in_argv_no_picked(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "argv", ["validate.py", "--pre"])
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("CI", raising=False)

        captured_cmds: list[list[str]] = []

        def tracking_run(cmd: list[str], **kwargs: object) -> MagicMock:
            captured_cmds.append(list(cmd))
            return _pre_mock_run(cmd, **kwargs)

        with (
            patch("scripts.checks._common.get_changed_files", return_value=["tests/test_x.py"]),
            patch("scripts.checks._common.run", side_effect=tracking_run),
            patch("validate.validate_iam_runner_policy"),
            patch("validate.validate_prompt_files"),
            patch("validate.validate_cli_tools_in_prompts"),
            patch("time.monotonic", side_effect=itertools.chain([0.0], itertools.repeat(1.0))),
            pytest.raises(SystemExit) as exc_info,
        ):
            _validate.main()

        assert exc_info.value.code == 0
        pytest_cmds = [c for c in captured_cmds if "pytest" in c]
        assert pytest_cmds, "pytest was not invoked despite changed test file"
        assert "tests/test_x.py" in pytest_cmds[0], "explicit file path missing from pytest argv"
        assert "--picked" not in pytest_cmds[0], "--picked must not appear (explicit-file transport)"

    def test_exit_5_with_changed_tests_reddens_gate(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "argv", ["validate.py", "--pre"])
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("CI", raising=False)

        def exit5_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.stdout = ""
            result.stderr = ""
            result.returncode = 5 if "pytest" in cmd else 0
            return result

        with (
            patch("scripts.checks._common.get_changed_files", return_value=["tests/test_x.py"]),
            patch("scripts.checks._common.run", side_effect=exit5_run),
            patch("validate.validate_iam_runner_policy"),
            patch("validate.validate_prompt_files"),
            patch("validate.validate_cli_tools_in_prompts"),
            patch("time.monotonic", side_effect=itertools.chain([0.0], itertools.repeat(1.0))),
            pytest.raises(SystemExit) as exc_info,
        ):
            _validate.main()

        assert exc_info.value.code != 0, "exit 5 / 0-collected with changed test files must redden the gate"

    def test_no_pytest_when_no_test_files_changed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "argv", ["validate.py", "--pre"])
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("CI", raising=False)

        captured_cmds: list[list[str]] = []

        def tracking_run(cmd: list[str], **kwargs: object) -> MagicMock:
            captured_cmds.append(list(cmd))
            return _pre_mock_run(cmd, **kwargs)

        with (
            patch("scripts.checks._common.get_changed_files", return_value=["scripts/validate.py", "scripts/sync/ops.py"]),
            patch("scripts.checks._common.run", side_effect=tracking_run),
            patch("validate.validate_iam_runner_policy"),
            patch("validate.validate_prompt_files"),
            patch("validate.validate_cli_tools_in_prompts"),
            patch("time.monotonic", side_effect=itertools.chain([0.0], itertools.repeat(1.0))),
            pytest.raises(SystemExit) as exc_info,
        ):
            _validate.main()

        assert exc_info.value.code == 0
        pytest_cmds = [c for c in captured_cmds if "pytest" in c]
        assert not pytest_cmds, f"pytest must not run when no test files changed, got: {pytest_cmds}"


@pytest.mark.usefixtures("_neutralized_pre_registry")
class TestBudgetAssertion:
    """Tests for the 5-minute fast-tier wall-clock budget assertion."""

    def test_exits_1_on_budget_breach(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "argv", ["validate", "--pre"])
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("CI", raising=False)

        with (
            patch("scripts.checks._common.get_changed_files", return_value=[]),
            patch("scripts.checks._common.run", side_effect=_pre_mock_run),
            patch("validate.validate_iam_runner_policy"),
            patch("validate.validate_prompt_files"),
            patch("validate.validate_cli_tools_in_prompts"),
            patch("validate._file_budget_breach_rec"),
            patch("time.monotonic", side_effect=itertools.chain([0.0], itertools.repeat(400.0))),
            pytest.raises(SystemExit) as exc_info,
        ):
            _validate.main()

        assert exc_info.value.code == 1

    def test_budget_breach_output_contains_diagnostic(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        monkeypatch.setattr(sys, "argv", ["validate", "--pre"])
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("CI", raising=False)

        with (
            patch("scripts.checks._common.get_changed_files", return_value=[]),
            patch("scripts.checks._common.run", side_effect=_pre_mock_run),
            patch("validate.validate_iam_runner_policy"),
            patch("validate.validate_prompt_files"),
            patch("validate.validate_cli_tools_in_prompts"),
            patch("validate._file_budget_breach_rec"),
            patch("time.monotonic", side_effect=itertools.chain([0.0], itertools.repeat(400.0))),
            pytest.raises(SystemExit),
        ):
            _validate.main()

        captured = capsys.readouterr()
        assert "Fast tier exceeded budget" in captured.out

    def test_exits_0_within_budget(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "argv", ["validate", "--pre"])
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("CI", raising=False)

        with (
            patch("scripts.checks._common.get_changed_files", return_value=[]),
            patch("scripts.checks._common.run", side_effect=_pre_mock_run),
            patch("validate.validate_iam_runner_policy"),
            patch("validate.validate_prompt_files"),
            patch("validate.validate_cli_tools_in_prompts"),
            patch("time.monotonic", side_effect=itertools.chain([0.0], itertools.repeat(60.0))),
            pytest.raises(SystemExit) as exc_info,
        ):
            _validate.main()

        assert exc_info.value.code == 0

    def test_budget_constant_is_300(self) -> None:
        assert _FAST_TIER_BUDGET_SECONDS == 300

    def test_breach_rec_receives_a_real_dominant_phase(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The dominant phase threaded to _file_budget_breach_rec must correctly identify WHICH
        step actually dominated the elapsed wall-clock -- not merely be non-None. Makes
        pytest_diff artificially slow (a real, attributable jump in the mocked clock) relative to
        every other near-zero step, so the assertion is on correctness of attribution, not just
        truthiness."""
        monkeypatch.setattr(sys, "argv", ["validate", "--pre"])
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("CI", raising=False)

        clock = {"t": 0.0}

        def fake_monotonic() -> float:
            return clock["t"]

        def slow_pytest_diff(changed_tests: list[str], failed: list[str]) -> None:
            clock["t"] += 1000.0  # dwarfs every other (near-zero) step's duration

        with (
            patch("scripts.checks._common.get_changed_files", return_value=[]),
            patch("scripts.checks._common.run", side_effect=_pre_mock_run),
            patch("validate.validate_iam_runner_policy"),
            patch("validate.validate_prompt_files"),
            patch("validate.validate_cli_tools_in_prompts"),
            patch("validate._file_budget_breach_rec") as mock_breach,
            patch("validate.run_pytest_diff", side_effect=slow_pytest_diff),
            patch("time.monotonic", side_effect=fake_monotonic),
            pytest.raises(SystemExit),
        ):
            _validate.main()

        dominant_phase_arg = mock_breach.call_args[0][2]
        assert dominant_phase_arg == "pytest_diff"

    def test_breach_console_error_names_dominant_phase(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """Same correctness bar as above, applied to the printed console diagnostic."""
        monkeypatch.setattr(sys, "argv", ["validate", "--pre"])
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("CI", raising=False)

        clock = {"t": 0.0}

        def fake_monotonic() -> float:
            return clock["t"]

        def slow_pytest_diff(changed_tests: list[str], failed: list[str]) -> None:
            clock["t"] += 1000.0

        with (
            patch("scripts.checks._common.get_changed_files", return_value=[]),
            patch("scripts.checks._common.run", side_effect=_pre_mock_run),
            patch("validate.validate_iam_runner_policy"),
            patch("validate.validate_prompt_files"),
            patch("validate.validate_cli_tools_in_prompts"),
            patch("validate._file_budget_breach_rec"),
            patch("validate.run_pytest_diff", side_effect=slow_pytest_diff),
            patch("time.monotonic", side_effect=fake_monotonic),
            pytest.raises(SystemExit),
        ):
            _validate.main()

        captured = capsys.readouterr()
        assert "Dominant phase: pytest_diff" in captured.out


@pytest.mark.usefixtures("_neutralized_pre_registry")
class TestIgnoreBudgetFlag:
    """Tests for the --ignore-budget escape hatch."""

    def test_bypass_calls_bypass_rec_helper(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "argv", ["validate", "--pre", "--ignore-budget"])
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("CI", raising=False)

        with (
            patch("scripts.checks._common.get_changed_files", return_value=[]),
            patch("scripts.checks._common.run", side_effect=_pre_mock_run),
            patch("validate.validate_iam_runner_policy"),
            patch("validate.validate_prompt_files"),
            patch("validate.validate_cli_tools_in_prompts"),
            patch("time.monotonic", side_effect=itertools.chain([0.0], itertools.repeat(60.0))),
            patch("validate._file_budget_bypass_rec") as mock_bypass,
            pytest.raises(SystemExit) as exc_info,
        ):
            _validate.main()

        assert exc_info.value.code == 0
        mock_bypass.assert_called_once()

    def test_bypass_reason_captured_when_provided(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "argv", ["validate", "--pre", "--ignore-budget", "--ignore-budget-reason", "disk slow"])
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("CI", raising=False)

        with (
            patch("scripts.checks._common.get_changed_files", return_value=[]),
            patch("scripts.checks._common.run", side_effect=_pre_mock_run),
            patch("validate.validate_iam_runner_policy"),
            patch("validate.validate_prompt_files"),
            patch("validate.validate_cli_tools_in_prompts"),
            patch("time.monotonic", side_effect=itertools.chain([0.0], itertools.repeat(60.0))),
            patch("validate._file_budget_bypass_rec") as mock_bypass,
            pytest.raises(SystemExit),
        ):
            _validate.main()

        reason_arg = mock_bypass.call_args[0][2]
        assert reason_arg == "disk slow"

    def test_bypass_reason_null_when_omitted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "argv", ["validate", "--pre", "--ignore-budget"])
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("CI", raising=False)

        with (
            patch("scripts.checks._common.get_changed_files", return_value=[]),
            patch("scripts.checks._common.run", side_effect=_pre_mock_run),
            patch("validate.validate_iam_runner_policy"),
            patch("validate.validate_prompt_files"),
            patch("validate.validate_cli_tools_in_prompts"),
            patch("time.monotonic", side_effect=itertools.chain([0.0], itertools.repeat(60.0))),
            patch("validate._file_budget_bypass_rec") as mock_bypass,
            pytest.raises(SystemExit),
        ):
            _validate.main()

        reason_arg = mock_bypass.call_args[0][2]
        assert reason_arg is None

    def test_bypass_skips_budget_assertion(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Breach rec is NOT filed when --ignore-budget is set, even if elapsed > 300."""
        monkeypatch.setattr(sys, "argv", ["validate", "--pre", "--ignore-budget"])
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("CI", raising=False)

        with (
            patch("scripts.checks._common.get_changed_files", return_value=[]),
            patch("scripts.checks._common.run", side_effect=_pre_mock_run),
            patch("validate.validate_iam_runner_policy"),
            patch("validate.validate_prompt_files"),
            patch("validate.validate_cli_tools_in_prompts"),
            patch("time.monotonic", side_effect=itertools.chain([0.0], itertools.repeat(400.0))),
            patch("validate._file_budget_bypass_rec"),
            patch("validate._file_budget_breach_rec") as mock_breach,
            pytest.raises(SystemExit) as exc_info,
        ):
            _validate.main()

        assert exc_info.value.code == 0
        mock_breach.assert_not_called()


@pytest.mark.usefixtures("_neutralized_pre_registry")
class TestIgnoreBudgetCIGuard:
    """Tests for the CI guard that forbids --ignore-budget in CI environments."""

    def test_refuses_ignore_budget_in_ci(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "argv", ["validate", "--pre", "--ignore-budget"])
        monkeypatch.setenv("CI", "true")
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

        with pytest.raises(SystemExit) as exc_info:
            _validate.main()

        assert exc_info.value.code == 1

    def test_ci_guard_message_contains_expected_phrase(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        monkeypatch.setattr(sys, "argv", ["validate", "--pre", "--ignore-budget"])
        monkeypatch.setenv("CI", "true")
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

        with pytest.raises(SystemExit):
            _validate.main()

        captured = capsys.readouterr()
        assert "cannot be used in CI" in captured.out

    def test_allows_ignore_budget_when_ci_not_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "argv", ["validate", "--pre", "--ignore-budget"])
        monkeypatch.delenv("CI", raising=False)
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

        with (
            patch("scripts.checks._common.get_changed_files", return_value=[]),
            patch("scripts.checks._common.run", side_effect=_pre_mock_run),
            patch("validate.validate_iam_runner_policy"),
            patch("validate.validate_prompt_files"),
            patch("validate.validate_cli_tools_in_prompts"),
            patch("time.monotonic", side_effect=itertools.chain([0.0], itertools.repeat(60.0))),
            patch("validate._file_budget_bypass_rec"),
            pytest.raises(SystemExit) as exc_info,
        ):
            _validate.main()

        assert exc_info.value.code == 0


class TestBudgetBreachRecFiling:
    """Tests for _file_budget_breach_rec and _file_budget_bypass_rec helpers.

    These exercise the LOCAL (non-CI) path -- CI-guard behaviour is covered separately by
    TestBudgetRecFilingCiGuard below. Every test here runs with CI unset regardless of the
    ambient environment (this file itself runs under CI="true" in the pr-validate/main-validate
    CI jobs), so the local-path assertions stay deterministic.
    """

    @pytest.fixture(autouse=True)
    def _no_ci(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CI", raising=False)

    def test_breach_rec_calls_file_rec_with_budget_breach_source(self) -> None:
        mock_portal = MagicMock()
        git_result = MagicMock(returncode=0, stdout="agent/test\n")

        with (
            patch("scripts.checks._common.run", return_value=git_result),
            patch.dict(sys.modules, {"scripts.ops_data_portal": mock_portal}),
        ):
            _file_budget_breach_rec(400.0, ["scripts/validate.py"], None)

        mock_portal.file_rec.assert_called_once()
        fields = mock_portal.file_rec.call_args[0][0]
        assert fields["source"] == "budget_breach"

    def test_breach_rec_context_contains_elapsed_and_manifest(self) -> None:
        mock_portal = MagicMock()
        git_result = MagicMock(returncode=0, stdout="agent/test\n")

        with (
            patch("scripts.checks._common.run", return_value=git_result),
            patch.dict(sys.modules, {"scripts.ops_data_portal": mock_portal}),
        ):
            _file_budget_breach_rec(400.0, ["scripts/validate.py", "tests/test_validate.py"], None)

        fields = mock_portal.file_rec.call_args[0][0]
        assert "scripts/validate.py" in fields["context"]
        assert "6.7 min" in fields["context"] or "6." in fields["context"]

    def test_breach_portal_exception_is_suppressed(self) -> None:
        mock_portal = MagicMock()
        mock_portal.file_rec.side_effect = RuntimeError("DynamoDB unreachable")
        git_result = MagicMock(returncode=0, stdout="agent/test\n")

        with (
            patch("scripts.checks._common.run", return_value=git_result),
            patch.dict(sys.modules, {"scripts.ops_data_portal": mock_portal}),
        ):
            # Must not raise
            _file_budget_breach_rec(400.0, [], None)

    def test_bypass_rec_calls_file_rec_with_budget_bypass_source(self) -> None:
        mock_portal = MagicMock()
        git_result = MagicMock(returncode=0, stdout="agent/test\n")

        with (
            patch("scripts.checks._common.run", return_value=git_result),
            patch.dict(sys.modules, {"scripts.ops_data_portal": mock_portal}),
        ):
            _file_budget_bypass_rec(60.0, ["scripts/validate.py"], "disk issue")

        mock_portal.file_rec.assert_called_once()
        fields = mock_portal.file_rec.call_args[0][0]
        assert fields["source"] == "budget_bypass"
        assert "disk issue" in fields["context"]

    def test_bypass_rec_reason_null_when_omitted(self) -> None:
        mock_portal = MagicMock()
        git_result = MagicMock(returncode=0, stdout="agent/test\n")

        with (
            patch("scripts.checks._common.run", return_value=git_result),
            patch.dict(sys.modules, {"scripts.ops_data_portal": mock_portal}),
        ):
            _file_budget_bypass_rec(60.0, [], None)

        fields = mock_portal.file_rec.call_args[0][0]
        assert "none provided" in fields["context"].lower()

    def test_bypass_portal_exception_is_suppressed(self) -> None:
        mock_portal = MagicMock()
        mock_portal.file_rec.side_effect = RuntimeError("DynamoDB unreachable")
        git_result = MagicMock(returncode=0, stdout="agent/test\n")

        with (
            patch("scripts.checks._common.run", return_value=git_result),
            patch.dict(sys.modules, {"scripts.ops_data_portal": mock_portal}),
        ):
            # Must not raise
            _file_budget_bypass_rec(60.0, [], None)

    def test_breach_priority_is_accepted_value(self) -> None:
        """_file_budget_breach_rec must pass a title-case priority (rec-2156)."""
        mock_portal = MagicMock()
        git_result = MagicMock(returncode=0, stdout="agent/test\n")

        with (
            patch("scripts.checks._common.run", return_value=git_result),
            patch.dict(sys.modules, {"scripts.ops_data_portal": mock_portal}),
        ):
            _file_budget_breach_rec(400.0, ["scripts/validate.py"], None)

        fields = mock_portal.file_rec.call_args[0][0]
        assert fields["priority"] in {"Critical", "High", "Medium", "Low"}

    def test_bypass_priority_is_accepted_value(self) -> None:
        """_file_budget_bypass_rec must pass a title-case priority (rec-2156)."""
        mock_portal = MagicMock()
        git_result = MagicMock(returncode=0, stdout="agent/test\n")

        with (
            patch("scripts.checks._common.run", return_value=git_result),
            patch.dict(sys.modules, {"scripts.ops_data_portal": mock_portal}),
        ):
            _file_budget_bypass_rec(60.0, ["scripts/validate.py"], "disk issue")

        fields = mock_portal.file_rec.call_args[0][0]
        assert fields["priority"] in {"Critical", "High", "Medium", "Low"}

    def test_breach_priority_survives_real_accepted_values_validator(self) -> None:
        """Anti-vacuous: the priority _file_budget_breach_rec passes must survive the REAL
        ops.yaml accepted_values validator, not just a hardcoded set in this test."""
        from scripts.ops_data_portal import _load_write_time_validators  # noqa: PLC0415

        mock_portal = MagicMock()
        git_result = MagicMock(returncode=0, stdout="agent/test\n")

        with (
            patch("scripts.checks._common.run", return_value=git_result),
            patch.dict(sys.modules, {"scripts.ops_data_portal": mock_portal}),
        ):
            _file_budget_breach_rec(400.0, ["scripts/validate.py"], None)

        priority = mock_portal.file_rec.call_args[0][0]["priority"]
        priority_validators = [fn for col, fn in _load_write_time_validators("ops_recommendations") if col == "priority"]
        assert priority_validators, "no priority validators loaded from ops.yaml"
        for validator in priority_validators:
            validator(priority, "priority")  # must not raise

    def test_bypass_priority_survives_real_accepted_values_validator(self) -> None:
        """Anti-vacuous: the priority _file_budget_bypass_rec passes must survive the REAL
        ops.yaml accepted_values validator, not just a hardcoded set in this test."""
        from scripts.ops_data_portal import _load_write_time_validators  # noqa: PLC0415

        mock_portal = MagicMock()
        git_result = MagicMock(returncode=0, stdout="agent/test\n")

        with (
            patch("scripts.checks._common.run", return_value=git_result),
            patch.dict(sys.modules, {"scripts.ops_data_portal": mock_portal}),
        ):
            _file_budget_bypass_rec(60.0, ["scripts/validate.py"], "disk issue")

        priority = mock_portal.file_rec.call_args[0][0]["priority"]
        priority_validators = [fn for col, fn in _load_write_time_validators("ops_recommendations") if col == "priority"]
        assert priority_validators, "no priority validators loaded from ops.yaml"
        for validator in priority_validators:
            validator(priority, "priority")  # must not raise


class TestBudgetRecFilingCiGuard:
    """CI-guard on the budget rec-filing helpers (Decision 84 I-4 / ULID anomaly root cause).

    The pr-validate CI job installs requirements-fast.txt (no python-ulid) and configures no AWS
    credentials, so a real portal file_rec() write there raises a swallowed ModuleNotFoundError
    from ducklake_runtime's mint_write_identity. With CI=="true" neither helper may even attempt
    the portal import -- it must print a loud diagnostic instead (never a silent skip, never a
    buffered outbox entry).
    """

    def test_breach_rec_skips_file_rec_under_ci(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CI", "true")
        mock_portal = MagicMock()

        with (
            patch("scripts.checks._common.run") as mock_run,
            patch.dict(sys.modules, {"scripts.ops_data_portal": mock_portal}),
        ):
            _file_budget_breach_rec(400.0, ["scripts/validate.py"], "pytest_diff")

        mock_portal.file_rec.assert_not_called()
        mock_run.assert_not_called()

    def test_breach_rec_prints_diagnostic_under_ci(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        monkeypatch.setenv("CI", "true")

        _file_budget_breach_rec(400.0, ["scripts/validate.py"], "pytest_diff")

        captured = capsys.readouterr()
        assert "pytest_diff" in captured.err
        assert "400.0" not in captured.err  # sanity: elapsed is rendered as minutes, not raw seconds
        assert "6.7" in captured.err or "6." in captured.err

    def test_breach_rec_calls_file_rec_when_ci_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CI", raising=False)
        mock_portal = MagicMock()
        git_result = MagicMock(returncode=0, stdout="agent/test\n")

        with (
            patch("scripts.checks._common.run", return_value=git_result),
            patch.dict(sys.modules, {"scripts.ops_data_portal": mock_portal}),
        ):
            _file_budget_breach_rec(400.0, ["scripts/validate.py"], "pytest_diff")

        mock_portal.file_rec.assert_called_once()

    def test_bypass_rec_skips_file_rec_under_ci(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CI", "true")
        mock_portal = MagicMock()

        with (
            patch("scripts.checks._common.run") as mock_run,
            patch.dict(sys.modules, {"scripts.ops_data_portal": mock_portal}),
        ):
            _file_budget_bypass_rec(60.0, ["scripts/validate.py"], "disk issue")

        mock_portal.file_rec.assert_not_called()
        mock_run.assert_not_called()

    def test_bypass_rec_prints_diagnostic_under_ci(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        monkeypatch.setenv("CI", "true")

        _file_budget_bypass_rec(60.0, ["scripts/validate.py"], "disk issue")

        captured = capsys.readouterr()
        assert "disk issue" in captured.err

    def test_bypass_rec_calls_file_rec_when_ci_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CI", raising=False)
        mock_portal = MagicMock()
        git_result = MagicMock(returncode=0, stdout="agent/test\n")

        with (
            patch("scripts.checks._common.run", return_value=git_result),
            patch.dict(sys.modules, {"scripts.ops_data_portal": mock_portal}),
        ):
            _file_budget_bypass_rec(60.0, ["scripts/validate.py"], "disk issue")

        mock_portal.file_rec.assert_called_once()


class TestBudgetBreachCiTelemetry:
    """CI-native budget-breach telemetry (pre-validation-performance / rec-2387): with
    CI="true" and GITHUB_STEP_SUMMARY set, _file_budget_breach_rec writes dominant_phase +
    the diff manifest to that file, files no rec, and stages no outbox entry."""

    def test_writes_dominant_phase_and_manifest_to_step_summary(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("CI", "true")
        summary_file = tmp_path / "step-summary.md"
        monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_file))
        mock_portal = MagicMock()

        with (
            patch("scripts.checks._common.run") as mock_run,
            patch.dict(sys.modules, {"scripts.ops_data_portal": mock_portal}),
        ):
            _file_budget_breach_rec(400.0, ["scripts/validate.py", "tests/test_validate.py"], "pytest_diff")

        content = summary_file.read_text(encoding="utf-8")
        assert "pytest_diff" in content
        assert "scripts/validate.py" in content
        mock_portal.file_rec.assert_not_called()
        mock_run.assert_not_called()

    def test_no_ops_outbox_staged(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("CI", "true")
        summary_file = tmp_path / "step-summary.md"
        monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_file))
        outbox_dir = tmp_path / "logs" / ".ops-outbox"

        with patch("scripts.checks._common.run") as mock_run:
            _file_budget_breach_rec(400.0, ["scripts/validate.py"], "pytest_diff")

        mock_run.assert_not_called()
        assert not outbox_dir.exists()

    def test_falls_back_to_stderr_when_step_summary_unset(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        monkeypatch.setenv("CI", "true")
        monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)

        _file_budget_breach_rec(400.0, ["scripts/validate.py"], "pytest_diff")

        captured = capsys.readouterr()
        assert "pytest_diff" in captured.err


@pytest.mark.usefixtures("_neutralized_pre_registry")
class TestSlocLimitsInPreMode:
    """Assert validate_sloc_limits runs in the --pre tier (rec-2106 RCA fix)."""

    def test_sloc_limits_called_in_pre_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """validate_sloc_limits must be invoked during --pre alongside validate_cc_limits."""
        monkeypatch.setattr(sys, "argv", ["validate", "--pre"])
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("CI", raising=False)

        sloc_called = []

        def capture_sloc(failed: list[str]) -> None:
            sloc_called.append(True)

        with (
            patch("scripts.checks._common.get_changed_files", return_value=[]),
            patch("scripts.checks._common.run", side_effect=_pre_mock_run),
            patch("validate.validate_iam_runner_policy"),
            patch("validate.validate_prompt_files"),
            patch("validate.validate_cli_tools_in_prompts"),
            patch("validate.validate_sloc_limits", side_effect=capture_sloc),
            patch("time.monotonic", side_effect=itertools.chain([0.0], itertools.repeat(1.0))),
            pytest.raises(SystemExit) as exc_info,
        ):
            _validate.main()

        assert exc_info.value.code == 0
        assert sloc_called, "validate_sloc_limits was NOT called in --pre mode"

    def test_sloc_limits_called_after_cc_limits_in_pre(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """validate_sloc_limits is called in the same --pre block as validate_cc_limits."""
        monkeypatch.setattr(sys, "argv", ["validate", "--pre"])
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("CI", raising=False)

        call_order: list[str] = []

        def capture_cc(failed: list[str]) -> None:
            call_order.append("cc")

        def capture_sloc(failed: list[str]) -> None:
            call_order.append("sloc")

        with (
            patch("scripts.checks._common.get_changed_files", return_value=[]),
            patch("scripts.checks._common.run", side_effect=_pre_mock_run),
            patch("validate.validate_iam_runner_policy"),
            patch("validate.validate_prompt_files"),
            patch("validate.validate_cli_tools_in_prompts"),
            patch("validate.validate_cc_limits", side_effect=capture_cc),
            patch("validate.validate_sloc_limits", side_effect=capture_sloc),
            patch("time.monotonic", side_effect=itertools.chain([0.0], itertools.repeat(1.0))),
            pytest.raises(SystemExit),
        ):
            _validate.main()

        assert "cc" in call_order, "validate_cc_limits not called in --pre mode"
        assert "sloc" in call_order, "validate_sloc_limits not called in --pre mode"
        cc_idx = call_order.index("cc")
        sloc_idx = call_order.index("sloc")
        assert cc_idx < sloc_idx, "validate_sloc_limits must be called after validate_cc_limits"


class TestGetChangedFilesDeletedPaths:
    """Assert get_changed_files() drops deleted (non-existent) paths before returning."""

    def test_drops_deleted_file(self, tmp_path: Path) -> None:
        """A file listed by git diff but absent on disk is excluded from the result."""
        existing = tmp_path / "scripts" / "exists.py"
        existing.parent.mkdir()
        existing.write_text("x = 1\n", encoding="utf-8")

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.returncode = 0
            result.stdout = "scripts/exists.py\nscripts/deleted_gone.py\n"
            return result

        with (
            patch("scripts.checks._common.run", side_effect=mock_run),
            patch("scripts.checks._common.ROOT", tmp_path),
        ):
            files = get_changed_files()

        assert "scripts/exists.py" in files
        assert "scripts/deleted_gone.py" not in files

    def test_all_deleted_returns_empty(self, tmp_path: Path) -> None:
        """When all listed files are deleted, the result is an empty list."""

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.returncode = 0
            result.stdout = "scripts/migrate_ops_iceberg_to_ducklake.py\ntests/test_migrate_ops_iceberg_to_ducklake.py\n"
            return result

        with (
            patch("scripts.checks._common.run", side_effect=mock_run),
            patch("scripts.checks._common.ROOT", tmp_path),
        ):
            files = get_changed_files()

        assert files == []

    def test_existing_files_all_returned(self, tmp_path: Path) -> None:
        """When all listed files exist on disk, none are filtered out."""
        for name in ("a.py", "b.py"):
            f = tmp_path / name
            f.write_text("x = 1\n", encoding="utf-8")

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.returncode = 0
            result.stdout = "a.py\nb.py\n"
            return result

        with (
            patch("scripts.checks._common.run", side_effect=mock_run),
            patch("scripts.checks._common.ROOT", tmp_path),
        ):
            files = get_changed_files()

        assert sorted(files) == ["a.py", "b.py"]


@pytest.mark.usefixtures("_neutralized_pre_registry")
class TestPreModeChecks:
    """Assert validate_subprocess_encoding runs in the --pre tier (rec-2382 RCA fix)."""

    def test_pre_mode_calls_subprocess_encoding(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """validate_subprocess_encoding must be invoked during --pre (tier-membership regression guard)."""
        monkeypatch.setattr(sys, "argv", ["validate", "--pre"])
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("CI", raising=False)

        encoding_called = []

        def capture_encoding(failed: list[str]) -> None:
            encoding_called.append(True)

        with (
            patch("scripts.checks._common.get_changed_files", return_value=[]),
            patch("scripts.checks._common.run", side_effect=_pre_mock_run),
            patch("validate.validate_iam_runner_policy"),
            patch("validate.validate_prompt_files"),
            patch("validate.validate_cli_tools_in_prompts"),
            patch("validate.validate_subprocess_encoding", side_effect=capture_encoding),
            patch("time.monotonic", side_effect=itertools.chain([0.0], itertools.repeat(1.0))),
            pytest.raises(SystemExit) as exc_info,
        ):
            _validate.main()

        assert exc_info.value.code == 0
        assert encoding_called, "validate_subprocess_encoding was NOT called in --pre mode"


@pytest.mark.usefixtures("_neutralized_pre_registry")
class TestPreModeRegistryIsolation:
    """Isolation-guard test (defect 2 lock-in): proves the real check registry is not
    executed inside a neutralized --pre main() call, so a future edit that silently
    reintroduces full-registry execution (and its wall-clock cost) is caught here instead
    of resurfacing as a slow/flaky fast-tier gate."""

    def test_real_registry_check_not_invoked_under_neutralization(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """validate_import_contracts prints a distinctive banner when it actually runs
        (see scripts/checks/deps/validate_import_contracts.py); the neutralization fixture
        replaces it with a plain no-op MagicMock, so that banner must never appear here.
        """
        monkeypatch.setattr(sys, "argv", ["validate", "--pre"])
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("CI", raising=False)

        with (
            patch("scripts.checks._common.get_changed_files", return_value=[]),
            patch("scripts.checks._common.run", side_effect=_pre_mock_run),
            patch("time.monotonic", side_effect=itertools.chain([0.0], itertools.repeat(1.0))),
            pytest.raises(SystemExit) as exc_info,
        ):
            _validate.main()

        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "Import contracts (Decision 80" not in captured.out, (
            "validate_import_contracts printed its real banner -- the real check ran "
            "instead of being neutralized by the _neutralized_pre_registry fixture"
        )


# ---------------------------------------------------------------------------
# same_pr_guard tests (T3.1)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# verification_registry tests (T3.1)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# VF-06 c2/c3 differential-execution branch tests (T3.18, audit-remediation-wave-4)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# differential_gate_step tests (T3.1)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# platform_roadmap ExitCriterion tests (T3.1 structured criteria)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# VP selector hooks for test_validate.py
# Standalone functions named so that `pytest -k <selector>` collects them.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# validate_import_contracts (Decision 80 / T3.11 wrapper)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# validate_lockfile_sync (Decision 80 / T3.11 wrapper)
# ---------------------------------------------------------------------------


class TestPreRoadmapGuardSelection:
    """ci-rca-cd25-ratification-tier-gap -- select_roadmap_guard_tests() dynamically pulls tests/ files that reference
    a roadmap YAML into the --pre fast tier's changed_tests set whenever a roadmap YAML
    appears in the diff, so live-roadmap guard tests stop being tier_misplaced (they used
    to run only in the full post-merge tier)."""

    select_roadmap_guard_tests = staticmethod(_validate.select_roadmap_guard_tests)

    def _make_tests_dir(self, tmp_path: Path) -> None:
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_roadmap_guard.py").write_text('ROADMAP = "ROADMAP-PLATFORM.yaml"\n', encoding="utf-8")
        (tests_dir / "test_unrelated.py").write_text("def test_x():\n    assert True\n", encoding="utf-8")
        pycache_dir = tests_dir / "__pycache__"
        pycache_dir.mkdir()
        (pycache_dir / "test_roadmap_guard.cpython-312.pyc").write_bytes(b"ROADMAP-PLATFORM.yaml")

    def test_roadmap_yaml_in_diff_selects_guard_tests(self, tmp_path: Path) -> None:
        self._make_tests_dir(tmp_path)
        result = self.select_roadmap_guard_tests(["docs/ROADMAP-PLATFORM.yaml"], repo_root=tmp_path)
        assert result == ["tests/test_roadmap_guard.py"]

    def test_no_roadmap_yaml_in_diff_does_not_force_select(self, tmp_path: Path) -> None:
        self._make_tests_dir(tmp_path)
        result = self.select_roadmap_guard_tests(["scripts/validate.py"], repo_root=tmp_path)
        assert result == []

    def test_pycache_paths_excluded(self, tmp_path: Path) -> None:
        self._make_tests_dir(tmp_path)
        result = self.select_roadmap_guard_tests(["docs/ROADMAP-PLATFORM.yaml"], repo_root=tmp_path)
        assert all("__pycache__" not in f and f.endswith(".py") for f in result)

    def test_product_roadmap_yaml_also_triggers_selection(self, tmp_path: Path) -> None:
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_product_guard.py").write_text('ROADMAP = "ROADMAP-PRODUCT.yaml"\n', encoding="utf-8")
        result = self.select_roadmap_guard_tests(["docs/ROADMAP-PRODUCT.yaml"], repo_root=tmp_path)
        assert result == ["tests/test_product_guard.py"]


# ---------------------------------------------------------------------------
# validate_vp_replay (T3.15 c2, VF-01, Decision 104) -- audit-wave-6-vp-replay
# ---------------------------------------------------------------------------
