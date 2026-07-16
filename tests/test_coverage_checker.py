"""Tests for scripts/test_coverage_checker.py."""

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_SCRIPT_PATH = Path(__file__).parent.parent / "scripts" / "test_coverage_checker.py"
_spec = importlib.util.spec_from_file_location("test_coverage_checker", _SCRIPT_PATH)
_checker = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(_checker)  # type: ignore[union-attr]
sys.modules["test_coverage_checker"] = _checker

extract_definitions = _checker.extract_definitions
map_source_to_test = _checker.map_source_to_test
check_test_file_exists = _checker.check_test_file_exists
check_per_file_coverage = _checker.check_per_file_coverage
get_changed_source_files = _checker.get_changed_source_files
ROOT = _checker.ROOT
_ALL_MIRROR_TARGET_HOMES = _checker._ALL_MIRROR_TARGET_HOMES
_RETIRING_GRANDFATHER_HOMES = _checker._RETIRING_GRANDFATHER_HOMES


class TestExtractDefinitions:
    """Tests for extract_definitions()."""

    def test_extracts_top_level_function(self, tmp_path: Path) -> None:
        """Module-level function names are extracted."""
        f = tmp_path / "sample.py"
        f.write_text("def my_func():\n    pass\n", encoding="utf-8")
        result = extract_definitions(f)
        assert "my_func" in result

    def test_extracts_top_level_async_function(self, tmp_path: Path) -> None:
        """Module-level async function names are extracted."""
        f = tmp_path / "sample.py"
        f.write_text("async def fetch_data():\n    pass\n", encoding="utf-8")
        result = extract_definitions(f)
        assert "fetch_data" in result

    def test_extracts_top_level_class(self, tmp_path: Path) -> None:
        """Module-level class names are extracted."""
        f = tmp_path / "sample.py"
        f.write_text("class MyClass:\n    pass\n", encoding="utf-8")
        result = extract_definitions(f)
        assert "MyClass" in result

    def test_skips_private_functions(self, tmp_path: Path) -> None:
        """Private functions (starting with _) are skipped."""
        f = tmp_path / "sample.py"
        f.write_text(
            "def public_func():\n    pass\n\ndef _private_func():\n    pass\n",
            encoding="utf-8",
        )
        result = extract_definitions(f)
        assert "public_func" in result
        assert "_private_func" not in result

    def test_skips_nested_functions(self, tmp_path: Path) -> None:
        """Nested functions inside other functions are not extracted."""
        f = tmp_path / "sample.py"
        f.write_text(
            "def outer():\n    def inner():\n        pass\n",
            encoding="utf-8",
        )
        result = extract_definitions(f)
        assert "outer" in result
        assert "inner" not in result

    def test_returns_empty_for_empty_file(self, tmp_path: Path) -> None:
        """Empty file returns empty list."""
        f = tmp_path / "empty.py"
        f.write_text("", encoding="utf-8")
        result = extract_definitions(f)
        assert result == []

    def test_returns_empty_for_syntax_error(self, tmp_path: Path) -> None:
        """File with syntax error returns empty list (no exception raised)."""
        f = tmp_path / "bad.py"
        f.write_text("def broken(\n", encoding="utf-8")
        result = extract_definitions(f)
        assert result == []


class TestMapSourceToTest:
    """Tests for map_source_to_test()."""

    def test_maps_src_nested_to_test(self) -> None:
        """src/common/config.py maps to tests/test_config.py."""
        source = ROOT / "src" / "common" / "config.py"
        result = map_source_to_test(source)
        assert result is not None
        assert result == ROOT / "tests" / "test_config.py"

    def test_maps_scripts_to_test(self) -> None:
        """scripts/validate.py maps to the tests/validate/ concern-split package (rec-2709
        Wave 1: "test_validate.py" retired from _RETIRING_GRANDFATHER_HOMES, and
        scripts/validate.py is a declared _CONCERN_SPLIT_TEST_PACKAGES entry)."""
        source = ROOT / "scripts" / "validate.py"
        result = map_source_to_test(source)
        assert result is not None
        assert result == ROOT / "tests" / "validate"

    def test_returns_none_for_unmapped_path(self, tmp_path: Path) -> None:
        """Paths not under src/ or scripts/ return None."""
        source = tmp_path / "docs" / "README.py"
        result = map_source_to_test(source)
        assert result is None

    def test_returns_none_for_tests_dir(self) -> None:
        """Paths under tests/ return None (not mapped to themselves)."""
        source = ROOT / "tests" / "test_config.py"
        result = map_source_to_test(source)
        assert result is None

    def test_maps_src_flat_to_test(self) -> None:
        """src/data/pipeline.py maps to tests/test_pipeline.py."""
        source = ROOT / "src" / "data" / "pipeline.py"
        result = map_source_to_test(source)
        assert result is not None
        assert result == ROOT / "tests" / "test_pipeline.py"

    def test_maps_scripts_checks_nested_module_to_mirror(self) -> None:
        """scripts/checks/<domain>/<module>.py maps to its per-check mirror test
        (tests/checks/<domain>/test_<module>.py) post rec-2709 Wave 1 retirement.

        Closes the coverage-gate hole: the pre-extension rule (len(parts) == 2) silently
        skipped every nested scripts/checks/** module.
        """
        source = ROOT / "scripts" / "checks" / "sloc" / "sloc_limits.py"
        result = map_source_to_test(source)
        assert result is not None
        assert result == ROOT / "tests" / "checks" / "sloc" / "test_sloc_limits.py"

    def test_maps_scripts_checks_domain_helper_to_mirror(self) -> None:
        """A domain-package helper module (e.g. contracts/_shared.py) mirrors to
        tests/checks/<domain>/test__shared.py post rec-2709 Wave 1 (no test file actually
        exists at that path -- contracts/_shared.py has no public defs -- this assertion is
        about map_source_to_test's computed path, not file presence; see
        PLAN-sloc-test-validate.yaml's LATENT OBLIGATIONS context note for the domain
        _shared.py helpers)."""
        source = ROOT / "scripts" / "checks" / "contracts" / "_shared.py"
        result = map_source_to_test(source)
        assert result is not None
        assert result == ROOT / "tests" / "checks" / "contracts" / "test__shared.py"

    def test_maps_scripts_checks_registry_to_test_checks_registry(self) -> None:
        """scripts/checks/registry.py maps to tests/test_checks_registry.py, not test_validate.py."""
        source = ROOT / "scripts" / "checks" / "registry.py"
        result = map_source_to_test(source)
        assert result is not None
        assert result == ROOT / "tests" / "test_checks_registry.py"

    def test_maps_scripts_checks_common_to_test_checks_registry(self) -> None:
        """scripts/checks/_common.py maps to tests/test_checks_registry.py, not test_validate.py."""
        source = ROOT / "scripts" / "checks" / "_common.py"
        result = map_source_to_test(source)
        assert result is not None
        assert result == ROOT / "tests" / "test_checks_registry.py"

    @pytest.mark.parametrize(
        "stem",
        ["ducklake_writes", "ducklake_tables", "ducklake_reads", "ducklake_metrics"],
    )
    def test_maps_ducklake_runtime_split_modules_to_test_ducklake_runtime(self, stem: str) -> None:
        """The four ducklake_runtime split-out src/common modules map to tests/test_ducklake_runtime.py
        (PLAN-sloc-ducklake-layer), mirroring the Decision 104 scripts/checks/** precedent."""
        source = ROOT / "src" / "common" / f"{stem}.py"
        result = map_source_to_test(source)
        assert result is not None
        assert result == ROOT / "tests" / "test_ducklake_runtime.py"

    def test_maps_ducklake_writer_smoke_actions_to_test_ducklake_writer_handler(self) -> None:
        """src/lambdas/ducklake_writer/smoke_actions.py maps to tests/test_ducklake_writer_handler.py
        (split-out from handler.py, PLAN-sloc-ducklake-layer)."""
        source = ROOT / "src" / "lambdas" / "ducklake_writer" / "smoke_actions.py"
        result = map_source_to_test(source)
        assert result is not None
        assert result == ROOT / "tests" / "test_ducklake_writer_handler.py"

    def test_ducklake_writer_handler_py_maps_to_parent_qualified_test(self) -> None:
        """src/lambdas/ducklake_writer/handler.py maps to tests/test_ducklake_writer_handler.py under
        the RS-08 parent-qualified rule -- keyed off the parent lambda-slug directory rather than the
        handler.py stem, so it no longer collides with the other lambdas' handler.py files on the
        retired tests/test_handler.py shim."""
        source = ROOT / "src" / "lambdas" / "ducklake_writer" / "handler.py"
        result = map_source_to_test(source)
        assert result is not None
        assert result == ROOT / "tests" / "test_ducklake_writer_handler.py"

    def test_other_lambda_dirs_get_their_own_parent_qualified_test(self) -> None:
        """A non-ducklake_writer lambda dir resolves to its OWN distinct test home -- the RS-08
        parent-qualified rule applies uniformly to every src/lambdas/<slug>/ directory, not just
        ducklake_writer (the pre-generalization special case)."""
        source = ROOT / "src" / "lambdas" / "ducklake_reader" / "handler.py"
        result = map_source_to_test(source)
        assert result is not None
        assert result == ROOT / "tests" / "test_ducklake_reader_handler.py"

    def test_all_lambda_handlers_map_to_distinct_existing_parent_qualified_tests(self) -> None:
        """RS-08: every src/lambdas/*/handler.py resolves to a distinct, EXISTING
        tests/test_{slug}_handler.py home; smoke_actions.py shares ducklake_writer's home; none
        collides on the retired tests/test_handler.py shim (deleted by this plan)."""
        # Derive the slug set from disk (growth-safe: a future lambda is covered automatically, and
        # one added without a parent-qualified test home fails result.exists() below). Do NOT hardcode
        # a list of a collection that grows by addition -- tests/CLAUDE.md test-count-coupling rule.
        handler_paths = sorted((ROOT / "src" / "lambdas").glob("*/handler.py"))
        assert handler_paths, "no src/lambdas/*/handler.py found -- glob is wrong"
        handler_results = {p.parent.name: map_source_to_test(p) for p in handler_paths}

        for slug, result in handler_results.items():
            assert result == ROOT / "tests" / f"test_{slug}_handler.py", (slug, result)
            assert result.exists(), f"missing test home for {slug}: {result}"

        # Every handler's home is distinct from every other handler's home (no collision).
        assert len({str(r) for r in handler_results.values()}) == len(handler_results)

        # None resolves to the retired shim.
        assert all(r != ROOT / "tests" / "test_handler.py" for r in handler_results.values())

        # smoke_actions.py (split-out from ducklake_writer/handler.py) shares that lambda's home.
        smoke_actions_result = map_source_to_test(ROOT / "src" / "lambdas" / "ducklake_writer" / "smoke_actions.py")
        assert smoke_actions_result == handler_results["ducklake_writer"]


class TestCheckTestFileExists:
    """Tests for check_test_file_exists()."""

    def test_returns_true_when_test_file_exists(self, tmp_path: Path) -> None:
        """Returns (True, ...) when the expected test file is present."""
        with (
            patch("test_coverage_checker.map_source_to_test") as mock_map,
            patch("test_coverage_checker.ROOT", tmp_path),
        ):
            test_file = tmp_path / "tests" / "test_config.py"
            test_file.parent.mkdir(parents=True)
            test_file.write_text("# tests", encoding="utf-8")
            mock_map.return_value = test_file

            source = tmp_path / "src" / "config.py"
            ok, msg = check_test_file_exists(source)

        assert ok is True
        assert "found" in msg

    def test_returns_false_when_test_file_missing(self, tmp_path: Path) -> None:
        """Returns (False, ...) when the expected test file is absent."""
        with patch("test_coverage_checker.map_source_to_test") as mock_map:
            test_file = tmp_path / "tests" / "test_missing.py"
            mock_map.return_value = test_file

            source = tmp_path / "src" / "missing.py"
            ok, msg = check_test_file_exists(source)

        assert ok is False
        assert "missing" in msg

    def test_returns_true_for_unmapped_path(self, tmp_path: Path) -> None:
        """Returns (True, skipped) for files that don't map to tests."""
        with patch("test_coverage_checker.map_source_to_test", return_value=None):
            source = tmp_path / "docs" / "something.py"
            ok, msg = check_test_file_exists(source)

        assert ok is True
        assert "skipped" in msg


class TestGetChangedSourceFiles:
    """Tests for get_changed_source_files()."""

    def test_filters_to_src_and_scripts(self) -> None:
        """Only files under src/ or scripts/ are returned."""
        mock_merge_base = MagicMock()
        mock_merge_base.returncode = 0
        mock_merge_base.stdout = "abc123\n"

        mock_diff = MagicMock()
        mock_diff.returncode = 0
        mock_diff.stdout = "src/data/pipeline.py\nscripts/validate.py\ndocs/README.md\nterraform/main.tf\n"

        with patch("test_coverage_checker.subprocess.run", side_effect=[mock_merge_base, mock_diff]):
            result = get_changed_source_files()

        rel_parts = [str(p.relative_to(ROOT)).replace("\\", "/") for p in result]
        assert any("src/data/pipeline.py" in r for r in rel_parts)
        assert any("scripts/validate.py" in r for r in rel_parts)
        assert not any("docs" in r for r in rel_parts)
        assert not any(".tf" in r for r in rel_parts)

    def test_excludes_init_and_conftest(self) -> None:
        """__init__.py and conftest.py are excluded from results."""
        mock_merge_base = MagicMock()
        mock_merge_base.returncode = 0
        mock_merge_base.stdout = "abc123\n"

        mock_diff = MagicMock()
        mock_diff.returncode = 0
        mock_diff.stdout = "src/data/__init__.py\nsrc/data/pipeline.py\n"

        with patch("test_coverage_checker.subprocess.run", side_effect=[mock_merge_base, mock_diff]):
            result = get_changed_source_files()

        names = [p.name for p in result]
        assert "__init__.py" not in names

    def test_excludes_test_files(self) -> None:
        """Files starting with test_ are excluded."""
        mock_merge_base = MagicMock()
        mock_merge_base.returncode = 0
        mock_merge_base.stdout = "abc123\n"

        mock_diff = MagicMock()
        mock_diff.returncode = 0
        mock_diff.stdout = "tests/test_pipeline.py\nsrc/data/pipeline.py\n"

        with patch("test_coverage_checker.subprocess.run", side_effect=[mock_merge_base, mock_diff]):
            result = get_changed_source_files()

        names = [p.name for p in result]
        assert "test_pipeline.py" not in names

    def test_uses_explicit_files_list(self) -> None:
        """When --files is provided, git diff is not called."""
        explicit = [str(ROOT / "scripts" / "validate.py")]
        with patch("test_coverage_checker.subprocess.run") as mock_run:
            result = get_changed_source_files(files=explicit)
            mock_run.assert_not_called()

        assert any("validate.py" in str(p) for p in result)

    def test_fallback_when_merge_base_fails(self) -> None:
        """Falls back to HEAD diff when merge-base against origin/main fails."""
        mock_fail = MagicMock()
        mock_fail.returncode = 128

        mock_head_diff = MagicMock()
        mock_head_diff.returncode = 0
        mock_head_diff.stdout = "src/data/pipeline.py\n"

        with patch("test_coverage_checker.subprocess.run", side_effect=[mock_fail, mock_head_diff]):
            result = get_changed_source_files()

        assert any("pipeline.py" in str(p) for p in result)


class TestGrandfatherRetiringTable:
    """Behaviour-preservation invariant (Decision 131): map_source_to_test resolves each
    roster home via colocation while it is grandfathered, and via the mirror rule once a wave
    retires it -- rec-2709 Wave 1 (PLAN-sloc-test-validate) retired the first of the 24,
    "test_validate.py"; Wave 2 (PLAN-sloc-execute-recommendation) retired the second,
    "test_execute_recommendation.py"."""

    def test_representative_paths_resolve_under_current_retirement_state(self) -> None:
        """A representative real path set resolves correctly under the CURRENT retirement
        state: "test_validate.py" and "test_execute_recommendation.py" are retired (their
        sources now resolve via the mirror rule / their concern-split packages), the other 22
        roster homes are still grandfathered, and scripts/executor/** and scripts/ops_portal/**
        keep returning None (Decision 124 -- unperturbed by the Wave 1/2 map edits)."""
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
            ROOT / "src" / "common" / "config.py": ROOT / "tests" / "test_config.py",
            ROOT / "scripts" / "executor" / "step_runner.py": None,
            ROOT / "scripts" / "ops_portal" / "cli.py": None,
            ROOT / "src" / "common" / "iceberg_reader.py": ROOT / "tests" / "test_iceberg_reader.py",
        }
        for source, expected in cases.items():
            assert map_source_to_test(source) == expected, source

    def test_retiring_is_all_target_homes_minus_test_validate_and_test_execute_recommendation(self) -> None:
        """Exactly two basenames have retired so far: "test_validate.py" (rec-2709 Wave 1) and
        "test_execute_recommendation.py" (rec-2709 Wave 2). The mirror branch is live for both
        and dormant for the other 22 roster targets."""
        retired = {"test_validate.py", "test_execute_recommendation.py"}
        assert _RETIRING_GRANDFATHER_HOMES == _ALL_MIRROR_TARGET_HOMES - retired
        assert "test_validate.py" not in _RETIRING_GRANDFATHER_HOMES
        assert "test_execute_recommendation.py" not in _RETIRING_GRANDFATHER_HOMES
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


class TestMirrorRule:
    """Once a wave retires a home (removes it from _RETIRING_GRANDFATHER_HOMES), sources that
    grandfather to it resolve via the mirror rule instead."""

    def test_package_source_resolves_to_mirror_path_once_retired(self, monkeypatch: pytest.MonkeyPatch) -> None:
        retired = _ALL_MIRROR_TARGET_HOMES - {"test_validate.py"}
        monkeypatch.setattr(_checker, "_RETIRING_GRANDFATHER_HOMES", retired)

        source = ROOT / "scripts" / "checks" / "hygiene" / "validate_prose_allowlist.py"
        result = map_source_to_test(source)

        assert result == ROOT / "tests" / "checks" / "hygiene" / "test_validate_prose_allowlist.py"

    def test_concern_split_monolith_resolves_to_test_package_directory_once_retired(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        retired = _ALL_MIRROR_TARGET_HOMES - {"test_ops_writer.py"}
        monkeypatch.setattr(_checker, "_RETIRING_GRANDFATHER_HOMES", retired)

        source = ROOT / "scripts" / "ops_writer.py"
        result = map_source_to_test(source)

        assert result == ROOT / "tests" / "ops_writer"

    def test_nested_concern_split_monolith_keeps_subdir_once_retired(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """src/common/iceberg_reader.py (nested under common/) mirrors to tests/common/iceberg_reader/,
        not tests/iceberg_reader/ -- the mirror-subpath is preserved for non-root sources."""
        retired = _ALL_MIRROR_TARGET_HOMES - {"test_iceberg_reader.py"}
        monkeypatch.setattr(_checker, "_RETIRING_GRANDFATHER_HOMES", retired)

        source = ROOT / "src" / "common" / "iceberg_reader.py"
        result = map_source_to_test(source)

        assert result == ROOT / "tests" / "common" / "iceberg_reader"


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
