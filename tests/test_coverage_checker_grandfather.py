"""Tests for the retiring grandfather table and the concern-split directory-target checks.

Split from the former tests/test_coverage_checker.py monolith (rec-2709 Wave 6b -- SLOC governance
per Decision 128, not a mirror-roster retirement). See tests/fixtures/coverage_checker_module.py
for the shared module-under-test singleton.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

from tests.fixtures.coverage_checker_module import _ALL_MIRROR_TARGET_HOMES, _RETIRING_GRANDFATHER_HOMES, ROOT, checker

map_source_to_test = checker.map_source_to_test
check_test_file_exists = checker.check_test_file_exists
check_per_file_coverage = checker.check_per_file_coverage


class TestGrandfatherRetiringTable:
    """Behaviour-preservation invariant (Decision 131): map_source_to_test resolves each
    roster home via colocation while it is grandfathered, and via the mirror rule once a wave
    retires it -- rec-2709 Wave 1 (PLAN-sloc-test-validate) retired the first of the 24,
    "test_validate.py"; Wave 2 (PLAN-sloc-execute-recommendation) retired the second,
    "test_execute_recommendation.py"; Wave 3 (PLAN-sloc-ops-data-portal-tests) retired the
    third, "test_ops_data_portal.py"; Wave 4 (PLAN-sloc-session-preflight-tests) retired the
    fourth, "test_session_preflight.py" (surgically -- its flat-file sibling
    "test_session_postflight.py" stays grandfathered until its own later wave); Wave 5
    (PLAN-sloc-executor-tests) retired the fifth, sixth, and seventh -- "test_executor_plan.py",
    "test_executor_postflight.py", and "test_executor_step_runner.py" -- a PURE test-file split
    with a no-op mapping consequence (their sources, scripts/executor/**, already returned None
    per Decision 124, so the retirement is bookkeeping/tidiness only, not a mapping flip); Wave 6
    retired the eighth, "test_convergence_health.py" -- a PACKAGE-MIRROR, not a concern-split;
    Wave 7 (PLAN-sloc-ducklake-runtime-smoke-tests) retired the ninth and tenth,
    "test_ducklake_runtime.py" (a MIRROR, with the _DUCKLAKE_RUNTIME_SPLIT_MODULES special-case
    KEPT -- see test_maps_ducklake_runtime_split_modules_resolve_to_their_common_mirror) and
    "test_ducklake_neon_smoke_test.py" (a CONCERN-SPLIT, already seeded in
    _CONCERN_SPLIT_TEST_PACKAGES before this wave)."""

    def test_representative_paths_resolve_under_current_retirement_state(self) -> None:
        """A representative path set resolves under the CURRENT retirement state: Waves 1-7's
        seven retired homes resolve via their mirror / concern-split / package-mirror, the other
        14 roster homes stay grandfathered, scripts/executor/** + scripts/ops_portal/** keep
        returning None (Decision 124), and scripts/session/postflight.py + metrics.py are
        surgical-retirement controls that stay grandfathered."""
        cases: dict[Path, Path | None] = {
            ROOT / "scripts" / "checks" / "hygiene" / "validate_prose_allowlist.py": ROOT
            / "tests"
            / "checks"
            / "hygiene"
            / "test_validate_prose_allowlist.py",
            ROOT / "scripts" / "validate.py": ROOT / "tests" / "validate",
            ROOT / "scripts" / "checks" / "_scaffolding.py": ROOT / "tests" / "validate",
            ROOT / "scripts" / "checks" / "_terraform.py": ROOT / "tests" / "validate",
            ROOT / "scripts" / "execute_recommendation.py": ROOT / "tests" / "execute_recommendation",
            ROOT / "scripts" / "ops_data_portal.py": ROOT / "tests" / "ops_data_portal",
            ROOT / "scripts" / "session" / "preflight.py": ROOT / "tests" / "session" / "preflight",
            ROOT / "scripts" / "session" / "postflight.py": ROOT / "tests" / "test_session_postflight.py",
            ROOT / "scripts" / "session" / "metrics.py": ROOT / "tests" / "test_session_metrics.py",
            ROOT / "scripts" / "convergence_health" / "record.py": ROOT / "tests" / "convergence_health" / "test_record.py",
            ROOT / "src" / "common" / "config.py": ROOT / "tests" / "test_config.py",
            ROOT / "scripts" / "executor" / "step_runner.py": None,
            ROOT / "scripts" / "executor" / "plan.py": None,
            ROOT / "scripts" / "executor" / "postflight.py": None,
            ROOT / "scripts" / "ops_portal" / "cli.py": None,
            ROOT / "src" / "common" / "iceberg_reader.py": ROOT / "tests" / "test_iceberg_reader.py",
            ROOT / "src" / "common" / "ducklake_writes.py": ROOT / "tests" / "common" / "test_ducklake_writes.py",
            ROOT / "src" / "common" / "ducklake_runtime.py": ROOT / "tests" / "common" / "test_ducklake_runtime.py",
            ROOT / "scripts" / "ducklake_neon_smoke_test.py": ROOT / "tests" / "ducklake_neon_smoke_test",
        }
        for source, expected in cases.items():
            assert map_source_to_test(source) == expected, source

    def test_retiring_is_all_target_homes_minus_ten_retired_waves(self) -> None:
        """Ten basenames retired so far (Waves 1-7); Wave 6 added "test_convergence_health.py"
        (a PACKAGE-MIRROR, NOT added to _CONCERN_SPLIT_TEST_PACKAGES); Wave 7 added
        "test_ducklake_runtime.py" (a MIRROR, special-case KEPT) and
        "test_ducklake_neon_smoke_test.py" (a CONCERN-SPLIT, already seeded)."""
        retired = {
            "test_validate.py",
            "test_execute_recommendation.py",
            "test_ops_data_portal.py",
            "test_session_preflight.py",
            "test_executor_plan.py",
            "test_executor_postflight.py",
            "test_executor_step_runner.py",
            "test_convergence_health.py",
            "test_ducklake_runtime.py",
            "test_ducklake_neon_smoke_test.py",
        }
        assert _RETIRING_GRANDFATHER_HOMES == _ALL_MIRROR_TARGET_HOMES - retired
        assert "test_validate.py" not in _RETIRING_GRANDFATHER_HOMES
        assert "test_execute_recommendation.py" not in _RETIRING_GRANDFATHER_HOMES
        assert "test_ops_data_portal.py" not in _RETIRING_GRANDFATHER_HOMES
        assert "test_session_preflight.py" not in _RETIRING_GRANDFATHER_HOMES
        assert "test_executor_plan.py" not in _RETIRING_GRANDFATHER_HOMES
        assert "test_executor_postflight.py" not in _RETIRING_GRANDFATHER_HOMES
        assert "test_executor_step_runner.py" not in _RETIRING_GRANDFATHER_HOMES
        assert "test_convergence_health.py" not in _RETIRING_GRANDFATHER_HOMES
        assert "test_ducklake_runtime.py" not in _RETIRING_GRANDFATHER_HOMES
        assert "test_ducklake_neon_smoke_test.py" not in _RETIRING_GRANDFATHER_HOMES
        assert "test_session_postflight.py" in _RETIRING_GRANDFATHER_HOMES
        assert _ALL_MIRROR_TARGET_HOMES - _RETIRING_GRANDFATHER_HOMES == retired

    def test_roster_is_the_24_known_basenames(self) -> None:
        """The fixed rec-2709 roster matches the 24 dec-130 config/sloc_budgets.yaml entries
        (frozen membership -- retiring a home deletes it from _RETIRING_GRANDFATHER_HOMES only,
        never from this frozenset)."""
        expected = {
            "test_build_lambda_deploy.py",
            "test_ci_rca_evidence.py",
            "test_contracts_enforcement.py",
            "test_convergence_health.py",
            "test_ducklake_maintenance_handler.py",
            "test_ducklake_neon_smoke_test.py",
            "test_ducklake_runtime.py",
            "test_ducklake_writer_handler.py",
            "test_execute_recommendation.py",
            "test_executor_plan.py",
            "test_executor_postflight.py",
            "test_executor_step_runner.py",
            "test_iceberg_reader.py",
            "test_lambda_manifest.py",
            "test_ops_data_portal.py",
            "test_ops_writer.py",
            "test_platform_roadmap_state.py",
            "test_s3_log_store.py",
            "test_scheduled_agent_handler.py",
            "test_session_postflight.py",
            "test_session_preflight.py",
            "test_sync_ops.py",
            "test_validate.py",
            "test_verify_ci_workflow.py",
        }
        assert _ALL_MIRROR_TARGET_HOMES == expected
        assert (
            len(_ALL_MIRROR_TARGET_HOMES) == 24
        )  # count-coupling-ok: fixed historical roster of the 24 rec-2709 targets, not a growing collection


class TestCheckTestFileExistsDirectoryTarget:
    """Tests for check_test_file_exists() with a concern-split test PACKAGE DIRECTORY target."""

    def test_directory_target_passes_when_populated(self, tmp_path: Path) -> None:
        test_dir = tmp_path / "tests" / "ops_writer"
        test_dir.mkdir(parents=True)
        (test_dir / "test_write_paths.py").write_text("# tests", encoding="utf-8")

        with (
            patch("test_coverage_checker.map_source_to_test", return_value=test_dir),
            patch("test_coverage_checker.ROOT", tmp_path),
        ):
            ok, msg = check_test_file_exists(tmp_path / "scripts" / "ops_writer.py")

        assert ok is True
        assert "package" in msg

    def test_directory_target_fails_when_empty(self, tmp_path: Path) -> None:
        test_dir = tmp_path / "tests" / "ops_writer"
        test_dir.mkdir(parents=True)  # exists, but no test_*.py yet

        with (
            patch("test_coverage_checker.map_source_to_test", return_value=test_dir),
            patch("test_coverage_checker.ROOT", tmp_path),
        ):
            ok, msg = check_test_file_exists(tmp_path / "scripts" / "ops_writer.py")

        assert ok is False
        assert "missing test package" in msg

    def test_directory_target_fails_when_absent(self, tmp_path: Path) -> None:
        test_dir = tmp_path / "tests" / "ops_writer"  # never created

        with (
            patch("test_coverage_checker.map_source_to_test", return_value=test_dir),
            patch("test_coverage_checker.ROOT", tmp_path),
        ):
            ok, msg = check_test_file_exists(tmp_path / "scripts" / "ops_writer.py")

        assert ok is False
        assert "missing test package" in msg


class TestCheckPerFileCoverageDirectoryTarget:
    """Drives the day-one-dormant directory branch of check_per_file_coverage: once a home
    retires, its concern-split mirror target is a test PACKAGE DIRECTORY, and coverage must run
    pytest against that directory rather than a single file. subprocess is mocked throughout."""

    def test_runs_pytest_against_directory_target(self, tmp_path: Path) -> None:
        source = tmp_path / "scripts" / "ops_writer.py"
        source.parent.mkdir(parents=True)
        source.write_text("# source", encoding="utf-8")

        test_dir = tmp_path / "tests" / "ops_writer"
        test_dir.mkdir(parents=True)
        (test_dir / "test_write_paths.py").write_text("# tests", encoding="utf-8")

        with (
            patch("test_coverage_checker.ROOT", tmp_path),
            patch("test_coverage_checker.map_source_to_test", return_value=test_dir),
            patch("test_coverage_checker.subprocess.Popen") as mock_popen,
        ):
            mock_proc = MagicMock()
            mock_proc.communicate.return_value = (None, None)
            mock_popen.return_value.__enter__.return_value = mock_proc

            errors = check_per_file_coverage([source])

        assert errors == []
        called_cmd = mock_popen.call_args.args[0]
        assert "tests/ops_writer" in called_cmd

    def test_skips_directory_target_with_no_test_files(self, tmp_path: Path) -> None:
        source = tmp_path / "scripts" / "ops_writer.py"
        source.parent.mkdir(parents=True)
        source.write_text("# source", encoding="utf-8")

        test_dir = tmp_path / "tests" / "ops_writer"
        test_dir.mkdir(parents=True)  # empty -- no test_*.py yet

        with (
            patch("test_coverage_checker.ROOT", tmp_path),
            patch("test_coverage_checker.map_source_to_test", return_value=test_dir),
            patch("test_coverage_checker.subprocess.Popen") as mock_popen,
        ):
            errors = check_per_file_coverage([source])

        assert errors == []
        mock_popen.assert_not_called()
