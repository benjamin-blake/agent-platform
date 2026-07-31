"""Tests for scripts/decisions_index.py (DCG-08, PLAN-dcg-decisions-index -- Decision 104/131
mirror of the generator; PLAN-decision-scout-bounded-retrieval adds the `live` and
triage_excerpt_* coverage below).

Covers: build_index() determinism (byte-stable, no volatile-field leak), both-files coverage
(Decision 146), typed-edge spot-checks spanning both derivation paths (title extraction,
superseded_by inverse map, title-borne supersedes) and both files (live + archive), the
superseded_by string->int coercion, the stable-field-only projection shape, the `live` provenance
flag, and the triage_excerpt/triage_excerpt_source/triage_excerpt_truncated fallback logic.
"""

from __future__ import annotations

import json

from scripts.decisions_index import _LIVE_PATH, _build_triage_excerpt, build_index
from scripts.decisions_md import decision_header_numbers, parse_decisions_md


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
        expected_keys = {
            "number",
            "title",
            "status",
            "decided_date",
            "supersedes",
            "superseded_by",
            "amends",
            "live",
            "triage_excerpt",
            "triage_excerpt_source",
            "triage_excerpt_truncated",
        }
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


class TestLiveField:
    """VP step 1 / AC1: `live` derived from decision_header_numbers(paths=[docs/DECISIONS.md]),
    never a hardcoded count (Decision 55 test-count-coupling)."""

    def test_live_matches_file_provenance(self) -> None:
        idx = build_index()
        live_numbers = decision_header_numbers(paths=[_LIVE_PATH])
        indexed_live = {x["number"] for x in idx["decisions"] if x["live"]}
        indexed_archive = {x["number"] for x in idx["decisions"] if not x["live"]}
        assert indexed_live == live_numbers
        assert indexed_archive == {x["number"] for x in idx["decisions"]} - live_numbers

    def test_live_is_bool_not_truthy_value(self) -> None:
        idx = build_index()
        for entry in idx["decisions"]:
            assert isinstance(entry["live"], bool)

    def test_archive_only_entry_is_not_live(self) -> None:
        """dec-36 exists only in DECISIONS_ARCHIVE.md (see TestBothFilesCoverage)."""
        idx = build_index()
        d = {x["number"]: x for x in idx["decisions"]}
        assert d[36]["live"] is False


class TestTriageExcerptUnit:
    """VP step 1 / AC1: _build_triage_excerpt's fallback order (Intent -> Problem -> Context ->
    Decision), the empty-excerpt branch, the 320-char cap, and the truncation flag -- tested as
    a pure unit against synthetic rows so coverage does not depend on which real decision numbers
    happen to occupy each branch today."""

    def test_intent_wins_when_present(self) -> None:
        row = {"intent": "the intent text", "problem": "the problem text", "context": "ctx", "decision_text": "dec"}
        excerpt, source, truncated = _build_triage_excerpt(row)
        assert excerpt == "the intent text"
        assert source == "Intent"
        assert truncated is False

    def test_problem_wins_when_no_intent(self) -> None:
        row = {"intent": "", "problem": "the problem text", "context": "ctx", "decision_text": "dec"}
        excerpt, source, truncated = _build_triage_excerpt(row)
        assert excerpt == "the problem text"
        assert source == "Problem"
        assert truncated is False

    def test_context_wins_when_no_intent_or_problem(self) -> None:
        row = {"intent": "", "problem": "", "context": "the context text", "decision_text": "dec"}
        excerpt, source, truncated = _build_triage_excerpt(row)
        assert excerpt == "the context text"
        assert source == "Context"
        assert truncated is False

    def test_decision_wins_when_only_decision_text_present(self) -> None:
        row = {"intent": "", "problem": "", "context": "", "decision_text": "the decision text"}
        excerpt, source, truncated = _build_triage_excerpt(row)
        assert excerpt == "the decision text"
        assert source == "Decision"
        assert truncated is False

    def test_whitespace_only_fields_are_treated_as_empty(self) -> None:
        row = {"intent": "   \n  ", "problem": "", "context": "", "decision_text": "the decision text"}
        excerpt, source, truncated = _build_triage_excerpt(row)
        assert source == "Decision"

    def test_empty_when_no_markers_present_at_all(self) -> None:
        row = {"intent": "", "problem": "", "context": "", "decision_text": ""}
        excerpt, source, truncated = _build_triage_excerpt(row)
        assert excerpt == ""
        assert source == ""
        assert truncated is False

    def test_missing_keys_treated_as_empty(self) -> None:
        excerpt, source, truncated = _build_triage_excerpt({})
        assert excerpt == ""
        assert source == ""
        assert truncated is False

    def test_320_char_cap_not_truncated_at_exactly_320(self) -> None:
        row = {"intent": "x" * 320, "problem": "", "context": "", "decision_text": ""}
        excerpt, source, truncated = _build_triage_excerpt(row)
        assert len(excerpt) == 320
        assert truncated is False

    def test_320_char_cap_truncates_over_320(self) -> None:
        row = {"intent": "x" * 400, "problem": "", "context": "", "decision_text": ""}
        excerpt, source, truncated = _build_triage_excerpt(row)
        assert len(excerpt) == 320
        assert excerpt == "x" * 320
        assert truncated is True


class TestTriageExcerptIntegration:
    """The generator's triage_excerpt fields, checked against the real corpus via independent
    re-derivation (never a hardcoded entry count -- Decision 55 test-count-coupling)."""

    def test_every_entry_carries_the_three_fields(self) -> None:
        idx = build_index()
        for entry in idx["decisions"]:
            assert "triage_excerpt" in entry
            assert "triage_excerpt_source" in entry
            assert "triage_excerpt_truncated" in entry
            assert isinstance(entry["triage_excerpt"], str)
            assert isinstance(entry["triage_excerpt_source"], str)
            assert isinstance(entry["triage_excerpt_truncated"], bool)

    def test_no_excerpt_exceeds_320_chars(self) -> None:
        idx = build_index()
        for entry in idx["decisions"]:
            assert len(entry["triage_excerpt"]) <= 320

    def test_non_empty_excerpt_always_names_a_source(self) -> None:
        idx = build_index()
        for entry in idx["decisions"]:
            if entry["triage_excerpt"]:
                assert entry["triage_excerpt_source"] in {"Intent", "Problem", "Context", "Decision"}
            else:
                assert entry["triage_excerpt_source"] == ""

    def test_empty_excerpt_set_matches_independent_rederivation(self) -> None:
        """Re-derive the residual (no-marker) set straight from parse_decisions_md rows,
        independent of build_index()'s own excerpt logic, and cross-check equality -- not a
        hardcoded count."""
        idx = build_index()
        indexed_empty = {x["number"] for x in idx["decisions"] if not x["triage_excerpt"]}
        rows = parse_decisions_md()
        rederived_empty = {
            row["decision_id"]
            for row in rows
            if not (row.get("intent") or "").strip()
            and not (row.get("problem") or "").strip()
            and not (row.get("context") or "").strip()
            and not (row.get("decision_text") or "").strip()
        }
        assert indexed_empty == rederived_empty

    def test_excerpt_coverage_is_high(self) -> None:
        """At most 4 entries lack any quotable marker (measured 135/139 at authoring time) --
        expressed as a coverage floor, not an exact count, so new decisions don't break this."""
        idx = build_index()
        total = len(idx["decisions"])
        with_excerpt = sum(1 for x in idx["decisions"] if x["triage_excerpt"])
        assert with_excerpt >= total - 4

    def test_truncated_flag_matches_source_text_length(self) -> None:
        """Cross-check truncated against an independent re-derivation of the winning fallback
        field's raw length, never trusting the generator's own flag in isolation."""
        idx = build_index()
        rows_by_id = {row["decision_id"]: row for row in parse_decisions_md()}
        for entry in idx["decisions"]:
            if not entry["triage_excerpt_source"]:
                continue
            field_by_source = {
                "Intent": "intent",
                "Problem": "problem",
                "Context": "context",
                "Decision": "decision_text",
            }
            row_key = field_by_source[entry["triage_excerpt_source"]]
            raw = (rows_by_id[entry["number"]].get(row_key) or "").strip()
            assert entry["triage_excerpt_truncated"] == (len(raw) > 320)
            if entry["triage_excerpt_truncated"]:
                assert entry["triage_excerpt"] == raw[:320]
            else:
                assert entry["triage_excerpt"] == raw
