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
    """Wave-invariant retirement oracle (Decision 131). map_source_to_test resolves each roster
    home via the pre-inversion colocation rule while it is grandfathered (its basename is in
    _RETIRING_GRANDFATHER_HOMES) and via the mirror / concern-split rule once a wave retires it. A
    wave retires a home by deleting its one basename line from _RETIRING_GRANDFATHER_HOMES AND
    deleting its flat monolith tests/<home>. These tests derive the retirement state from the frozen
    roster and the tests/ tree itself -- there is no per-wave minus_N literal to hand-edit -- so each
    wave stays green by construction and none of them is a per-wave merge-conflict surface."""

    def test_representative_paths_resolve_to_their_stable_targets(self) -> None:
        """A FROZEN representative sample -- one source per resolution pattern -- proving
        map_source_to_test produces the correct target shape: checks-mirror, concern-split package
        DIR, package-mirror 1:1, non-roster grandfathered sibling, the KEPT ducklake special-cases,
        and Decision-124 None. Every case is already-retired or permanently-classified, so the
        sample is wave-invariant: DO NOT append a per-wave case here -- the retirement-state and
        gate-flip tests below carry the moving parts."""
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
            ROOT / "scripts" / "sync" / "ops.py": ROOT / "tests" / "sync" / "ops",
            ROOT / "scripts" / "session" / "postflight.py": ROOT / "tests" / "session" / "postflight",
            ROOT / "scripts" / "ci_rca" / "evidence.py": ROOT / "tests" / "ci_rca" / "evidence",
            ROOT / "scripts" / "sync" / "recommendations.py": ROOT / "tests" / "test_sync_recommendations.py",
            ROOT / "scripts" / "ci_rca" / "filing.py": ROOT / "tests" / "test_ci_rca_filing.py",
            ROOT / "scripts" / "session" / "metrics.py": ROOT / "tests" / "test_session_metrics.py",
            ROOT / "scripts" / "convergence_health" / "record.py": ROOT / "tests" / "convergence_health" / "test_record.py",
            ROOT / "src" / "common" / "config.py": ROOT / "tests" / "test_config.py",
            ROOT / "scripts" / "executor" / "step_runner.py": None,
            ROOT / "scripts" / "executor" / "plan.py": None,
            ROOT / "scripts" / "executor" / "postflight.py": None,
            ROOT / "scripts" / "ops_portal" / "cli.py": None,
            ROOT / "src" / "common" / "ducklake_writes.py": ROOT / "tests" / "common" / "test_ducklake_writes.py",
            ROOT / "src" / "common" / "ducklake_runtime.py": ROOT / "tests" / "common" / "test_ducklake_runtime.py",
            ROOT / "scripts" / "ducklake_neon_smoke_test.py": ROOT / "tests" / "ducklake_neon_smoke_test",
        }
        for source, expected in cases.items():
            assert map_source_to_test(source) == expected, source

    def test_retiring_homes_are_a_subset_of_the_frozen_roster(self) -> None:
        """A wave only ever DELETES a basename from _RETIRING_GRANDFATHER_HOMES; it never adds one
        outside the frozen roster. So _RETIRING is always a subset of _ALL_MIRROR_TARGET_HOMES --
        a guard against a typo'd or off-roster basename being introduced during a retirement."""
        assert _RETIRING_GRANDFATHER_HOMES <= _ALL_MIRROR_TARGET_HOMES

    def test_retirement_state_matches_the_tests_tree(self) -> None:
        """The load-bearing wave-invariant: a roster home is grandfathered (in _RETIRING) IFF its
        flat monolith tests/<home> still exists. Retiring a home IS the act of deleting that flat
        file (replaced by a mirror package/module), so this derives the retirement state from the
        tree instead of a hand-maintained minus_N literal -- no wave edits this test; it stays green
        as each wave deletes both the _RETIRING line and the flat file together. Replaces the former
        test_retiring_is_all_target_homes_minus_N_retired_waves conflict-magnet (rec-2709)."""
        for home in _ALL_MIRROR_TARGET_HOMES:
            flat = ROOT / "tests" / home
            if home in _RETIRING_GRANDFATHER_HOMES:
                assert flat.is_file(), f"grandfathered home is missing its flat monolith: {home}"
            else:
                assert not flat.exists(), f"retired home still has a flat monolith: {home}"

    def test_gate_flips_colocation_to_mirror_on_retirement(self, monkeypatch) -> None:
        """The _RETIRING gate is precisely what flips a source from its pre-inversion colocation
        target to its mirror. Demonstrated on an already-retired PLAIN package-mirror home
        (test_convergence_health.py) so no future wave restales the example: in the real (retired)
        state the source resolves to its 1:1 mirror; re-adding the home to the gate flips it back to
        the grandfathered flat-file colocation target."""
        source = ROOT / "scripts" / "convergence_health" / "record.py"
        mirror = ROOT / "tests" / "convergence_health" / "test_record.py"
        colocated = ROOT / "tests" / "test_convergence_health.py"
        assert map_source_to_test(source) == mirror
        monkeypatch.setattr(
            checker,
            "_RETIRING_GRANDFATHER_HOMES",
            _RETIRING_GRANDFATHER_HOMES | {"test_convergence_health.py"},
        )
        assert map_source_to_test(source) == colocated

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
