"""Tests for scripts/checks/_marker_guard.py -- the shared raise-marker authorization module
(Decision 165, audit finding SGE-07, PLAN-size-gov-marker-guard).

Carries the BULK of the new coverage this plan introduces: extractor shapes (class-table
exclusion, comment immunity), the authorization rule (bare-root negative, band positive, no
body tokenization), composite `dir::step-id` keys, the supersession hop, moved-from, the empty
grandfather hook, and the cross-registry live-marker invariant + an independent-scan population
cross-check. Thin binding assertions for each of the five consumer guards live alongside their
own tests instead (mirror convention, Decision 131)."""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.checks import _common, _marker_guard
from scripts.checks._marker_guard import (
    RegistrySpec,
    authorization_failure,
    check_diff,
    check_present_markers,
    load_decision_bodies,
    make_flat_extractor,
    make_section_extractor,
)
from scripts.checks.ci_guards import validate_composite_action_shell_bodies as composite_module
from scripts.checks.misc import coverage_baseline as coverage_module
from scripts.checks.prose import prose_budget_raises as prose_module
from scripts.checks.sloc import validate_sloc_budget_raises as sloc_module
from scripts.checks.typing import mypy_baseline as mypy_module


class TestSectionExtractorScoping:
    """VP step 2: a `budgets:`-scoped extractor must not parse a class-table scalar (e.g.
    `limit: 500` under a `classes:` block) as a budget entry, while the flat extractor would --
    the seam that lets Slice B bind against a registry mixing a class table with flat budgets."""

    _FIXTURE = "classes:\n  small:\n    limit: 500\nbudgets:\n  scripts/foo.py: 100\n"

    def test_section_scope_excludes_class_table_scalar(self) -> None:
        entries = make_section_extractor("budgets")(self._FIXTURE)
        assert "limit" not in entries
        assert entries["scripts/foo.py"].value == 100

    def test_section_scope_skips_a_non_entry_line_inside_the_section(self) -> None:
        """A non-blank, non-comment line inside the section that doesn't match the entry
        grammar (e.g. free prose) is skipped, not raised on."""
        entries = make_section_extractor("budgets")("budgets:\n  notes here, no value\n  scripts/foo.py: 100\n")
        assert list(entries) == ["scripts/foo.py"]

    def test_flat_extractor_class_table_scalar_included(self) -> None:
        entries = make_flat_extractor("raise-approved")(self._FIXTURE)
        assert "limit" in entries
        assert entries["limit"].value == 500


class TestRequireReason:
    """High finding fix: require_reason=True (mirroring the incumbent composite-only
    `_RAISE_APPROVED_RE`'s `\\s+\\S` non-empty-reason requirement) makes a marker with an empty
    reason parse as NO marker at all -- it can never rescue an entry. Default (False) keeps a
    bare marker (no reason) valid, matching sloc/prose/coverage/mypy's incumbent behaviour."""

    def test_flat_extractor_require_reason_true_rejects_empty_reason(self) -> None:
        entries = make_flat_extractor("raise-approved", require_reason=True)("scripts/x.py: 800  # raise-approved: dec-1\n")
        assert entries["scripts/x.py"].marker is None
        assert entries["scripts/x.py"].reason is None

    def test_flat_extractor_require_reason_true_accepts_nonempty_reason(self) -> None:
        entries = make_flat_extractor("raise-approved", require_reason=True)(
            "scripts/x.py: 800  # raise-approved: dec-1 a real reason\n"
        )
        assert entries["scripts/x.py"].marker == "dec-1"

    def test_flat_extractor_require_reason_false_accepts_empty_reason(self) -> None:
        entries = make_flat_extractor("raise-approved", require_reason=False)("scripts/x.py: 800  # raise-approved: dec-1\n")
        assert entries["scripts/x.py"].marker == "dec-1"

    def test_section_extractor_require_reason_true_rejects_empty_reason(self) -> None:
        entries = make_section_extractor("r3", require_reason=True)(
            'r3:\n  ".github/actions/a::#0": 5  # raise-approved: dec-1\n'
        )
        assert entries[".github/actions/a::#0"].marker is None


class TestSectionExtractorCommentImmune:
    """VP step 3: rec-2954 finding 3 -- the incumbent _parse_raw_r3_markers dropped every
    marker declared after a column-0 comment inside its section. The shared extractor must not
    reproduce that defect."""

    _FIXTURE = 'r3:\n  ".github/actions/a::#0": 5\n# a column-0 comment mid-section\n  ".github/actions/b::#0": 7\n'

    def test_comment_immune_entries_declared_after_the_comment_are_still_returned(self) -> None:
        entries = make_section_extractor("r3")(self._FIXTURE)
        assert ".github/actions/a::#0" in entries
        assert ".github/actions/b::#0" in entries


class TestAuthorizationAncestorRule:
    """VP step 4: key-side ancestor-prefix authorization, verified against the REAL Decision
    161 corpus (never a synthetic fixture) so the bare-root negative and band positive are
    proven against actual authoring prose, not an idealised test double."""

    def test_bare_root_scripts_does_not_authorize_arbitrary_file(self) -> None:
        bodies = load_decision_bodies()
        assert authorization_failure("dec-161", "scripts/foo.py", bodies) is True

    def test_ancestor_band_authorizes_scripts_checks_subpath(self) -> None:
        bodies = load_decision_bodies()
        assert authorization_failure("dec-161", "scripts/checks/foo.py", bodies) is False

    def test_dec161_does_not_authorize_tests_test_checks_registry(self) -> None:
        bodies = load_decision_bodies()
        assert authorization_failure("dec-161", "tests/test_checks_registry.py", bodies) is True

    def test_no_glob_body_tokenization_markdown_bold_is_never_a_wildcard(self) -> None:
        """A body consisting only of markdown bold markers (`**Date`, `**Status`) must never
        authorize an unrelated key -- proving candidates come from the KEY, never from
        tokenizing the body."""
        bodies = {1: "**Status:** Decided\n**Date:** 2026-01-01\n**Decision:** Some unrelated text.\n"}
        assert authorization_failure("dec-1", "scripts/anything/at/all.py", bodies) is True

    def test_full_key_with_no_slash_authorized_by_its_own_literal_mention(self) -> None:
        """A non-path bare key (e.g. prose's S1 `root_ambient_load_set`) is authorized by its
        own full-key mention -- the >=2-segment floor governs TRUNCATED ancestors, not the
        full key itself."""
        bodies = {1: "**Decision:** Authorizes root_ambient_load_set.\n"}
        assert authorization_failure("dec-1", "root_ambient_load_set", bodies) is False

    def test_nonexistent_decision_fails_unconditionally(self) -> None:
        assert authorization_failure("dec-999999", "scripts/anything.py", {}) is True

    def test_archive_only_decision_is_present_in_loaded_bodies(self) -> None:
        """Decisions in DECISIONS_ARCHIVE.md count as authorizing (matches the shared parser's
        own _DECISIONS_MD_PATHS convention) -- dec-36 is archive-only (tests/decisions_md/
        test_parse.py TestArchiveCoverage)."""
        bodies = load_decision_bodies()
        assert 36 in bodies


class TestCompositeKeyAuthorization:
    """VP step 5: composite R3 authorization on a real "<action-rel-dir>::<step-id>" key."""

    _KEY = ".github/actions/materialise-tfvars::#0"  # every live r3 key uses the #N fallback

    def test_composite_key_authorized_via_action_rel_dir_mention(self) -> None:
        bodies = {1: "**Decision:** Authorizes .github/actions/materialise-tfvars.\n"}
        failure = authorization_failure("dec-1", self._KEY, bodies, mention_candidates=composite_module._r3_mention_candidates)
        assert failure is False

    def test_composite_key_bare_github_root_does_not_authorize(self) -> None:
        bodies = {1: "**Decision:** Mentions .github/ generically, nothing deeper.\n"}
        failure = authorization_failure("dec-1", self._KEY, bodies, mention_candidates=composite_module._r3_mention_candidates)
        assert failure is True


class TestSupersessionHop:
    """VP step 9: the Decision 149 compact-in-place coupling -- a compaction stub's body is
    authorized via ONE hop to its superseder; a stub pointing at a stub is not chased further."""

    def test_supersession_hop_authorizes_via_superseding_decision_body(self) -> None:
        bodies = {
            1: "**Status:** Superseded\n**Date:** 2026-01-01\n**Decision:** See Decision 2.\n**Superseded by: Decision 2**\n",
            2: "**Decision:** Authorizes scripts/checks/foo.py.\n",
        }
        assert authorization_failure("dec-1", "scripts/checks/foo.py", bodies) is False

    def test_compaction_stub_with_non_authorizing_superseder_still_fails(self) -> None:
        bodies = {
            1: "**Status:** Superseded\n**Date:** 2026-01-01\n**Decision:** See Decision 2.\n**Superseded by: Decision 2**\n",
            2: "**Decision:** Unrelated text entirely.\n",
        }
        assert authorization_failure("dec-1", "scripts/checks/foo.py", bodies) is True

    def test_supersession_hop_is_one_hop_only_a_stub_pointing_at_a_stub_is_not_chased(self) -> None:
        bodies = {
            1: "**Superseded by: Decision 2**\n**Decision:** stub one.\n",
            2: "**Superseded by: Decision 3**\n**Decision:** stub two, no mention.\n",
            3: "**Decision:** Authorizes scripts/checks/foo.py.\n",
        }
        assert authorization_failure("dec-1", "scripts/checks/foo.py", bodies) is True


class TestLiveMarkerCorpusInvariant:
    """VP step 6: every token-bearing marker across all five REAL registries is
    authorization-clean, and the flat registries' extractor-found population is cross-checked
    against an independent line-based scan of the same files -- never a hardcoded population
    count, which would red CI on the next legitimate marker addition to a PR that never touched
    this test file (tests/CLAUDE.md Test-count coupling; the exact rec-2572..2576 failure
    shape)."""

    _SPECS = (
        sloc_module._SPEC,
        prose_module._SPEC,
        coverage_module._SPEC,
        mypy_module._SPEC,
        composite_module._R3_SPEC,
    )

    def _live_marker_entries(self) -> list[tuple[RegistrySpec, str, str]]:
        found: list[tuple[RegistrySpec, str, str]] = []
        for spec in self._SPECS:
            path = _common.ROOT / spec.rel_path
            if not path.exists():
                continue
            entries = spec.extractor(path.read_text(encoding="utf-8"))
            for key, entry in entries.items():
                if entry.marker is not None:
                    found.append((spec, key, entry.marker))
        return found

    def test_live_markers_across_all_five_registries_are_authorization_clean(self) -> None:
        bodies = load_decision_bodies()
        for spec, key, marker in self._live_marker_entries():
            assert not authorization_failure(marker, key, bodies, spec.mention_candidates), (spec.rel_path, key, marker)

    # Whole-file scanning is semantically exact for these four ONLY: each is built by
    # make_flat_extractor (every non-blank, non-full-line-comment line is a candidate) with
    # require_reason left at its default False, so a line-based raw scan and the extractor
    # admit exactly the same markers. composite_module._R3_SPEC is deliberately EXCLUDED --
    # it is section-scoped (make_section_extractor("r3", ...)) over a baseline file that also
    # carries r1: and r3_workflows: sections, so a whole-file scan would count a marker in a
    # non-r3 section that the extractor never sees, reddening this assertion on a PR that
    # never touched this file (the rec-2572..2576 shape). It also sets require_reason=True, a
    # second admission asymmetry a token-only regex cannot mirror. That spec stays covered by
    # the authorization-clean test above, which needs no independent count.
    _FLAT_SCAN_SPECS = (
        sloc_module._SPEC,
        prose_module._SPEC,
        coverage_module._SPEC,
        mypy_module._SPEC,
    )

    def test_flat_registry_marker_population_matches_independent_raw_scan(self) -> None:
        """Independent cross-check, not a hardcoded count: a line-based raw scan of each
        flat-extractor registry file (keyed on the same spec.token, but never touching
        spec.extractor or _ENTRY_RE) must find exactly as many markers as the structured
        extractors do. Catches an extractor regression in either direction while staying
        growth-safe -- the population may grow indefinitely by legitimate addition without ever
        reddening this assertion, since both sides grow together. The scan mirrors the flat
        extractor's blank/full-line-comment skip so a marker cited inside a file's header prose
        is not counted on the raw side alone."""
        extracted = sum(1 for spec, _key, _marker in self._live_marker_entries() if spec in self._FLAT_SCAN_SPECS)
        independent_count = 0
        for spec in self._FLAT_SCAN_SPECS:
            path = _common.ROOT / spec.rel_path
            if not path.exists():
                continue
            marker_re = re.compile(rf"#\s*{re.escape(spec.token)}:\s*dec-\d+")
            for line in path.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                if marker_re.search(line):
                    independent_count += 1
        assert extracted == independent_count


class TestRetroactiveScanWiredIntoAllFourGenericConsumers:
    """Medium finding: pins that each of the four generic (check_diff/check_present_markers)
    consumers actually WIRES IN the retroactive scan, not just that check_present_markers itself
    works in isolation. Fixture shape per test: base == current (no diff-side violation --
    check_diff alone finds nothing), but the current entry carries an unauthorized marker --
    only check_present_markers can catch it. If a future refactor drops
    `+ _marker_guard.check_present_markers(_SPEC)` from any of the four consumers, that
    consumer's test below reds while the other four (and check_present_markers' own unit tests)
    stay green -- the exact mutation this class exists to catch."""

    def test_sloc_wires_in_retroactive_scan(self, tmp_path: Path) -> None:
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        body = "budgets:\n  scripts/x.py: 800  # raise-approved: dec-999999 bogus\n"
        (config_dir / "sloc_budgets.yaml").write_text(body, encoding="utf-8")
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            sloc_module.validate_sloc_budget_raises(failed, base_reader=lambda rel: body)
        assert failed, "unauthorized marker present in an unchanged entry must still be caught"

    def test_prose_wires_in_retroactive_scan(self, tmp_path: Path) -> None:
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        body = "S1:\n  root_ambient_load_set: 40000  # raise-approved: dec-999999 bogus\n"
        (config_dir / "prose_budgets.yaml").write_text(body, encoding="utf-8")
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            prose_module.validate_prose_budget_raises(failed, base_reader=lambda rel: body)
        assert failed, "unauthorized marker present in an unchanged entry must still be caught"

    def test_coverage_wires_in_retroactive_scan(self, tmp_path: Path) -> None:
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        body = "entries:\n  scripts/x.py: 60.0  # baseline-lowered: dec-999999 bogus\n"
        (config_dir / "coverage_baseline.yaml").write_text(body, encoding="utf-8")
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            coverage_module.validate_coverage_baseline_edits(failed, base_reader=lambda rel: body)
        assert failed, "unauthorized marker present in an unchanged entry must still be caught"

    def test_mypy_wires_in_retroactive_scan(self, tmp_path: Path) -> None:
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        body = "entries:\n  scripts/x.py: 5  # baseline-raised: dec-999999 bogus\n"
        (config_dir / "mypy_baseline.yaml").write_text(body, encoding="utf-8")
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            mypy_module.validate_mypy_baseline_edits(failed, base_reader=lambda rel: body)
        assert failed, "unauthorized marker present in an unchanged entry must still be caught"


class TestMovedFromSameDiffProof:
    """VP step 11: the Decision 161 clause 4 `moved from <old-path>` form is a same-diff proof
    (base-map presence, current-map absence), gated behind RegistrySpec.moved_from_relief and
    skipped (never failed) by the retroactive scan, which has no base map to prove against."""

    _SPEC = RegistrySpec(
        rel_path="config/fake_moved_from_baseline.yaml",
        token="baseline-raised",
        gated_direction="up",
        extractor=make_flat_extractor("baseline-raised", value_type=int),
        gates_new_entry=lambda value: value > 0,
        label="fake moved-from guard",
        moved_from_relief=True,
    )

    def _write(self, tmp_path: Path, body: str) -> None:
        target = tmp_path / self._SPEC.rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")

    def test_moved_from_passes_when_old_path_proven_in_base_map(self, tmp_path: Path) -> None:
        self._write(tmp_path, "scripts/new.py: 3  # baseline-raised: dec-1 moved from scripts/old.py\n")
        with patch("scripts.checks._common.ROOT", tmp_path):
            violations = check_diff(self._SPEC, base_reader=lambda rel: "scripts/old.py: 3\n")
        assert violations == []

    def test_moved_from_fails_when_old_path_never_existed_in_base(self, tmp_path: Path) -> None:
        self._write(tmp_path, "scripts/new.py: 3  # baseline-raised: dec-1 moved from scripts/old.py\n")
        with patch("scripts.checks._common.ROOT", tmp_path):
            violations = check_diff(self._SPEC, base_reader=lambda rel: "")
        assert violations

    def test_moved_from_fails_when_old_path_still_present_in_current(self, tmp_path: Path) -> None:
        self._write(
            tmp_path,
            "scripts/new.py: 3  # baseline-raised: dec-1 moved from scripts/old.py\nscripts/old.py: 3\n",
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            violations = check_diff(self._SPEC, base_reader=lambda rel: "scripts/old.py: 3\n")
        assert violations

    def test_moved_from_skipped_not_failed_by_retroactive_scan(self, tmp_path: Path) -> None:
        self._write(tmp_path, "scripts/new.py: 3  # baseline-raised: dec-1 moved from scripts/old.py\n")
        with patch("scripts.checks._common.ROOT", tmp_path):
            violations = check_present_markers(self._SPEC)
        assert violations == []

    def test_moved_from_relief_off_by_default_on_a_fresh_spec(self) -> None:
        default_spec = RegistrySpec(
            rel_path="x",
            token="raise-approved",
            gated_direction="up",
            extractor=make_flat_extractor("raise-approved"),
            gates_new_entry=lambda value: True,
            label="x",
        )
        assert default_spec.moved_from_relief is False


class TestDefaultBaseReader:
    def test_returns_stdout_on_success(self) -> None:
        fake_result = type("FakeResult", (), {"returncode": 0, "stdout": "budgets:\n  scripts/x.py: 1\n"})()
        with patch("scripts.checks._common.run", return_value=fake_result):
            assert _marker_guard.default_base_reader("config/sloc_budgets.yaml") == "budgets:\n  scripts/x.py: 1\n"

    def test_reads_origin_main_not_head(self) -> None:
        """Pins the argv contract: `git show origin/main:<path>`, never `HEAD:<path>` -- the
        deleted per-consumer TestDefaultBaseReader classes asserted this before the move; nothing
        else pins it post-consolidation."""
        mock_result = MagicMock(returncode=0, stdout="budgets:\n  scripts/x.py: 1\n")
        with patch("scripts.checks._common.run", return_value=mock_result) as mock_run:
            _marker_guard.default_base_reader("config/sloc_budgets.yaml")
        assert mock_run.call_args.args[0] == ["git", "show", "origin/main:config/sloc_budgets.yaml"]

    def test_returns_none_on_nonzero_exit(self) -> None:
        fake_result = type("FakeResult", (), {"returncode": 1, "stdout": ""})()
        with patch("scripts.checks._common.run", return_value=fake_result):
            assert _marker_guard.default_base_reader("config/sloc_budgets.yaml") is None


class TestCheckDiffAndCheckPresentMarkersDirectly:
    """Direct coverage of check_diff/check_present_markers' own branches -- the five consumer
    guards exercise these indirectly via their own test suites, but this module's coverage
    threshold is measured against tests/checks/test__marker_guard.py alone (Decision 131 mirror
    convention)."""

    _UP_SPEC = RegistrySpec(
        rel_path="config/fake_up.yaml",
        token="raise-approved",
        gated_direction="up",
        extractor=make_flat_extractor("raise-approved", value_type=int),
        gates_new_entry=lambda value: value > 500,
        label="fake up guard",
    )
    _DOWN_SPEC = RegistrySpec(
        rel_path="config/fake_down.yaml",
        token="baseline-lowered",
        gated_direction="down",
        extractor=make_flat_extractor("baseline-lowered", value_type=float),
        gates_new_entry=lambda value: True,
        label="fake down guard",
    )
    _MOVED_FROM_SPEC = RegistrySpec(
        rel_path="config/fake_moved.yaml",
        token="baseline-raised",
        gated_direction="up",
        extractor=make_flat_extractor("baseline-raised", value_type=int),
        gates_new_entry=lambda value: True,
        label="fake moved guard",
        moved_from_relief=True,
    )

    def _write(self, tmp_path: Path, rel_path: str, body: str) -> None:
        target = tmp_path / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")

    def test_check_diff_current_file_absent_returns_empty(self, tmp_path: Path) -> None:
        with patch("scripts.checks._common.ROOT", tmp_path):
            assert check_diff(self._UP_SPEC, base_reader=lambda rel: "budgets: {}\n") == []

    def test_check_diff_skips_when_base_reader_returns_none(self, tmp_path: Path) -> None:
        self._write(tmp_path, self._UP_SPEC.rel_path, "scripts/x.py: 600\n")
        with patch("scripts.checks._common.ROOT", tmp_path):
            assert check_diff(self._UP_SPEC, base_reader=lambda rel: None) == []

    def test_check_diff_new_entry_below_gates_new_entry_threshold_is_not_gated(self, tmp_path: Path) -> None:
        self._write(tmp_path, self._UP_SPEC.rel_path, "scripts/x.py: 100\n")
        with patch("scripts.checks._common.ROOT", tmp_path):
            assert check_diff(self._UP_SPEC, base_reader=lambda rel: "") == []

    def test_check_diff_down_direction_lowered_with_no_marker_is_a_violation(self, tmp_path: Path) -> None:
        self._write(tmp_path, self._DOWN_SPEC.rel_path, "scripts/x.py: 60.0\n")
        with patch("scripts.checks._common.ROOT", tmp_path):
            violations = check_diff(self._DOWN_SPEC, base_reader=lambda rel: "scripts/x.py: 80.0\n")
        assert violations and "unauthorized" in violations[0]

    def test_check_diff_marker_present_but_unauthorized_is_a_violation(self, tmp_path: Path) -> None:
        self._write(tmp_path, self._UP_SPEC.rel_path, "scripts/x.py: 800  # raise-approved: dec-1 no real authority\n")
        with patch("scripts.checks._common.ROOT", tmp_path):
            violations = check_diff(self._UP_SPEC, base_reader=lambda rel: "scripts/x.py: 600\n")
        assert violations and "does not authorize" in violations[0]

    def test_check_diff_moved_from_relief_marker_with_no_reason_falls_through_to_authorization(self, tmp_path: Path) -> None:
        """A marker carrying no reason text at all (`# baseline-raised: dec-1`, nothing after)
        has reason=None -- _moved_from_path(None) returns None, so the moved_from branch is
        skipped and ordinary authorization applies."""
        self._write(tmp_path, self._MOVED_FROM_SPEC.rel_path, "scripts/x.py: 3  # baseline-raised: dec-1\n")
        with patch("scripts.checks._common.ROOT", tmp_path):
            violations = check_diff(self._MOVED_FROM_SPEC, base_reader=lambda rel: "")
        assert violations and "does not authorize" in violations[0]

    def test_check_present_markers_current_file_absent_returns_empty(self, tmp_path: Path) -> None:
        with patch("scripts.checks._common.ROOT", tmp_path):
            assert check_present_markers(self._UP_SPEC) == []

    def test_check_present_markers_skips_entry_with_no_marker(self, tmp_path: Path) -> None:
        self._write(tmp_path, self._UP_SPEC.rel_path, "scripts/x.py: 600\n")
        with patch("scripts.checks._common.ROOT", tmp_path):
            assert check_present_markers(self._UP_SPEC) == []

    def test_check_present_markers_unauthorized_marker_is_a_violation(self, tmp_path: Path) -> None:
        self._write(tmp_path, self._UP_SPEC.rel_path, "scripts/x.py: 600  # raise-approved: dec-1 no real authority\n")
        with patch("scripts.checks._common.ROOT", tmp_path):
            violations = check_present_markers(self._UP_SPEC)
        assert violations and "retroactive scan" in violations[0]


class TestCoverageGrandfatheredCommentsAreNotMarkers:
    """VP acceptance criterion 12: coverage's `# grandfathered dec-159` roster comments carry no
    marker token and must never be treated as markers by the retroactive scan. Decision 169
    deliberately converts the scripts/validate.py entry from grandfathered to a real, authorized
    `baseline-lowered: dec-169` marker -- the roster count drops from 9 to 8, and that one entry
    is the sole legitimate exception to the "no entry parses as a marker" rule."""

    def test_grandfathered_comments_carry_no_baseline_lowered_token(self) -> None:
        raw_text = (_common.ROOT / coverage_module._SPEC.rel_path).read_text(encoding="utf-8")
        assert raw_text.count("# grandfathered dec-159") >= 8, "expected the 8 known grandfathered roster comments"

        entries = coverage_module._SPEC.extractor(raw_text)
        markers = [(k, e.marker) for k, e in entries.items() if e.marker is not None]
        assert markers == [("scripts/validate.py", "dec-169")], (
            f"only the deliberate scripts/validate.py baseline-lowered marker may parse as a marker, got: {markers}"
        )


class TestGrandfatherHookFrozenAndEmpty:
    def test_retro_scan_grandfather_is_a_frozenset_and_empty(self) -> None:
        assert isinstance(_marker_guard.RETRO_SCAN_GRANDFATHER, frozenset)
        assert len(_marker_guard.RETRO_SCAN_GRANDFATHER) == 0
