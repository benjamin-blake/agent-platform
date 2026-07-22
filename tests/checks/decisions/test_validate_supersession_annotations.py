"""Tests for validate_supersession_annotations(). Mirror of
scripts/checks/decisions/validate_supersession_annotations.py (DPI-01/DPI-06/DPI-03-ext,
PLAN-decisions-supersession-guard). Synthetic tmp_path fixtures exercise every branch; a
non-vacuity class at the bottom runs the pure extractor and the full entrypoint against the REAL
repo files, asserting > 0 edges without asserting an absolute count (test-count-coupling
anti-pattern, validate_test_count_coupling)."""

from __future__ import annotations

from pathlib import Path

import yaml

from scripts.checks.decisions.validate_supersession_annotations import (
    extract_supersession_edges,
    validate_supersession_annotations,
)
from scripts.decisions_md import parse_decisions_md

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _write_decisions(root: Path, live: str = "", archive: str | None = "") -> None:
    """Write docs/DECISIONS.md (always) and docs/DECISIONS_ARCHIVE.md (unless archive is None,
    which omits the file entirely -- the missing-file coverage case)."""
    docs_dir = root / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    (docs_dir / "DECISIONS.md").write_text(live, encoding="utf-8")
    if archive is not None:
        (docs_dir / "DECISIONS_ARCHIVE.md").write_text(archive, encoding="utf-8")


def _write_waivers(
    root: Path,
    waivers: list[dict] | None = None,
    live_archive_pair_allowlist: list[int] | None = None,
    raw_text: str | None = None,
) -> None:
    config_dir = root / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    path = config_dir / "decision_supersession_waivers.yaml"
    if raw_text is not None:
        path.write_text(raw_text, encoding="utf-8")
        return
    data = {"waivers": waivers or [], "live_archive_pair_allowlist": live_archive_pair_allowlist or []}
    path.write_text(yaml.safe_dump(data), encoding="utf-8")


class TestExtractSupersessionEdges:
    def test_extracts_superseder_victim_file_triple(self, tmp_path: Path) -> None:
        _write_decisions(
            tmp_path,
            live="## Decision 2: New (Decided)\n\n**Decision:** Supersedes Decision 1.\n\n---\n\n"
            "## Decision 1: Old (Decided)\n\n**Status:** Superseded\n",
        )
        edges = extract_supersession_edges(tmp_path)
        assert edges == [(2, 1, "docs/DECISIONS.md")]

    def test_self_reference_is_skipped(self, tmp_path: Path) -> None:
        _write_decisions(
            tmp_path,
            live="## Decision 9: Self-citing (Decided)\n\n**Decision:** amends Decision 9 point 1.\n",
        )
        edges = extract_supersession_edges(tmp_path)
        assert edges == []

    def test_repeated_mention_within_one_block_is_deduped(self, tmp_path: Path) -> None:
        """A header parenthetical AND body prose both saying 'amends Decision N' for the SAME
        edge must count once, not twice (avoids double-counting/duplicate FAIL lines)."""
        _write_decisions(
            tmp_path,
            live="## Decision 5: Something (amends Decision 3 clause 2) (Decided)\n\n"
            "**Decision:** This amends Decision 3 clause 2 as described above.\n",
        )
        edges = extract_supersession_edges(tmp_path)
        assert edges == [(5, 3, "docs/DECISIONS.md")]

    def test_missing_archive_file_is_tolerated(self, tmp_path: Path) -> None:
        _write_decisions(
            tmp_path,
            live="## Decision 2: New (Decided)\n\n**Decision:** Supersedes Decision 1.\n",
            archive=None,
        )
        edges = extract_supersession_edges(tmp_path)
        assert edges == [(2, 1, "docs/DECISIONS.md")]

    def test_missing_archive_file_is_tolerated_end_to_end(self, tmp_path: Path) -> None:
        """Exercises the same missing-archive tolerance through the full entrypoint, so every
        helper that independently loops over (LIVE, ARCHIVE) -- not just the pure extractor --
        takes its missing-file branch."""
        _write_decisions(
            tmp_path,
            live="## Decision 2: New (Decided)\n\n**Decision:** Supersedes Decision 1.\n\n---\n\n"
            "## Decision 1: Old (Decided)\n\n**Status:** Superseded by Decision 2.\n\n"
            "**Warehouse ID:** dec-001\n",
            archive=None,
        )
        _write_waivers(tmp_path)
        failed: list[str] = []
        validate_supersession_annotations(failed, root=tmp_path)
        assert failed == []


class TestSupersessionAnnotationSubCheck:
    def test_unannotated_full_supersession_fails(self, tmp_path: Path) -> None:
        _write_decisions(
            tmp_path,
            live="## Decision 2: New (Decided)\n\n**Decision:** Supersedes Decision 1.\n\n---\n\n"
            "## Decision 1: Old (Decided)\n\n**Status:** Superseded\n\n**Decision:** No back-pointer here.\n",
        )
        _write_waivers(tmp_path)
        failed: list[str] = []
        validate_supersession_annotations(failed, root=tmp_path)
        assert failed == ["Decision supersession-annotation guard"]

    def test_plain_decision_mention_annotates(self, tmp_path: Path) -> None:
        _write_decisions(
            tmp_path,
            live="## Decision 2: New (Decided)\n\n**Decision:** Supersedes Decision 1.\n\n---\n\n"
            "## Decision 1: Old (Decided)\n\n**Status:** Superseded by Decision 2, see its rationale.\n",
        )
        _write_waivers(tmp_path)
        failed: list[str] = []
        validate_supersession_annotations(failed, root=tmp_path)
        assert failed == []

    def test_superseded_by_header_annotates(self, tmp_path: Path) -> None:
        _write_decisions(
            tmp_path,
            live="## Decision 2: New (Decided)\n\n**Decision:** Supersedes Decision 1.\n\n---\n\n"
            "## Decision 1: Old (Superseded by Decision 2) (Decided)\n\n**Status:** Superseded\n",
        )
        _write_waivers(tmp_path)
        failed: list[str] = []
        validate_supersession_annotations(failed, root=tmp_path)
        assert failed == []

    def test_mismatched_superseded_by_header_does_not_annotate(self, tmp_path: Path) -> None:
        """A '(Superseded by Decision N)' header pointing at a DIFFERENT decision than the real
        superseder must not satisfy the annotation test (proves the number comparison, not just
        pattern presence, is load-bearing)."""
        _write_decisions(
            tmp_path,
            live="## Decision 2: New (Decided)\n\n**Decision:** Supersedes Decision 1.\n\n---\n\n"
            "## Decision 1: Old (Superseded by Decision 99) (Decided)\n\n**Status:** Superseded\n",
        )
        _write_waivers(tmp_path)
        failed: list[str] = []
        validate_supersession_annotations(failed, root=tmp_path)
        assert failed == ["Decision supersession-annotation guard"]

    def test_waived_edge_passes(self, tmp_path: Path) -> None:
        _write_decisions(
            tmp_path,
            live="## Decision 2: New (Decided)\n\n**Decision:** Supersedes Decision 1.\n\n---\n\n"
            "## Decision 1: Old (Decided)\n\n**Status:** Superseded\n\n**Decision:** No back-pointer here.\n",
        )
        _write_waivers(tmp_path, waivers=[{"superseder": 2, "victim": 1, "reason": "test waiver"}])
        failed: list[str] = []
        validate_supersession_annotations(failed, root=tmp_path)
        assert failed == []

    def test_stale_waiver_warns_but_does_not_fail(self, tmp_path: Path, capsys) -> None:
        """A waived edge whose victim IS now annotated is a WARN (stale waiver), never a FAIL."""
        _write_decisions(
            tmp_path,
            live="## Decision 2: New (Decided)\n\n**Decision:** Supersedes Decision 1.\n\n---\n\n"
            "## Decision 1: Old (Decided)\n\n**Status:** Superseded by Decision 2.\n",
        )
        _write_waivers(tmp_path, waivers=[{"superseder": 2, "victim": 1, "reason": "now-stale waiver"}])
        failed: list[str] = []
        validate_supersession_annotations(failed, root=tmp_path)
        assert failed == []
        assert "stale" in capsys.readouterr().out.lower()


class TestDuplicateNumberSubCheck:
    def test_live_file_duplicate_number_fails(self, tmp_path: Path) -> None:
        _write_decisions(
            tmp_path,
            live="## Decision 1: First (Decided)\n\n**Status:** Decided\n\n---\n\n"
            "## Decision 1: Duplicate (Decided)\n\n**Status:** Decided\n",
        )
        _write_waivers(tmp_path)
        failed: list[str] = []
        validate_supersession_annotations(failed, root=tmp_path)
        assert failed == ["Decision supersession-annotation guard"]

    def test_live_archive_pair_warns_when_not_allowlisted(self, tmp_path: Path, capsys) -> None:
        _write_decisions(
            tmp_path,
            live="## Decision 7: Live copy (Decided)\n\n**Status:** Decided\n",
            archive="## Decision 7: Archive copy (Decided)\n\n**Status:** Decided\n",
        )
        _write_waivers(tmp_path)
        failed: list[str] = []
        validate_supersession_annotations(failed, root=tmp_path)
        assert failed == []
        out = capsys.readouterr().out
        assert "WARN" in out and "Decision 7" in out

    def test_live_archive_pair_silenced_by_allowlist(self, tmp_path: Path, capsys) -> None:
        _write_decisions(
            tmp_path,
            live="## Decision 7: Live copy (Decided)\n\n**Status:** Decided\n",
            archive="## Decision 7: Archive copy (Decided)\n\n**Status:** Decided\n",
        )
        _write_waivers(tmp_path, live_archive_pair_allowlist=[7])
        failed: list[str] = []
        validate_supersession_annotations(failed, root=tmp_path)
        assert failed == []
        assert "Decision 7" not in capsys.readouterr().out


class TestWarehouseIdSubCheck:
    def test_conforming_warehouse_id_passes(self, tmp_path: Path) -> None:
        _write_decisions(
            tmp_path,
            live="## Decision 12: Something (Decided)\n\n**Status:** Decided\n\n**Warehouse ID:** dec-012\n",
        )
        _write_waivers(tmp_path)
        failed: list[str] = []
        validate_supersession_annotations(failed, root=tmp_path)
        assert failed == []

    def test_nonconforming_warehouse_id_fails(self, tmp_path: Path) -> None:
        _write_decisions(
            tmp_path,
            live="## Decision 12: Something (Decided)\n\n**Status:** Decided\n\n**Warehouse ID:** dec-099\n",
        )
        _write_waivers(tmp_path)
        failed: list[str] = []
        validate_supersession_annotations(failed, root=tmp_path)
        assert failed == ["Decision supersession-annotation guard"]

    def test_block_without_warehouse_id_is_skipped(self, tmp_path: Path) -> None:
        _write_decisions(tmp_path, live="## Decision 12: Something (Decided)\n\n**Status:** Decided\n")
        _write_waivers(tmp_path)
        failed: list[str] = []
        validate_supersession_annotations(failed, root=tmp_path)
        assert failed == []


class TestWaiverFileLoading:
    def test_missing_waivers_file_fails(self, tmp_path: Path) -> None:
        _write_decisions(tmp_path, live="## Decision 1: Something (Decided)\n\n**Status:** Decided\n")
        failed: list[str] = []
        validate_supersession_annotations(failed, root=tmp_path)
        assert len(failed) == 1
        assert "decision_supersession_waivers.yaml" in failed[0]

    def test_malformed_yaml_fails(self, tmp_path: Path) -> None:
        _write_decisions(tmp_path, live="## Decision 1: Something (Decided)\n\n**Status:** Decided\n")
        _write_waivers(tmp_path, raw_text="waivers: [unterminated\n")
        failed: list[str] = []
        validate_supersession_annotations(failed, root=tmp_path)
        assert len(failed) == 1
        assert "decision_supersession_waivers.yaml" in failed[0]

    def test_non_dict_top_level_fails(self, tmp_path: Path) -> None:
        _write_decisions(tmp_path, live="## Decision 1: Something (Decided)\n\n**Status:** Decided\n")
        _write_waivers(tmp_path, raw_text="- just\n- a\n- list\n")
        failed: list[str] = []
        validate_supersession_annotations(failed, root=tmp_path)
        assert len(failed) == 1
        assert "decision_supersession_waivers.yaml" in failed[0]

    def test_empty_waivers_file_treated_as_no_waivers(self, tmp_path: Path) -> None:
        _write_decisions(tmp_path, live="## Decision 1: Something (Decided)\n\n**Status:** Decided\n")
        _write_waivers(tmp_path, raw_text="")
        failed: list[str] = []
        validate_supersession_annotations(failed, root=tmp_path)
        assert failed == []


class TestFullEntrypointIntegration:
    def test_fully_green_fixture_prints_pass(self, tmp_path: Path, capsys) -> None:
        _write_decisions(
            tmp_path,
            live="## Decision 2: New (Decided)\n\n**Decision:** Supersedes Decision 1.\n\n---\n\n"
            "## Decision 1: Old (Decided)\n\n**Status:** Superseded by Decision 2.\n",
        )
        _write_waivers(tmp_path)
        failed: list[str] = []
        validate_supersession_annotations(failed, root=tmp_path)
        assert failed == []
        assert "PASS:" in capsys.readouterr().out


class TestNonVacuityRealRepo:
    """Runs the pure extractor and the full entrypoint against the REAL repo files. Asserts
    non-vacuity (> 0) only -- never an absolute count (test-count-coupling anti-pattern); the
    corpus grows over time as new Decisions are authored."""

    def test_extractor_enumerates_a_positive_edge_count(self) -> None:
        edges = extract_supersession_edges(_REPO_ROOT)
        assert len(edges) > 0

    def test_real_repo_guard_is_green(self) -> None:
        failed: list[str] = []
        validate_supersession_annotations(failed, root=_REPO_ROOT)
        assert failed == []

    def test_default_root_resolves_to_common_root(self) -> None:
        """Calling with no root= argument at all exercises the _common.ROOT default (the real
        entrypoint signature used by scripts/validate.py's dispatch)."""
        failed: list[str] = []
        validate_supersession_annotations(failed)
        assert failed == []


class TestDecisionsMdDedupWarning:
    """parse_decisions_md's first-wins dedup site (scripts/decisions_md.py) emits a stderr
    WARNING naming the dropped decision number whenever it discards a duplicate -- the returned
    parse result is unchanged (behavior-preserving edit)."""

    def test_duplicate_decision_number_emits_stderr_warning(self, tmp_path: Path, capsys) -> None:
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir(parents=True)
        decisions_path = docs_dir / "DECISIONS.md"
        decisions_path.write_text(
            "## Decision 1: First (Decided)\n\n**Status:** Decided\n\n---\n\n"
            "## Decision 1: Duplicate (Decided)\n\n**Status:** Decided\n",
            encoding="utf-8",
        )
        result = parse_decisions_md(paths=[decisions_path])
        err = capsys.readouterr().err
        assert "WARNING" in err
        assert "duplicate decision number 1" in err
        assert "DECISIONS.md" in err
        # Behavior-preserving: still exactly one (first-parsed) entry for decision 1.
        assert len(result) == 1
        assert result[0]["title"] == "First"

    def test_no_duplicate_emits_no_warning(self, tmp_path: Path, capsys) -> None:
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir(parents=True)
        decisions_path = docs_dir / "DECISIONS.md"
        decisions_path.write_text("## Decision 1: Only one (Decided)\n\n**Status:** Decided\n", encoding="utf-8")
        parse_decisions_md(paths=[decisions_path])
        assert capsys.readouterr().err == ""
