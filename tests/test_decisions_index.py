"""Tests for scripts/decisions_index.py (DCG-08, PLAN-dcg-decisions-index -- Decision 104/131
mirror of the generator).

Covers: build_index() determinism (byte-stable, no volatile-field leak), both-files coverage
(Decision 146), typed-edge spot-checks spanning both derivation paths (title extraction,
superseded_by inverse map, title-borne supersedes) and both files (live + archive), the
superseded_by string->int coercion, and the stable-field-only projection shape.
"""

from __future__ import annotations

import json

from scripts.decisions_index import build_index
from scripts.decisions_md import decision_header_numbers


class TestDeterminism:
    """VP step 1: two consecutive build_index() calls must be byte-identical."""

    def test_build_index_is_byte_stable_across_two_calls(self) -> None:
        first = json.dumps(build_index(), sort_keys=True)
        second = json.dumps(build_index(), sort_keys=True)
        assert first == second

    def test_build_index_excludes_volatile_parser_fields(self) -> None:
        """No created_timestamp/last_updated_timestamp/content_hash/raw_block leak into any
        entry -- these are exactly the fields that would break determinism (a fresh
        now_iso timestamp on every parse_decisions_md() call)."""
        idx = build_index()
        volatile = {"created_timestamp", "last_updated_timestamp", "content_hash", "raw_block"}
        for entry in idx["decisions"]:
            assert not (volatile & entry.keys()), f"dec-{entry['number']} leaked volatile field(s): {volatile & entry.keys()}"

    def test_entry_shape_is_the_stable_projection_only(self) -> None:
        idx = build_index()
        expected_keys = {"number", "title", "status", "decided_date", "supersedes", "superseded_by", "amends"}
        for entry in idx["decisions"]:
            assert set(entry.keys()) == expected_keys


class TestBothFilesCoverage:
    """VP step 2 / Decision 146: entry set == the shared parser's header set across BOTH
    docs/DECISIONS.md and docs/DECISIONS_ARCHIVE.md -- derived, never hardcoded (Decision 55
    test-count-coupling)."""

    def test_covers_all_headers_both_files(self) -> None:
        idx = build_index()
        numbers = {entry["number"] for entry in idx["decisions"]}
        assert numbers == decision_header_numbers()

    def test_decisions_list_is_sorted_by_number(self) -> None:
        idx = build_index()
        numbers = [entry["number"] for entry in idx["decisions"]]
        assert numbers == sorted(numbers)

    def test_archive_only_entry_present(self) -> None:
        """dec-36 exists only in DECISIONS_ARCHIVE.md (tests/test_decisions_md.py's own
        archive-coverage anchor) -- proves the index covers the archive file too."""
        idx = build_index()
        numbers = {entry["number"] for entry in idx["decisions"]}
        assert 36 in numbers


class TestTypedEdgeSpotChecks:
    """VP step 3: edges spanning both derivation paths (title extraction, superseded_by
    inverse map, title-borne supersedes) and both files (live + archive)."""

    def test_dec150_amends_105_title_extraction(self) -> None:
        idx = build_index()
        d = {x["number"]: x for x in idx["decisions"]}
        assert 105 in d[150]["amends"]

    def test_dec143_amends_81_title_extraction_with_clause_suffix(self) -> None:
        idx = build_index()
        d = {x["number"]: x for x in idx["decisions"]}
        assert 81 in d[143]["amends"]

    def test_dec144_amends_both_98_and_92_multi_target(self) -> None:
        idx = build_index()
        d = {x["number"]: x for x in idx["decisions"]}
        assert d[144]["amends"] == [92, 98]

    def test_dec90_supersedes_dec42_live_to_archive_inverse(self) -> None:
        """42 lives in DECISIONS_ARCHIVE.md; its superseded_by inverts onto live dec-90."""
        idx = build_index()
        d = {x["number"]: x for x in idx["decisions"]}
        assert 42 in d[90]["supersedes"]

    def test_dec69_superseded_by_78_and_inverse_symmetry(self) -> None:
        idx = build_index()
        d = {x["number"]: x for x in idx["decisions"]}
        assert d[69]["superseded_by"] == 78
        assert 69 in d[78]["supersedes"]

    def test_dec117_supersedes_44_title_and_inverse_agree(self) -> None:
        """Both derivation paths agree here: 117's title says 'Supersedes Decision 44' AND
        44's body carries '**Superseded by: Decision 117**' -- the union produces one edge,
        not a duplicate, and the REVERSE edge (44 supersedes 117) must NOT appear."""
        idx = build_index()
        d = {x["number"]: x for x in idx["decisions"]}
        assert d[117]["supersedes"] == [44]
        assert d[44]["supersedes"] == []
        assert d[44]["superseded_by"] == 117

    def test_dec52_title_borne_supersedes_multi_target_plural_form(self) -> None:
        """Decision 52's title 'Supersedes Decisions 37, 40, 49' -- the plural/comma
        title-borne form, direction n->target (52 supersedes each, not the reverse)."""
        idx = build_index()
        d = {x["number"]: x for x in idx["decisions"]}
        assert d[52]["supersedes"] == [37, 40, 49]
        assert 52 not in d[37]["supersedes"]


class TestSupersededByCoercion:
    """superseded_by is coerced from the parser's 'dec-NNN' string to a bare int, or None."""

    def test_superseded_by_is_int_not_string(self) -> None:
        idx = build_index()
        d = {x["number"]: x for x in idx["decisions"]}
        assert d[69]["superseded_by"] == 78
        assert isinstance(d[69]["superseded_by"], int)

    def test_superseded_by_is_none_when_never_superseded(self) -> None:
        idx = build_index()
        d = {x["number"]: x for x in idx["decisions"]}
        assert d[150]["superseded_by"] is None
