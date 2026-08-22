"""Mirror test for scripts/checks/misc/validate_diff_coverage.py (PLAN-premerge-diff-coverage-gate).

THE DISCRIMINATOR (acceptance criterion 1): an added executable line with no covering test is
reported UNCOVERED, and an added covered line is not. Also covers the three derived DEFERRED
classes (a/b/d), the class-(c) declared residual (asserted to land in UNCOVERED, never DEFERRED),
the absent-selection-manifest skip, the no-usable-artifact skip, and the --replay-history /
--report-only CLI surface.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from scripts.checks import registry
from scripts.checks.misc import validate_diff_coverage as vdc


class TestClassifyFileDiscriminator:
    """THE DISCRIMINATOR: a covered added line is not reported UNCOVERED; an uncovered one is --
    a test asserting only that the check runs would pass on a broken intersection."""

    def test_added_uncovered_line_reported_uncovered(self) -> None:
        status, reason = vdc.classify_file(
            "src/foo.py",
            {10},
            coverage_files={"src/foo.py": {"executed_lines": [1, 2], "missing_lines": [10]}},
            covering_tests=frozenset({"tests/test_foo.py"}),
            selected={"tests/test_foo.py"},
            heavy_dep_deferred=set(),
        )
        assert status == {10: vdc.UNCOVERED}
        assert reason is None

    def test_added_covered_line_not_reported_uncovered(self) -> None:
        status, reason = vdc.classify_file(
            "src/foo.py",
            {5},
            coverage_files={"src/foo.py": {"executed_lines": [5], "missing_lines": [10]}},
            covering_tests=frozenset({"tests/test_foo.py"}),
            selected={"tests/test_foo.py"},
            heavy_dep_deferred=set(),
        )
        assert status == {5: vdc.COVERED}
        assert reason is None

    def test_non_executable_line_excluded_from_classification(self) -> None:
        """A line absent from both executed_lines and missing_lines (blank/comment/docstring per
        coverage.py) is silently excluded -- neither COVERED, UNCOVERED, nor DEFERRED."""
        status, _reason = vdc.classify_file(
            "src/foo.py",
            {3},
            coverage_files={"src/foo.py": {"executed_lines": [1], "missing_lines": [2]}},
            covering_tests=frozenset({"tests/test_foo.py"}),
            selected={"tests/test_foo.py"},
            heavy_dep_deferred=set(),
        )
        assert status == {}


class TestDerivedDeferredClasses:
    """The three MACHINE-DERIVED DEFERRED classes: (a) affected-set capped/deferred, (b)
    heavy-dependency exclusion, (d) never a selection candidate at all."""

    def test_class_a_affected_set_capped_or_deferred(self) -> None:
        status, reason = vdc.classify_file(
            "src/foo.py",
            {10, 11},
            coverage_files={},
            covering_tests=frozenset({"tests/test_foo.py"}),
            selected=set(),  # covering test absent from selected -- capped/deferred
            heavy_dep_deferred=set(),
        )
        assert status == {10: vdc.DEFERRED, 11: vdc.DEFERRED}
        assert reason == vdc.REASON_AFFECTED_SET

    def test_class_b_heavy_dependency_exclusion(self) -> None:
        status, reason = vdc.classify_file(
            "src/foo.py",
            {10},
            coverage_files={},
            covering_tests=frozenset({"tests/test_foo.py"}),
            selected={"tests/test_foo.py"},
            heavy_dep_deferred={"tests/test_foo.py"},
        )
        assert status == {10: vdc.DEFERRED}
        assert reason == vdc.REASON_HEAVY_DEP

    def test_class_d_never_a_selection_candidate_unmapped_source(self) -> None:
        """Decision 124 carve-out shape: map_source_to_test returns None (e.g.
        scripts/executor/**, scripts/ops_portal/**) -- DEFERRED, not UNCOVERED, and this plan
        does not close that carve-out."""
        status, reason = vdc.classify_file(
            "scripts/executor/step_runner.py",
            {5},
            coverage_files={},
            covering_tests=frozenset(),
            selected=set(),
            heavy_dep_deferred=set(),
        )
        assert status == {5: vdc.DEFERRED}
        assert reason == vdc.REASON_UNMAPPED


class TestExpandCoveringTests:
    """A concern-split source resolves to a test PACKAGE DIRECTORY, not a single file (real
    example: scripts/checks/_pytest_diff.py -> tests/validate -- see that module's docstring on
    _ORCHESTRATION_SCAFFOLDING_FILES). A bare directory string would never match any individual
    entry in logs/debug/selection-manifest.json's `selected` list, silently mis-deferring every
    line under such a source -- this is what expand_covering_tests exists to prevent."""

    def test_none_expands_to_empty(self, tmp_path: Path) -> None:
        assert vdc.expand_covering_tests(None, tmp_path) == frozenset()

    def test_single_file_expands_to_itself(self, tmp_path: Path) -> None:
        test_file = tmp_path / "tests" / "test_foo.py"
        test_file.parent.mkdir(parents=True)
        test_file.write_text("", encoding="utf-8")
        assert vdc.expand_covering_tests(test_file, tmp_path) == frozenset({"tests/test_foo.py"})

    def test_directory_expands_to_every_test_module_inside(self, tmp_path: Path) -> None:
        pkg = tmp_path / "tests" / "validate"
        pkg.mkdir(parents=True)
        (pkg / "test_a.py").write_text("", encoding="utf-8")
        (pkg / "test_b.py").write_text("", encoding="utf-8")
        (pkg / "not_a_test.py").write_text("", encoding="utf-8")
        assert vdc.expand_covering_tests(pkg, tmp_path) == frozenset({"tests/validate/test_a.py", "tests/validate/test_b.py"})

    def test_directory_with_no_test_modules_expands_to_empty(self, tmp_path: Path) -> None:
        pkg = tmp_path / "tests" / "empty_pkg"
        pkg.mkdir(parents=True)
        assert vdc.expand_covering_tests(pkg, tmp_path) == frozenset()


class TestDirectoryCoveringTestNotFalselyDeferred:
    """Regression: a concern-split directory result must be resolved via at least ONE of its
    expanded test modules being selected -- a bare directory string must never be compared
    directly against `selected` (it would never match, always mis-deferring class (a))."""

    def test_directory_result_with_one_selected_member_is_not_deferred(self, tmp_path: Path) -> None:
        covering_tests = frozenset({"tests/validate/test_a.py", "tests/validate/test_b.py"})
        status, reason = vdc.classify_file(
            "scripts/checks/_pytest_diff.py",
            {7},
            coverage_files={"scripts/checks/_pytest_diff.py": {"executed_lines": [7], "missing_lines": []}},
            covering_tests=covering_tests,
            selected={"tests/validate/test_a.py"},  # only ONE of the two expanded members ran
            heavy_dep_deferred=set(),
        )
        assert status == {7: vdc.COVERED}
        assert reason is None


class TestClassCResidualLandsInUncovered:
    """Class (c): a line covered only by a test the `-m "not integration"` marker excludes on
    every run_pytest_diff invocation. map_source_to_test returns the mirror FILE and carries no
    marker information, so this is a DECLARED KNOWN RESIDUAL that lands in UNCOVERED, never
    DEFERRED -- suppressing it would hide the false positives this plan exists to measure."""

    def test_integration_only_covered_line_lands_uncovered_not_deferred(self) -> None:
        # The covering test file DID run (selected, not heavy-dep-deferred) -- but the specific
        # integration-marked test that would have covered this line was excluded by
        # `-m "not integration"`, so coverage.json shows it as missing, indistinguishable from a
        # genuinely uncovered line.
        status, reason = vdc.classify_file(
            "src/foo.py",
            {42},
            coverage_files={"src/foo.py": {"executed_lines": [1, 2], "missing_lines": [42]}},
            covering_tests=frozenset({"tests/test_foo.py"}),
            selected={"tests/test_foo.py"},
            heavy_dep_deferred=set(),
        )
        assert status == {42: vdc.UNCOVERED}
        assert reason is None


class TestAbsentSelectionManifestSkip:
    def test_absent_manifest_declares_skipped_not_pass(self, tmp_path: Path) -> None:
        registry.pop_declaration()
        failed: list[str] = []
        with patch("scripts.checks.misc.validate_diff_coverage.added_line_numbers_by_file", return_value={}):
            vdc.validate_diff_coverage(failed, root=tmp_path, base="origin/main", map_source_to_test=lambda p: None)
        declaration = registry.pop_declaration()
        assert declaration is not None
        assert declaration.kind == "skipped"
        assert failed == []


class TestNoUsableArtifactSkip:
    def test_no_artifact_state_declares_skipped(self, tmp_path: Path) -> None:
        (tmp_path / "logs" / "debug").mkdir(parents=True)
        (tmp_path / "logs" / "debug" / "selection-manifest.json").write_text('{"selected": []}', encoding="utf-8")
        (tmp_path / "logs" / "debug" / "diff-coverage-deferrals.json").write_text(
            '{"state": "all_deferred", "deferred": {}}', encoding="utf-8"
        )
        registry.pop_declaration()
        failed: list[str] = []
        vdc.validate_diff_coverage(failed, root=tmp_path, base="origin/main", map_source_to_test=lambda p: None)
        declaration = registry.pop_declaration()
        assert declaration is not None
        assert declaration.kind == "skipped"
        assert failed == []


class TestNeverAppendsToFailed:
    def test_ok_state_with_real_uncovered_line_never_fails(self, tmp_path: Path) -> None:
        (tmp_path / "logs" / "debug").mkdir(parents=True)
        (tmp_path / "logs" / "debug" / "selection-manifest.json").write_text(
            '{"selected": ["tests/test_foo.py"]}', encoding="utf-8"
        )
        (tmp_path / "logs" / "debug" / "diff-coverage-deferrals.json").write_text(
            '{"state": "ok", "deferred": {}}', encoding="utf-8"
        )
        (tmp_path / "logs" / "debug" / "diff-coverage.json").write_text(
            '{"files": {"src/foo.py": {"executed_lines": [], "missing_lines": [10]}}}', encoding="utf-8"
        )
        registry.pop_declaration()
        failed: list[str] = []
        with patch(
            "scripts.checks.misc.validate_diff_coverage.added_line_numbers_by_file",
            return_value={"src/foo.py": {10}},
        ):
            vdc.validate_diff_coverage(
                failed,
                root=tmp_path,
                base="origin/main",
                map_source_to_test=lambda p: tmp_path / "tests" / "test_foo.py",
            )
        declaration = registry.pop_declaration()
        assert declaration is not None
        assert declaration.kind == "examined"
        assert declaration.count == 1
        assert failed == []  # THE central constraint: never appends to failed, regardless of UNCOVERED lines


class TestAddedLineNumbersByFile:
    """Hunk-parsing correctness over a synthetic -U0 unified diff (mocked subprocess -- no real
    git repo needed to prove the parser's line-number arithmetic)."""

    _DIFF = (
        "diff --git a/src/foo.py b/src/foo.py\n"
        "index 1111111..2222222 100644\n"
        "--- a/src/foo.py\n"
        "+++ b/src/foo.py\n"
        "@@ -9,0 +10,2 @@ def existing():\n"
        "+    new_line_one()\n"
        "+    new_line_two()\n"
        "@@ -20 +22 @@ def other():\n"
        "-    old_call()\n"
        "+    new_call()\n"
    )

    def test_added_lines_recorded_at_correct_new_line_numbers(self) -> None:
        def mock_run(cmd, **kwargs):
            class _Result:
                returncode = 0
                stdout = TestAddedLineNumbersByFile._DIFF
                stderr = ""

            return _Result()

        with patch("scripts.checks._common.run", side_effect=mock_run):
            result = vdc.added_line_numbers_by_file(Path("/repo"), "origin/main")
        assert result == {"src/foo.py": {10, 11, 22}}

    def test_non_python_file_excluded(self) -> None:
        diff = "diff --git a/docs/README.md b/docs/README.md\n@@ -1 +1 @@\n-old\n+new\n"

        def mock_run(cmd, **kwargs):
            class _Result:
                returncode = 0
                stdout = diff
                stderr = ""

            return _Result()

        with patch("scripts.checks._common.run", side_effect=mock_run):
            result = vdc.added_line_numbers_by_file(Path("/repo"), "origin/main")
        assert result == {}


class TestUntrackedNewFilesLeg:
    """`git diff <base>` is blind to untracked new files by construction (rec-2638 precedent) --
    a brand-new src/scripts .py file must still contribute EVERY line as added, via the separate
    `git ls-files --others` leg, or a local session's own new files would silently vanish from
    this classifier's domain."""

    def test_untracked_new_file_every_line_is_added(self, tmp_path: Path) -> None:
        new_file = tmp_path / "scripts" / "brand_new.py"
        new_file.parent.mkdir(parents=True)
        new_file.write_text("line1\nline2\nline3\n", encoding="utf-8")

        def mock_run(cmd, **kwargs):
            class _Result:
                returncode = 0
                stdout = ""
                stderr = ""

            r = _Result()
            if "ls-files" in cmd:
                r.stdout = "scripts/brand_new.py\n"
            return r

        with patch("scripts.checks._common.run", side_effect=mock_run):
            result = vdc.added_line_numbers_by_file(tmp_path, "origin/main")
        assert result == {"scripts/brand_new.py": {1, 2, 3}}

    def test_tracked_and_untracked_legs_union_without_clobbering(self, tmp_path: Path) -> None:
        new_file = tmp_path / "scripts" / "brand_new.py"
        new_file.parent.mkdir(parents=True)
        new_file.write_text("a\nb\n", encoding="utf-8")
        tracked_diff = "diff --git a/scripts/existing.py b/scripts/existing.py\n@@ -1,0 +2 @@\n+x\n"

        def mock_run(cmd, **kwargs):
            class _Result:
                returncode = 0
                stdout = ""
                stderr = ""

            r = _Result()
            if "ls-files" in cmd:
                r.stdout = "scripts/brand_new.py\n"
            elif "diff" in cmd:
                r.stdout = tracked_diff
            return r

        with patch("scripts.checks._common.run", side_effect=mock_run):
            result = vdc.added_line_numbers_by_file(tmp_path, "origin/main")
        assert result == {"scripts/existing.py": {2}, "scripts/brand_new.py": {1, 2}}


class TestCliModes:
    def test_report_only_flag_never_appends_to_failed(self, tmp_path: Path) -> None:
        with patch("scripts.checks.misc.validate_diff_coverage._common.ROOT", tmp_path):
            exit_code = vdc.main(["--report-only"])
        assert exit_code == 0

    def test_replay_history_mode_runs_without_error(self) -> None:
        def mock_run(cmd, **kwargs):
            class _Result:
                returncode = 0
                stdout = ""
                stderr = ""

            return _Result()

        with patch("scripts.checks._common.run", side_effect=mock_run):
            exit_code = vdc.main(["--replay-history", "5"])
        assert exit_code == 0

    def test_replay_history_recommends_forward_arm(self, capsys) -> None:
        commits = "\n".join(f"c{i}" * 4 for i in range(3))

        def mock_run(cmd, **kwargs):
            class _Result:
                pass

            r = _Result()
            if "log" in cmd:
                r.returncode = 0
                r.stdout = commits
                r.stderr = ""
            else:
                r.returncode = 0
                r.stdout = ""
                r.stderr = ""
            return r

        with patch("scripts.checks._common.run", side_effect=mock_run):
            vdc._replay_history(3)
        out = capsys.readouterr().out
        assert "RECOMMENDATION" in out
        assert "FORWARD ARM" in out


class TestLoadJsonDecodeError:
    def test_invalid_json_returns_none(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text("{not valid json", encoding="utf-8")
        assert vdc._load_json(bad) is None


class TestNonZeroReturncodeLegs:
    def test_tracked_leg_nonzero_returncode_returns_empty(self, tmp_path: Path) -> None:
        def mock_run(cmd, **kwargs):
            class _Result:
                returncode = 1
                stdout = ""
                stderr = "fatal: bad revision"

            return _Result()

        with patch("scripts.checks._common.run", side_effect=mock_run):
            assert vdc._tracked_added_lines(tmp_path, "origin/main") == {}

    def test_untracked_leg_nonzero_returncode_returns_empty(self, tmp_path: Path) -> None:
        def mock_run(cmd, **kwargs):
            class _Result:
                returncode = 1
                stdout = ""
                stderr = "fatal: not a git repository"

            return _Result()

        with patch("scripts.checks._common.run", side_effect=mock_run):
            assert vdc._untracked_added_lines(tmp_path) == {}


class TestFindCoverageFileEntryFuzzyMatch:
    def test_fuzzy_suffix_match_when_exact_key_absent(self) -> None:
        coverage_files = {"/abs/repo/src/foo.py": {"executed_lines": [1], "missing_lines": []}}
        entry = vdc._find_coverage_file_entry(coverage_files, "src/foo.py")
        assert entry == {"executed_lines": [1], "missing_lines": []}

    def test_no_match_returns_none(self) -> None:
        assert vdc._find_coverage_file_entry({"src/bar.py": {}}, "src/foo.py") is None


class TestExpandCoveringTestsNeitherFileNorDir:
    def test_nonexistent_extensionless_path_expands_to_empty(self, tmp_path: Path) -> None:
        ghost = tmp_path / "not_a_real_thing"
        assert vdc.expand_covering_tests(ghost, tmp_path) == frozenset()


class TestReplayHistoryPerCommitLoop:
    def test_commit_with_unresolvable_diff_is_skipped(self) -> None:
        def mock_run(cmd, **kwargs):
            class _Result:
                pass

            r = _Result()
            if "log" in cmd:
                r.returncode, r.stdout, r.stderr = 0, "abc1234\n", ""
            else:
                r.returncode, r.stdout, r.stderr = 1, "", "fatal: bad object abc1234^"
            return r

        with patch("scripts.checks._common.run", side_effect=mock_run):
            exit_code = vdc._replay_history(1)
        assert exit_code == 0

    def test_touched_files_tallied_mapped_and_unmapped(self, capsys) -> None:
        def mock_run(cmd, **kwargs):
            class _Result:
                pass

            r = _Result()
            if "log" in cmd:
                r.returncode, r.stdout, r.stderr = 0, "abc1234\n", ""
            else:
                r.returncode, r.stdout, r.stderr = (
                    0,
                    "scripts/checks/_pytest_diff.py\nscripts/executor/step_runner.py\ndocs/README.md\n",
                    "",
                )
            return r

        with (
            patch("scripts.checks._common.run", side_effect=mock_run),
            patch(
                "scripts.checks.misc.validate_diff_coverage._default_map_source_to_test",
                side_effect=lambda p: Path("/some/test.py") if "pytest_diff" in str(p) else None,
            ),
        ):
            vdc._replay_history(1)
        out = capsys.readouterr().out
        assert "touched src/scripts .py files: 2" in out
        assert "with a mapped covering test (current tree): 1" in out
        assert "with NO mapped covering test (current tree -- Decision 124-style carve-outs etc.): 1" in out


class TestCurrentDiffReportIntegration:
    """Full _current_diff_report path -- mixed COVERED/UNCOVERED/DEFERRED, the >50% DEFERRED
    ratio FINDING line, and the vacuous (zero-added-lines) examined(0) branch."""

    def _write_state(self, tmp_path: Path, *, selected: list[str], coverage_files: dict) -> None:
        debug = tmp_path / "logs" / "debug"
        debug.mkdir(parents=True)
        (debug / "selection-manifest.json").write_text(json.dumps({"selected": selected}), encoding="utf-8")
        (debug / "diff-coverage-deferrals.json").write_text(json.dumps({"state": "ok", "deferred": {}}), encoding="utf-8")
        (debug / "diff-coverage.json").write_text(json.dumps({"files": coverage_files}), encoding="utf-8")

    def test_mixed_classification_prints_ratio_and_finding(self, tmp_path: Path, capsys) -> None:
        self._write_state(
            tmp_path,
            selected=["tests/test_foo.py"],
            coverage_files={"src/foo.py": {"executed_lines": [1], "missing_lines": [2]}},
        )
        test_foo = tmp_path / "tests" / "test_foo.py"
        test_foo.parent.mkdir(parents=True)
        test_foo.write_text("", encoding="utf-8")
        with patch(
            "scripts.checks.misc.validate_diff_coverage.added_line_numbers_by_file",
            return_value={"src/foo.py": {1, 2}, "scripts/bar.py": {5}},
        ):
            registry.pop_declaration()
            vdc.validate_diff_coverage(
                [],
                root=tmp_path,
                base="origin/main",
                map_source_to_test=lambda p: test_foo if "foo" in str(p) and "src" in str(p) else None,
            )
        out = capsys.readouterr().out
        # src/foo.py:1 COVERED, src/foo.py:2 UNCOVERED, scripts/bar.py:5 DEFERRED (unmapped) -- 1/3 = 33.3%, no FINDING.
        assert "COVERED=1 UNCOVERED=1 DEFERRED=1" in out
        assert "DEFERRED-to-changed-line ratio: 33.3%" in out
        assert "FINDING" not in out
        declaration = registry.pop_declaration()
        assert declaration.count == 3

    def test_deferred_ratio_above_half_prints_finding(self, tmp_path: Path, capsys) -> None:
        self._write_state(tmp_path, selected=[], coverage_files={})
        with patch(
            "scripts.checks.misc.validate_diff_coverage.added_line_numbers_by_file",
            return_value={"scripts/bar.py": {1, 2, 3}},
        ):
            vdc.validate_diff_coverage([], root=tmp_path, base="origin/main", map_source_to_test=lambda p: None)
        out = capsys.readouterr().out
        assert "FINDING: DEFERRED ratio exceeds 50%" in out

    def test_zero_added_lines_is_vacuous(self, tmp_path: Path) -> None:
        self._write_state(tmp_path, selected=[], coverage_files={})
        registry.pop_declaration()
        with patch("scripts.checks.misc.validate_diff_coverage.added_line_numbers_by_file", return_value={}):
            vdc.validate_diff_coverage([], root=tmp_path, base="origin/main", map_source_to_test=lambda p: None)
        declaration = registry.pop_declaration()
        assert declaration.count == 0

    def test_file_with_empty_added_line_set_is_skipped(self, tmp_path: Path) -> None:
        """An entry with an empty line set (defensive -- added_line_numbers_by_file never
        actually emits one today) is a no-op, not a crash."""
        self._write_state(tmp_path, selected=[], coverage_files={})
        with patch(
            "scripts.checks.misc.validate_diff_coverage.added_line_numbers_by_file",
            return_value={"scripts/empty.py": set()},
        ):
            registry.pop_declaration()
            vdc.validate_diff_coverage([], root=tmp_path, base="origin/main", map_source_to_test=lambda p: None)
        declaration = registry.pop_declaration()
        assert declaration.count == 0
