"""Tests for test_coverage_checker.map_source_to_test() and the post-retirement mirror rule.

Split from the former tests/test_coverage_checker.py monolith (rec-2709 Wave 6b -- SLOC governance
per Decision 128, not a mirror-roster retirement: scripts/test_coverage_checker.py is excluded from
its own coverage scan by name and isn't one of the 24 _ALL_MIRROR_TARGET_HOMES roster entries). See
tests/fixtures/coverage_checker_module.py for the shared module-under-test singleton.
"""

from pathlib import Path

import pytest

from tests.fixtures.coverage_checker_module import _ALL_MIRROR_TARGET_HOMES, ROOT
from tests.fixtures.coverage_checker_module import checker as _checker

map_source_to_test = _checker.map_source_to_test


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

    def test_maps_scripts_session_preflight_to_concern_split_package(self) -> None:
        """scripts/session/preflight.py maps to the tests/session/preflight/ concern-split
        package (rec-2709 Wave 4: "test_session_preflight.py" retired from
        _RETIRING_GRANDFATHER_HOMES, and scripts/session/preflight.py is a declared
        _CONCERN_SPLIT_TEST_PACKAGES entry)."""
        source = ROOT / "scripts" / "session" / "preflight.py"
        result = map_source_to_test(source)
        assert result is not None
        assert result == ROOT / "tests" / "session" / "preflight"

    def test_maps_scripts_sync_ops_to_concern_split_package(self) -> None:
        """scripts/sync/ops.py maps to the tests/sync/ops/ concern-split package (rec-2709
        Wave 10: "test_sync_ops.py" retired from _RETIRING_GRANDFATHER_HOMES, and
        scripts/sync/ops.py is a declared _CONCERN_SPLIT_TEST_PACKAGES entry)."""
        source = ROOT / "scripts" / "sync" / "ops.py"
        result = map_source_to_test(source)
        assert result is not None
        assert result == ROOT / "tests" / "sync" / "ops"

    def test_maps_scripts_session_postflight_to_concern_split_package(self) -> None:
        """scripts/session/postflight.py maps to the tests/session/postflight/ concern-split
        package (rec-2709 Wave 10: "test_session_postflight.py" retired from
        _RETIRING_GRANDFATHER_HOMES, and scripts/session/postflight.py is a declared
        _CONCERN_SPLIT_TEST_PACKAGES entry)."""
        source = ROOT / "scripts" / "session" / "postflight.py"
        result = map_source_to_test(source)
        assert result is not None
        assert result == ROOT / "tests" / "session" / "postflight"

    def test_maps_scripts_ci_rca_evidence_to_concern_split_package(self) -> None:
        """scripts/ci_rca/evidence.py maps to the tests/ci_rca/evidence/ concern-split package
        (rec-2709 Wave 10: "test_ci_rca_evidence.py" retired from _RETIRING_GRANDFATHER_HOMES,
        and scripts/ci_rca/evidence.py is a declared _CONCERN_SPLIT_TEST_PACKAGES entry)."""
        source = ROOT / "scripts" / "ci_rca" / "evidence.py"
        result = map_source_to_test(source)
        assert result is not None
        assert result == ROOT / "tests" / "ci_rca" / "evidence"

    def test_maps_still_grandfathered_sync_sibling_to_flat_home(self) -> None:
        """scripts/sync/recommendations.py (never on the 24-roster) still resolves to its flat
        grandfathered home via _NESTED_SUBPACKAGE_TEST_PREFIX -- proves Wave 10's retirement of
        "test_sync_ops.py" did not perturb the family-sibling prefix rule."""
        source = ROOT / "scripts" / "sync" / "recommendations.py"
        result = map_source_to_test(source)
        assert result is not None
        assert result == ROOT / "tests" / "test_sync_recommendations.py"

    def test_maps_still_grandfathered_session_sibling_to_flat_home(self) -> None:
        """scripts/session/metrics.py (never on the 24-roster) still resolves to its flat
        grandfathered home via _NESTED_SUBPACKAGE_TEST_PREFIX -- proves Wave 10's retirement of
        "test_session_postflight.py" did not perturb the family-sibling prefix rule."""
        source = ROOT / "scripts" / "session" / "metrics.py"
        result = map_source_to_test(source)
        assert result is not None
        assert result == ROOT / "tests" / "test_session_metrics.py"

    def test_maps_still_grandfathered_ci_rca_sibling_to_flat_home(self) -> None:
        """scripts/ci_rca/filing.py (never on the 24-roster) still resolves to its flat
        grandfathered home via _NESTED_SUBPACKAGE_TEST_PREFIX -- proves Wave 10's retirement of
        "test_ci_rca_evidence.py" did not perturb the family-sibling prefix rule."""
        source = ROOT / "scripts" / "ci_rca" / "filing.py"
        result = map_source_to_test(source)
        assert result is not None
        assert result == ROOT / "tests" / "test_ci_rca_filing.py"

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
    def test_maps_ducklake_runtime_split_modules_resolve_to_their_common_mirror(self, stem: str) -> None:
        """The four ducklake_runtime split-out src/common modules map to their own
        tests/common/test_ducklake_<stem>.py mirror (rec-2709 Wave 7: "test_ducklake_runtime.py"
        retired from _RETIRING_GRANDFATHER_HOMES). Proves the crux: _DUCKLAKE_RUNTIME_SPLIT_MODULES
        is KEPT (not removed) -- it still routes these four to the ducklake_runtime grandfather
        home, and once that home retires, the mirror branch (drop-root, non-concern-split) resolves
        each to its real per-module test home instead of the flat tests/test_ducklake_<stem>.py a
        removed special-case would wrongly produce."""
        source = ROOT / "src" / "common" / f"{stem}.py"
        result = map_source_to_test(source)
        assert result is not None
        assert result == ROOT / "tests" / "common" / f"test_{stem}.py"

    def test_maps_ducklake_neon_smoke_test_to_concern_split_package(self) -> None:
        """scripts/ducklake_neon_smoke_test.py maps to the tests/ducklake_neon_smoke_test/
        concern-split package (rec-2709 Wave 7: "test_ducklake_neon_smoke_test.py" retired from
        _RETIRING_GRANDFATHER_HOMES, and scripts/ducklake_neon_smoke_test.py is a declared
        _CONCERN_SPLIT_TEST_PACKAGES entry, already seeded before this wave)."""
        source = ROOT / "scripts" / "ducklake_neon_smoke_test.py"
        result = map_source_to_test(source)
        assert result is not None
        assert result == ROOT / "tests" / "ducklake_neon_smoke_test"

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

    @pytest.mark.parametrize(
        ("stem", "expected_test_name"),
        [
            ("record", "test_record.py"),
            ("approvals", "test_approvals.py"),
            ("assess", "test_assess.py"),
            ("escalate", "test_escalate.py"),
            ("code_drift", "test_code_drift.py"),
            ("__main__", "test___main__.py"),
        ],
    )
    def test_maps_convergence_health_submodules_to_their_own_mirror(self, stem: str, expected_test_name: str) -> None:
        # rec-2709 Wave 6 PACKAGE-MIRROR: each submodule maps 1:1 to its own mirror file.
        source = ROOT / "scripts" / "convergence_health" / f"{stem}.py"
        result = map_source_to_test(source)
        assert result is not None
        assert result == ROOT / "tests" / "convergence_health" / expected_test_name


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
