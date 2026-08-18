"""Tests for validate_decisions_size(). Mirror of
scripts/checks/decisions/validate_decisions_size.py (Decision 134 / Decision 114 parity;
PLAN-decision-entry-flow-governance / Decision 167 adds the per-entry authoring cap, hard-fail
tier flipped by migration-step-3-grandfathering / T2.56 migration step 3).

The live-byte-only ceiling (_DECISIONS_LIVE_MAX_BYTES, Decision 145's stopgap raise to 500_000)
was RETIRED by PLAN-decision-scout-bounded-retrieval -- the decision-scout gate no longer reads
the live file wholesale, so the ceiling that guard existed to size no longer has a referent. Only
_DECISIONS_LIVE_MAX_H2 (132) and _DECISIONS_COMBINED_MAX_BYTES (780_000) survive as hard-fail
ceilings; this file covers their boundaries plus a case proving a live file ABOVE the old 500_000
value now passes on its own while a combined breach still FAILs -- plus the
_PER_ENTRY_CAP_BYTES (6_144) hard-fail per-NEW-entry cap below (Decision 167 clause 3, fired by
migration step 3)."""

from pathlib import Path
from unittest.mock import patch

from scripts.checks import registry
from scripts.checks.decisions.validate_decisions_size import (
    _DECISIONS_COMBINED_MAX_BYTES,
    _DECISIONS_LIVE_MAX_H2,
    _PER_ENTRY_CAP_BYTES,
    _decisions_size_issues,
    _new_entries_examined_count,
    _per_entry_cap_failures,
    validate_decisions_size,
)


def _live_header_block(count: int) -> str:
    """Build `count` synthetic '## Decision N:' live-file-shaped headers with a small body."""
    return "".join(f"## Decision {i}: Test entry {i}\n\nBody text.\n\n---\n\n" for i in range(1, count + 1))


class TestDecisionsSizeIssuesLiveH2:
    """_decisions_size_issues() live-header-count boundary cases (_DECISIONS_LIVE_MAX_H2)."""

    def test_below_ceiling_returns_empty(self) -> None:
        live = _live_header_block(_DECISIONS_LIVE_MAX_H2 - 1)
        assert _decisions_size_issues(live, "") == []

    def test_at_ceiling_returns_empty(self) -> None:
        live = _live_header_block(_DECISIONS_LIVE_MAX_H2)
        assert _decisions_size_issues(live, "") == []

    def test_above_ceiling_fails(self) -> None:
        live = _live_header_block(_DECISIONS_LIVE_MAX_H2 + 1)
        issues = _decisions_size_issues(live, "")
        assert len(issues) == 1
        assert "live '## Decision' headers" in issues[0]
        assert str(_DECISIONS_LIVE_MAX_H2 + 1) in issues[0]


class TestDecisionsSizeIssuesCombined:
    """_decisions_size_issues() combined live+archive-byte-ceiling boundary cases
    (_DECISIONS_COMBINED_MAX_BYTES), with the live-H2 ceiling not breached."""

    _LIVE_SIZE = 350_000  # comfortably under _DECISIONS_COMBINED_MAX_BYTES (780_000) on its own

    def test_below_ceiling_returns_empty(self) -> None:
        live = "x" * self._LIVE_SIZE
        archive = "x" * (_DECISIONS_COMBINED_MAX_BYTES - self._LIVE_SIZE - 1)
        assert _decisions_size_issues(live, archive) == []

    def test_at_ceiling_returns_empty(self) -> None:
        live = "x" * self._LIVE_SIZE
        archive = "x" * (_DECISIONS_COMBINED_MAX_BYTES - self._LIVE_SIZE)
        assert _decisions_size_issues(live, archive) == []

    def test_above_ceiling_fails(self) -> None:
        live = "x" * self._LIVE_SIZE
        archive = "x" * (_DECISIONS_COMBINED_MAX_BYTES - self._LIVE_SIZE + 1)
        issues = _decisions_size_issues(live, archive)
        assert len(issues) == 1
        assert "combined" in issues[0]
        assert str(_DECISIONS_COMBINED_MAX_BYTES) in issues[0]

    def test_archive_bytes_count_toward_combined_ceiling(self) -> None:
        """DECISIONS_ARCHIVE.md bytes alone trip the combined ceiling even with a tiny live file --
        proves the archive file is genuinely covered by the guard, not just accepted and ignored."""
        live = "tiny live file, well under every live ceiling"
        archive = "x" * (_DECISIONS_COMBINED_MAX_BYTES + 1)
        issues = _decisions_size_issues(live, archive)
        assert any("combined" in issue for issue in issues)

    def test_live_file_above_old_500000_ceiling_now_passes_alone(self) -> None:
        """The retired live-byte ceiling was 500_000 -- a live file bigger than that must now
        pass on its own (no live-byte check left), as long as it stays under the header count and
        the combined ceiling still has room for it."""
        live = "x" * 550_000
        archive = "x" * 1_000  # combined well under 700_000
        assert _decisions_size_issues(live, archive) == []

    def test_live_file_above_old_500000_ceiling_still_fails_via_combined(self) -> None:
        """Same oversized live file, but now paired with enough archive bytes to breach the
        surviving combined ceiling -- proves the combined ceiling is a real backstop, not a
        no-op, for exactly the live-byte case the retired ceiling used to catch."""
        live = "x" * 550_000
        archive = "x" * (_DECISIONS_COMBINED_MAX_BYTES - 550_000 + 1)
        issues = _decisions_size_issues(live, archive)
        assert any("combined" in issue for issue in issues)


class TestDecisionsSizeIssuesReliefValveMessage:
    """The COMBINED-breach message names relief valves that actually reduce combined bytes --
    never claims archival (which only moves bytes between the two counted files) still helps."""

    def test_message_names_effective_relief_valves(self) -> None:
        live = "x" * 350_000
        archive = "x" * (_DECISIONS_COMBINED_MAX_BYTES - 350_000 + 1)
        issues = _decisions_size_issues(live, archive)
        assert len(issues) == 1
        assert "compact" in issues[0].lower()
        assert "149" in issues[0]
        assert "per-entry" in issues[0].lower()

    def test_message_states_archival_does_not_relieve_combined_ceiling(self) -> None:
        """Archival must be named as INERT against the combined ceiling, not as a working valve
        -- the plan's finding is that moving bytes between the two counted files is a no-op."""
        live = "x" * 350_000
        archive = "x" * (_DECISIONS_COMBINED_MAX_BYTES - 350_000 + 1)
        issues = _decisions_size_issues(live, archive)
        message = issues[0].lower()
        assert "does not relieve" in message
        assert "moves bytes between the two counted files" in message


class TestValidateDecisionsSizeRegisteredCheck:
    """Exercises the REGISTERED validate_decisions_size(failed) function itself (not just the
    pure helper), via patch("scripts.checks._common.ROOT", tmp_path) over a synthetic
    docs/DECISIONS.md + docs/DECISIONS_ARCHIVE.md tree -- mirrors
    tests/checks/roadmap/test_validate_platform_roadmap.py's TestPlatformRoadmapCriteriaIntegrity
    pattern, so validate_test_coverage's 100%-of-new-code gate covers the check function's own
    file-read / count / print / failed.append branches."""

    def _write_docs(self, tmp_path: Path, live_text: str, archive_text: str) -> None:
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir(parents=True, exist_ok=True)
        (docs_dir / "DECISIONS.md").write_text(live_text, encoding="utf-8")
        (docs_dir / "DECISIONS_ARCHIVE.md").write_text(archive_text, encoding="utf-8")

    def test_pass_case(self, tmp_path: Path) -> None:
        self._write_docs(tmp_path, "## Decision 1: Small entry\n\nBody.\n\n---\n\n", "Archive body.\n")
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_decisions_size(failed)
        assert failed == []

    def test_pass_case_live_file_above_old_500000_byte_value(self, tmp_path: Path) -> None:
        """End-to-end (through the registered check, not just the pure helper): a live file
        bigger than the retired 500_000-byte ceiling passes when header count and combined bytes
        both stay within their surviving ceilings."""
        self._write_docs(tmp_path, "x" * 550_000, "x" * 1_000)
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_decisions_size(failed)
        assert failed == []

    def test_fail_case_combined_breach(self, tmp_path: Path) -> None:
        self._write_docs(tmp_path, "x" * 350_000, "x" * (_DECISIONS_COMBINED_MAX_BYTES - 350_000 + 1))
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_decisions_size(failed)
        assert "DECISIONS size governance" in failed

    def test_fail_case_header_count_breach(self, tmp_path: Path) -> None:
        self._write_docs(tmp_path, _live_header_block(_DECISIONS_LIVE_MAX_H2 + 1), "")
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_decisions_size(failed)
        assert "DECISIONS size governance" in failed

    def test_missing_live_file_fails(self, tmp_path: Path) -> None:
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir(parents=True, exist_ok=True)
        (docs_dir / "DECISIONS_ARCHIVE.md").write_text("", encoding="utf-8")
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_decisions_size(failed)
        assert "DECISIONS size governance" in failed

    def test_missing_archive_file_fails(self, tmp_path: Path) -> None:
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir(parents=True, exist_ok=True)
        (docs_dir / "DECISIONS.md").write_text("## Decision 1: X\n", encoding="utf-8")
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_decisions_size(failed)
        assert "DECISIONS size governance" in failed


class TestLiveByteCeilingRetired:
    """VP step 6 / graduation candidate 'decisions-live-ceiling-retired-others-intact':
    _DECISIONS_LIVE_MAX_BYTES (Decision 145's stopgap) no longer exists as a module attribute --
    a standing regression guard against reintroducing the retired ceiling."""

    def test_live_max_bytes_constant_does_not_exist(self) -> None:
        import scripts.checks.decisions.validate_decisions_size as m

        assert not hasattr(m, "_DECISIONS_LIVE_MAX_BYTES")


class TestBridgeCeilingValues:
    """Deliberate bridge values (docs/plans/PLAN-decision-ceiling-bridge.yaml) pending the
    contract-first governance rebuild on claude/contract-first-audit-p5f0tu: the live '## Decision'
    header ceiling moves 120 -> 132 and the combined byte ceiling moves 700_000 -> 780_000. Every
    pre-existing boundary test in this module expresses its assertions RELATIVE to the constants
    (_DECISIONS_LIVE_MAX_H2 - 1, + 1, and so on) and so passes identically before and after the
    raise -- these absolute-literal assertions are what actually distinguishes the two."""

    def test_132_headers_returns_no_issues(self) -> None:
        live = _live_header_block(132)
        assert _decisions_size_issues(live, "") == []

    def test_133_headers_returns_exactly_one_header_issue(self) -> None:
        live = _live_header_block(133)
        issues = _decisions_size_issues(live, "")
        assert len(issues) == 1
        assert "live '## Decision' headers" in issues[0]

    def test_combined_780000_bytes_returns_no_issues(self) -> None:
        live = "x" * 780_000
        assert _decisions_size_issues(live, "") == []

    def test_combined_780001_bytes_returns_exactly_one_byte_issue(self) -> None:
        live = "x" * 780_001
        issues = _decisions_size_issues(live, "")
        assert len(issues) == 1
        assert "combined" in issues[0]

    def test_live_max_h2_pinned_to_132(self) -> None:
        assert _DECISIONS_LIVE_MAX_H2 == 132

    def test_combined_max_bytes_pinned_to_780000(self) -> None:
        assert _DECISIONS_COMBINED_MAX_BYTES == 780_000

    def test_header_breach_message_omits_134(self) -> None:
        live = _live_header_block(133)
        issues = _decisions_size_issues(live, "")
        assert all("134" not in issue for issue in issues)

    def test_combined_breach_message_omits_134(self) -> None:
        live = "x" * 780_001
        issues = _decisions_size_issues(live, "")
        assert all("134" not in issue for issue in issues)


def _make_block(number: int, target_bytes: int) -> str:
    """A synthetic '## Decision N:' heading-inclusive block whose UTF-8 byte length is exactly
    target_bytes -- header/filler/trailing-newline are all ASCII, so char count == byte count."""
    header = f"## Decision {number}: Test entry\n\n"
    footer = "\n"
    filler_len = target_bytes - len((header + footer).encode("utf-8"))
    assert filler_len >= 0, "target_bytes too small for the fixed header/footer"
    return header + ("x" * filler_len) + footer


def _write_docs(tmp_path: Path, live_text: str, archive_text: str = "") -> None:
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    (docs_dir / "DECISIONS.md").write_text(live_text, encoding="utf-8")
    (docs_dir / "DECISIONS_ARCHIVE.md").write_text(archive_text, encoding="utf-8")


class TestPerEntryCap:
    """test_obligations selector alias for the hard-fail flip -- see
    TestPerEntryCapFailuresPureFunction below for the full boundary coverage."""

    def test_new_over_cap_entry_fails(self, tmp_path: Path) -> None:
        _write_docs(tmp_path, _make_block(5, _PER_ENTRY_CAP_BYTES + 1))
        failures = _per_entry_cap_failures(tmp_path, baseline_numbers=set())
        assert len(failures) == 1
        assert "Decision 5" in failures[0]

        historical_failures = _per_entry_cap_failures(tmp_path, baseline_numbers={5})
        assert historical_failures == [], "a historical entry must still never be measured"


class TestPerEntryCapFailuresPureFunction:
    """_per_entry_cap_failures(root, baseline_numbers) -- hard-fail tier, forward-only.
    Renamed from _per_entry_cap_warnings / TestPerEntryCapWarningsPureFunction
    (migration-step-3-grandfathering: Decision 167 clause 3's WARN pre-commitment fires)."""

    def test_over_cap_new_entry_fails(self, tmp_path: Path) -> None:
        _write_docs(tmp_path, _make_block(5, _PER_ENTRY_CAP_BYTES + 1))
        failures = _per_entry_cap_failures(tmp_path, baseline_numbers=set())
        assert len(failures) == 1
        assert "Decision 5" in failures[0]
        assert str(_PER_ENTRY_CAP_BYTES) in failures[0]

    def test_over_cap_historical_entry_is_silent(self, tmp_path: Path) -> None:
        _write_docs(tmp_path, _make_block(5, _PER_ENTRY_CAP_BYTES + 1))
        failures = _per_entry_cap_failures(tmp_path, baseline_numbers={5})
        assert failures == []

    def test_new_entry_at_exactly_cap_is_silent(self, tmp_path: Path) -> None:
        _write_docs(tmp_path, _make_block(5, _PER_ENTRY_CAP_BYTES))
        failures = _per_entry_cap_failures(tmp_path, baseline_numbers=set())
        assert failures == []

    def test_new_entry_under_cap_is_silent(self, tmp_path: Path) -> None:
        _write_docs(tmp_path, _make_block(5, _PER_ENTRY_CAP_BYTES - 100))
        failures = _per_entry_cap_failures(tmp_path, baseline_numbers=set())
        assert failures == []

    def test_archive_over_cap_new_entry_fails_too(self, tmp_path: Path) -> None:
        _write_docs(tmp_path, "", archive_text=_make_block(9, _PER_ENTRY_CAP_BYTES + 1))
        failures = _per_entry_cap_failures(tmp_path, baseline_numbers=set())
        assert len(failures) == 1
        assert "Decision 9" in failures[0]

    def test_missing_files_yield_no_failures(self, tmp_path: Path) -> None:
        assert _per_entry_cap_failures(tmp_path, baseline_numbers=set()) == []


class TestPerEntryCapThroughRegisteredCheck:
    """End-to-end through validate_decisions_size(failed, root=..., baseline_reader=...) -- a
    non-default root always exercises the per-entry sub-check (deterministic for tests,
    bypassing the production changed-files short-circuit; see the module docstring)."""

    def test_over_cap_new_entry_fails_and_prints_fail(self, tmp_path: Path, capsys) -> None:
        """INVERTED from the pre-flip test_over_cap_new_entry_prints_warning_and_never_fails
        (which asserted failed == []) -- migration-step-3-grandfathering fires Decision 167
        clause 3's hard-fail flip; a red result here IS the flip working."""
        _write_docs(tmp_path, _make_block(5, _PER_ENTRY_CAP_BYTES + 1))
        failed: list[str] = []
        validate_decisions_size(failed, root=tmp_path, baseline_reader=lambda r: set())
        assert "DECISIONS size governance" in failed
        out = capsys.readouterr().out
        assert "FAIL" in out
        assert "Decision 5" in out

    def test_over_cap_historical_entry_produces_no_per_entry_output(self, tmp_path: Path, capsys) -> None:
        """Re-anchored on the new failure surface: a "WARN not in out" assertion would pass
        VACUOUSLY post-flip (WARN is never printed by this module at all anymore) -- the real
        claim is that a historical (baseline-present) entry never appears in the per-entry
        output or in `failed`, regardless of its size."""
        _write_docs(tmp_path, _make_block(5, _PER_ENTRY_CAP_BYTES + 1))
        failed: list[str] = []
        validate_decisions_size(failed, root=tmp_path, baseline_reader=lambda r: {5})
        assert failed == []
        assert "Decision 5" not in capsys.readouterr().out

    def test_boundary_at_exactly_cap_is_silent(self, tmp_path: Path, capsys) -> None:
        """Re-anchored (see test_over_cap_historical_entry_produces_no_per_entry_output above)."""
        _write_docs(tmp_path, _make_block(5, _PER_ENTRY_CAP_BYTES))
        failed: list[str] = []
        validate_decisions_size(failed, root=tmp_path, baseline_reader=lambda r: set())
        assert failed == []
        assert "Decision 5" not in capsys.readouterr().out

    def test_unreachable_baseline_advisory_skips_per_entry_cap(self, tmp_path: Path, capsys) -> None:
        """A non-default root with NO injected baseline_reader and no .git directory -- the
        default reader's own reachability check returns the None sentinel; the two stock
        ceilings still ran above (unaffected). Re-anchored: also asserts the SKIP message
        printed, so this proves the skip path fired rather than merely that no over-cap entry
        happened to be measured."""
        _write_docs(tmp_path, _make_block(5, _PER_ENTRY_CAP_BYTES + 1))
        failed: list[str] = []
        validate_decisions_size(failed, root=tmp_path)
        assert failed == []
        assert "SKIP" in capsys.readouterr().out

    def test_stock_ceiling_breach_and_per_entry_failure_can_coexist(self, tmp_path: Path, capsys) -> None:
        """INVERTED from the pre-flip test_stock_ceiling_breach_and_per_entry_warning_can_coexist
        -- a combined-bytes breach and the per-entry hard-fail on the same entry both contribute
        to `failed` (the label is appended twice; membership is what matters), and both surfaces
        print their own FAIL line."""
        _write_docs(
            tmp_path,
            _make_block(5, _PER_ENTRY_CAP_BYTES + 1),
            archive_text="x" * (_DECISIONS_COMBINED_MAX_BYTES + 1),
        )
        failed: list[str] = []
        validate_decisions_size(failed, root=tmp_path, baseline_reader=lambda r: set())
        assert "DECISIONS size governance" in failed
        out = capsys.readouterr().out
        assert "combined" in out
        assert "Decision 5" in out


class TestDeclarationAdoption:
    """Decision 170 touch-it-fix-it: this check was baselined (no declaration) before this
    plan; editing it now obligates a registry.examined()/skipped() declaration on ALL FIVE of
    its reachable exit paths."""

    def test_missing_live_file_skips(self, tmp_path: Path) -> None:
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "DECISIONS_ARCHIVE.md").write_text("", encoding="utf-8")
        failed: list[str] = []
        registry.pop_declaration()
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_decisions_size(failed)
        declaration = registry.pop_declaration()
        assert declaration is not None
        assert declaration.kind == "skipped"
        assert "DECISIONS.md" in declaration.reason

    def test_missing_archive_file_skips(self, tmp_path: Path) -> None:
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "DECISIONS.md").write_text("## Decision 1: X\n", encoding="utf-8")
        failed: list[str] = []
        registry.pop_declaration()
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_decisions_size(failed)
        declaration = registry.pop_declaration()
        assert declaration is not None
        assert declaration.kind == "skipped"
        assert "DECISIONS_ARCHIVE.md" in declaration.reason

    def test_cost_gated_early_return_examines_zero(self, tmp_path: Path) -> None:
        """using_default_root AND neither DECISIONS file changed (an empty-.git-less tmp_path
        naturally yields get_changed_files() == []) -- definitively zero new entries to check,
        not an unmet precondition, so this declares examined(0), never skipped()."""
        _write_docs(tmp_path, "## Decision 1: Small entry\n\nBody.\n\n---\n\n", "Archive body.\n")
        failed: list[str] = []
        registry.pop_declaration()
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_decisions_size(failed)
        declaration = registry.pop_declaration()
        assert declaration is not None
        assert declaration.kind == "examined"
        assert declaration.count == 0
        assert declaration.unit == "new_decision_entries"

    def test_unreachable_baseline_skips(self, tmp_path: Path) -> None:
        _write_docs(tmp_path, "## Decision 1: X\n\nBody.\n\n---\n\n")
        failed: list[str] = []
        registry.pop_declaration()
        validate_decisions_size(failed, root=tmp_path, baseline_reader=lambda r: None)
        declaration = registry.pop_declaration()
        assert declaration is not None
        assert declaration.kind == "skipped"
        assert "origin/main" in declaration.reason
        assert failed == []

    def test_fallthrough_examines_new_entry_count(self, tmp_path: Path) -> None:
        _write_docs(tmp_path, _make_block(5, 200))
        failed: list[str] = []
        registry.pop_declaration()
        validate_decisions_size(failed, root=tmp_path, baseline_reader=lambda r: set())
        declaration = registry.pop_declaration()
        assert declaration is not None
        assert declaration.kind == "examined"
        assert declaration.count == 1
        assert declaration.unit == "new_decision_entries"

    def test_fallthrough_excludes_baselined_historical_entries(self, tmp_path: Path) -> None:
        _write_docs(tmp_path, _make_block(5, 200))
        failed: list[str] = []
        registry.pop_declaration()
        validate_decisions_size(failed, root=tmp_path, baseline_reader=lambda r: {5})
        declaration = registry.pop_declaration()
        assert declaration is not None
        assert declaration.kind == "examined"
        assert declaration.count == 0

    def test_new_entries_examined_count_missing_files_is_zero(self, tmp_path: Path) -> None:
        """Neither docs/DECISIONS.md nor docs/DECISIONS_ARCHIVE.md exists under tmp_path --
        mirrors _per_entry_cap_failures's own missing-files tolerance."""
        assert _new_entries_examined_count(tmp_path, baseline_numbers=set()) == 0
