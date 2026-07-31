"""Tests for the remaining error/fallback statements in test_coverage_checker.py, scattered
across get_changed_source_files, _mirror_source_to_test, map_source_to_test,
check_test_file_exists, and check_per_file_coverage. Also covers the new direct
_CONCERN_SPLIT_TEST_PACKAGES branch added to map_source_to_test by
PLAN-coverage-checker-self-enforcement.

Two of these branches (map_source_to_test's rel_name fallback and check_per_file_coverage's
relative_to fallback) are defensively dead on any real, non-mocked input -- both are reachable
only if a resolve()/relative_to(ROOT) call that already succeeded upstream in the SAME logical
operation later fails, which cannot happen for a real Path on a stable filesystem. Per the plan's
guidance, these are exercised via helper-mocking (a call-counted fault injection on
Path.relative_to, and a monkeypatched _measure_and_check) rather than a crafted input.
"""

from pathlib import Path

import pytest

from tests.fixtures.coverage_checker_module import ROOT, checker

map_source_to_test = checker.map_source_to_test
_mirror_source_to_test = checker._mirror_source_to_test
_grandfathered_source_to_test = checker._grandfathered_source_to_test
check_test_file_exists = checker.check_test_file_exists
check_per_file_coverage = checker.check_per_file_coverage
get_changed_source_files = checker.get_changed_source_files


class TestGrandfatheredSourceToTestEmptyParts:
    def test_root_itself_returns_none(self) -> None:
        """source_path == ROOT resolves to an empty rel.parts tuple -- the `not parts` guard."""
        assert _grandfathered_source_to_test(ROOT) is None


class TestMirrorSourceToTestEdgeCases:
    def test_path_outside_root_returns_none(self) -> None:
        """A path with no common ancestor with ROOT raises ValueError on relative_to -> None."""
        outside = Path("/definitely-not-under-repo-root/module.py")
        assert _mirror_source_to_test(outside) is None

    def test_top_level_single_part_returns_none(self) -> None:
        """A path directly under ROOT (one part, e.g. ROOT/setup.py) has len(parts) < 2 -> None."""
        top_level = ROOT / "some_hypothetical_top_level_file.py"
        assert _mirror_source_to_test(top_level) is None


class TestMapSourceToTestDirectConcernSplit:
    """The new branch: _CONCERN_SPLIT_TEST_PACKAGES membership alone resolves a source to its
    test package directory, independent of whether its grandfathered home has retired."""

    def test_checker_itself_resolves_via_direct_membership(self) -> None:
        source = ROOT / "scripts" / "test_coverage_checker.py"
        result = map_source_to_test(source)
        assert result == ROOT / "tests" / "test_coverage_checker"

    def test_unmapped_path_not_in_concern_split_set_stays_none(self) -> None:
        """A path with no grandfathered home (home is None) and no concern-split membership
        still returns None -- the new branch must not widen the mapped surface."""
        unmapped = ROOT / "scripts" / "executor" / "some_helper.py"
        assert map_source_to_test(unmapped) is None

    def test_rel_name_fallback_is_behavior_preserving(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Defensive branch (map_source_to_test's own relative_to(ROOT) call, made independently
        of _grandfathered_source_to_test's earlier one): fault-inject so exactly the SECOND
        Path.relative_to call in this operation raises, forcing the `except ValueError: rel_name
        = source_path.name` fallback. scripts/ops_writer.py's mapping is unaffected either way
        (rel_name only gates the two special-cased homes, neither of which is
        test_ops_writer.py), so this proves the fallback doesn't change real behavior."""
        source = ROOT / "scripts" / "ops_writer.py"
        original_relative_to = Path.relative_to
        call_count = {"n": 0}

        def fake_relative_to(self: Path, *args: object, **kwargs: object) -> Path:
            call_count["n"] += 1
            if call_count["n"] == 2:
                raise ValueError("injected failure for defensive-branch coverage")
            return original_relative_to(self, *args, **kwargs)

        monkeypatch.setattr(Path, "relative_to", fake_relative_to)
        result = map_source_to_test(source)

        assert call_count["n"] >= 2
        assert result == ROOT / "tests" / "ops_writer"


class TestCheckTestFileExistsMissingPackageRelativeToFailure:
    def test_missing_package_display_falls_back_to_full_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Defensive branch: expected.relative_to(ROOT) fails for the concern-split "missing test
        package" message. Achieved by mocking map_source_to_test to return a directory-shaped
        path with no common ancestor with ROOT (the measure/map helper, not a crafted real path)."""
        fake_expected = Path("/definitely-not-under-repo-root/some_pkg")
        monkeypatch.setattr(checker, "map_source_to_test", lambda _p: fake_expected)

        ok, msg = check_test_file_exists(ROOT / "scripts" / "whatever.py")

        assert ok is False
        assert msg == f"missing test package: {fake_expected}"


class TestCheckPerFileCoverageRelativeToFailure:
    def test_measured_path_outside_root_is_skipped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Defensive branch: a measured key that resolves outside ROOT is skipped via `continue`
        rather than raising. Achieved by mocking _measure_and_check (the measure helper) to
        report a non-None percentage for an out-of-root path -- this cannot happen with a real
        source_files list (every caller filters to files under ROOT first)."""
        outside = Path("/definitely-not-under-repo-root/module.py")
        monkeypatch.setattr(checker, "_measure_and_check", lambda _files: ({str(outside.resolve()): 55.0}, []))

        errors = check_per_file_coverage([outside])

        assert errors == []


class TestGetChangedSourceFilesSelfInclusion:
    """rec-2916: the checker no longer excludes itself from get_changed_source_files, while
    still excluding real tests/ files -- the exclusion is now keyed on the resolved path being
    under tests/ (via the parts[0] in ("src", "scripts") filter), not a "test_" basename prefix."""

    def test_checker_included_ops_writer_included_tests_dir_excluded(self) -> None:
        got = {
            p.name
            for p in get_changed_source_files(
                files=[
                    "scripts/test_coverage_checker.py",
                    "scripts/ops_writer.py",
                    "tests/test_coverage_checker/test_main_cli.py",
                ]
            )
        }
        assert "test_coverage_checker.py" in got, f"still self-excluded: {got}"
        assert "ops_writer.py" in got, got
        assert "test_main_cli.py" not in got, f"tests/ leaked in: {got}"


class TestGetChangedSourceFilesEdgePaths:
    def test_relative_files_argument_resolved_against_root(self) -> None:
        """A relative --files entry is joined onto ROOT (p = ROOT / p) before resolution."""
        result = get_changed_source_files(files=["scripts/ops_writer.py"])
        assert result == [(ROOT / "scripts" / "ops_writer.py").resolve()]

    def test_non_py_file_in_files_argument_is_skipped(self) -> None:
        """A non-.py path passed via --files is filtered out (suffix check)."""
        result = get_changed_source_files(files=["docs/CLAUDE.md"])
        assert result == []

    def test_path_outside_root_in_files_argument_is_skipped(self) -> None:
        """An absolute path with no common ancestor with ROOT fails relative_to(ROOT) and is
        skipped rather than raising."""
        result = get_changed_source_files(files=["/definitely-not-under-repo-root/module.py"])
        assert result == []
