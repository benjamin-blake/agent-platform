"""Tests for scripts/decisions_index.py (DCG-08, PLAN-dcg-decisions-index -- Decision 104/131
mirror of the generator; PLAN-decision-scout-bounded-retrieval adds the `live`, triage_excerpt_*,
and `category_tags` coverage below).

Covers: build_index() determinism (byte-stable, no volatile-field leak), both-files coverage
(Decision 146), typed-edge spot-checks spanning both derivation paths (title extraction,
superseded_by inverse map, title-borne supersedes) and both files (live + archive), the
superseded_by string->int coercion, the stable-field-only projection shape, the `live` provenance
flag, the triage_excerpt/triage_excerpt_source/triage_excerpt_truncated fallback logic, and the
category_tags deterministic pattern-matching (the recall-gap fix from the Fable advice-consult).
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from scripts.decisions_index import (
    _EXPORT_PATH,
    _LIVE_PATH,
    _build_triage_excerpt,
    _derive_category_tags,
    build_index,
    check_index_freshness,
    main,
)
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
            "category_tags",
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


class TestCategoryTagsUnit:
    """VP-9-driven fix (Fable advice-consult): _derive_category_tags as a pure unit, independent
    of real corpus content -- covers each pattern class and the sorted/dedup/no-match shapes."""

    def test_lambda_tag_matches_lambda_mention(self) -> None:
        assert "lambda" in _derive_category_tags("Ratify per-Lambda packaging manifests", "")

    def test_terraform_tag_matches_terraform_mention(self) -> None:
        assert "terraform" in _derive_category_tags("Terraform apply routing", "")

    def test_iam_tag_matches_role_or_boundary(self) -> None:
        assert "iam" in _derive_category_tags("A new IAM role", "")
        assert "iam" in _derive_category_tags("", "extends the mandatory permissions boundary")

    def test_secrets_tag_matches_secrets_manager(self) -> None:
        assert "secrets" in _derive_category_tags("Secrets Manager split by value-capability", "")

    def test_deploy_tag_matches_deployment_noun(self) -> None:
        """Regression pin: Decision 126's title says 'deployment model', not 'deploy' -- the
        pattern must match the noun form too, not just the bare verb."""
        assert "deploy" in _derive_category_tags("Two-verb deployment model", "")

    def test_egress_tag_matches_neon_or_budget(self) -> None:
        assert "egress" in _derive_category_tags("Neon catalog egress is a first-class budget", "")

    def test_decisions_corpus_tag_matches_decisions_md(self) -> None:
        assert "decisions-corpus" in _derive_category_tags("DECISIONS.md is the canonical corpus", "")

    def test_prose_docs_tag_matches_docs_path(self) -> None:
        assert "prose-docs" in _derive_category_tags("Sanctioned-prose taxonomy", "")

    def test_no_match_returns_empty_list(self) -> None:
        assert _derive_category_tags("Some entirely unrelated title", "and an unrelated excerpt") == []

    def test_multiple_matches_are_sorted_and_deduped(self) -> None:
        tags = _derive_category_tags("Lambda Terraform Lambda deploy", "")
        assert tags == sorted(set(tags))
        assert tags.count("lambda") == 1

    def test_matches_against_excerpt_too_not_only_title(self) -> None:
        assert _derive_category_tags("Untitled", "reads a Secrets Manager credential") == ["secrets"]


class TestCategoryTagsIntegration:
    """Real-corpus regression pins for the two decisions the category_tags fix specifically
    targets (VP step 9's measured recall gap, closed via the Fable advice-consult) -- Decision
    126 ('deployment model' title, no Lambda/Terraform/IAM/Secrets keyword) and Decision 157
    ('Secrets Manager' in title) must both carry a non-empty category_tags list so decision-scout's
    mechanical shortlist step can find them without relying on per-entry judgment."""

    def test_decision_126_carries_deploy_tag(self) -> None:
        idx = build_index()
        d = {x["number"]: x for x in idx["decisions"]}
        assert "deploy" in d[126]["category_tags"]

    def test_decision_157_carries_secrets_tag(self) -> None:
        idx = build_index()
        d = {x["number"]: x for x in idx["decisions"]}
        assert "secrets" in d[157]["category_tags"]

    def test_every_entry_carries_a_list_of_strings(self) -> None:
        idx = build_index()
        for entry in idx["decisions"]:
            assert isinstance(entry["category_tags"], list)
            assert all(isinstance(t, str) for t in entry["category_tags"])

    def test_category_tags_is_sorted_and_deduped_for_every_entry(self) -> None:
        idx = build_index()
        for entry in idx["decisions"]:
            tags = entry["category_tags"]
            assert tags == sorted(set(tags)), f"dec-{entry['number']} category_tags not sorted/deduped: {tags}"

    def test_no_tag_covers_more_than_forty_percent_of_live_entries(self) -> None:
        """Keeps the shortlist materially smaller than the full corpus -- an over-broad tag would
        silently rebuild the whole-file-read cost this plan removes."""
        idx = build_index()
        live = [x for x in idx["decisions"] if x["live"]]
        from collections import Counter

        counts = Counter(tag for entry in live for tag in entry["category_tags"])
        for tag, count in counts.items():
            assert count / len(live) <= 0.40, f"tag {tag!r} covers {count}/{len(live)} live entries -- too broad"


class TestCommittedIndexSizePin:
    """AC1 / VP step 1 graduation candidate 'decisions-index-live-count-matches-file': the
    committed docs/decisions-index.json stays within a re-derived byte pin, so the figure
    recorded in the governing Decision cannot silently drift upward without review.

    RE-DERIVED (Decision 166 point 9, PLAN-size-gov-engine): the prior 110,000-byte pin
    (Decision 160 point 9) had only 236 bytes of headroom left before Decision 166's own
    entry existed -- exhausted by ordinary corpus growth, not by any defect. Decision 160
    point 9 itself named this outcome as an open question: "A future owner should reassess
    whether this indirect bound remains adequate as the corpus grows past the header
    ceiling's current runway." This is that reassessment.

    Derivation (measured on this tree, indent=2 pretty-printed bytes -- the format the
    committed file is actually written in):
      - live term:    120 (live_max_h2_headers ceiling, decision-entry.yaml) x 764 bytes/row
                       (measured: 119 live rows cost 90,857 bytes net of the {decisions,metadata}
                       wrapper = 763.5 bytes/row, rounded up) = 91,680 bytes.
      - archive term: 54 rows (2x the current 27-row archive population -- a multi-quarter
                       buffer; archival is a rare, operator-disposed event per Decision 146,
                       not a steady drip) x 726 bytes/row (measured: 27 archive rows cost
                       19,583 bytes net of wrapper = 725.3 bytes/row, rounded up) = 39,204 bytes.
      - total: 91,680 + 39,204 = 130,884 bytes, rounded up to 131,000 for measurement variance
        (unicode, trailing newline, key-order drift).

    This is a stopgap, not a permanent fix, in the Decision 145 sense -- EXCEPT that the
    named successor already exists and is dated: docs/decisions-index.json is a T1.5-INTERIM
    surface (Decision 160 point 13: "This arrangement is INTERIM, not the T1.5 portal
    cutover"). decision-scout's Phase 1 index read (its sole consumer) is scheduled for
    removal by T1.5 c1 (that item's own exit criteria: "T1.5 c1 owns swapping its bounded
    index-plus-targeted-reads mechanism for a queried tool call") once the DuckLake
    ops-decisions portal cutover lands; T1.5 itself is STRATEGIC and CD.17-frozen (AGENTS.md
    Temporary Operational Constraints), so this pin persists at least that long. rec-3012
    (filed alongside Decision 166) owns thinning archive rows to skeletons (dropping
    triage_excerpt/category_tags, which decision-scout never reads for live:false rows) --
    once landed, the archive term above shrinks and this pin has room to fall back down,
    never to be treated as a floor.

    The 120-header live_max_h2_headers ceiling (Decision 134 clause 2) is measured separately
    at 118/120 at this entry's time -- binding within roughly two more live entries regardless
    of this byte pin. This test does not relieve that ceiling; only an archival wave under
    Decision 146 does, and queuing one is out of this plan's scope (noted in
    docs/plans/PLAN-size-gov-engine.yaml Context, not actioned here).
    """

    _COMMITTED_INDEX_MAX_BYTES = 131_000

    def test_committed_index_under_re_derived_byte_pin(self) -> None:
        size = len(_EXPORT_PATH.read_bytes())
        assert size <= self._COMMITTED_INDEX_MAX_BYTES, (
            f"committed index is {size} bytes, over the {self._COMMITTED_INDEX_MAX_BYTES:,}-byte pin "
            "(Decision 166 point 9 re-derivation)"
        )


class TestCheckIndexFreshnessDirect:
    """Direct coverage of check_index_freshness() in THIS mapped test file (the coverage checker
    maps scripts/decisions_index.py -> tests/test_decisions_index.py specifically; the equivalent
    branch coverage in tests/checks/decisions/test_validate_decisions_index_freshness.py exercises
    the registered wrapper, a different module, and does not count toward this file's mapping)."""

    def test_fails_when_export_is_absent(self, tmp_path) -> None:
        missing = tmp_path / "nonexistent.json"
        with patch("scripts.decisions_index._EXPORT_PATH", missing):
            failed: list[str] = []
            check_index_freshness(failed)
        assert len(failed) == 1
        assert "missing" in failed[0].lower()

    def test_fails_when_export_is_unreadable_json(self, tmp_path) -> None:
        export_path = tmp_path / "decisions-index.json"
        export_path.write_text("not valid json {{{", encoding="utf-8")
        with patch("scripts.decisions_index._EXPORT_PATH", export_path):
            failed: list[str] = []
            check_index_freshness(failed)
        assert len(failed) == 1
        assert "cannot read" in failed[0].lower()

    def test_fails_when_export_is_stale(self, tmp_path) -> None:
        export_path = tmp_path / "decisions-index.json"
        export_path.write_text(json.dumps({"decisions": [], "metadata": {}}), encoding="utf-8")
        with patch("scripts.decisions_index._EXPORT_PATH", export_path):
            failed: list[str] = []
            check_index_freshness(failed)
        assert len(failed) == 1
        assert "stale" in failed[0].lower()

    def test_passes_when_export_is_fresh(self, tmp_path) -> None:
        export_path = tmp_path / "decisions-index.json"
        export_path.write_text(json.dumps(build_index(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        with patch("scripts.decisions_index._EXPORT_PATH", export_path):
            failed: list[str] = []
            check_index_freshness(failed)
        assert not failed


class TestMainCLI:
    """Direct coverage of main()'s argparse dispatch branches (--write / --check / --print /
    no-args), same file-mapping rationale as TestCheckIndexFreshnessDirect above."""

    def test_write_regenerates_the_export(self, tmp_path, monkeypatch) -> None:
        export_path = tmp_path / "decisions-index.json"
        monkeypatch.setattr("scripts.decisions_index._EXPORT_PATH", export_path)
        monkeypatch.setattr("sys.argv", ["decisions_index", "--write"])
        main()
        assert export_path.exists()
        assert json.loads(export_path.read_text(encoding="utf-8")) == build_index()

    def test_check_exits_zero_when_fresh(self, tmp_path, monkeypatch) -> None:
        export_path = tmp_path / "decisions-index.json"
        export_path.write_text(json.dumps(build_index(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        monkeypatch.setattr("scripts.decisions_index._EXPORT_PATH", export_path)
        monkeypatch.setattr("sys.argv", ["decisions_index", "--check"])
        main()  # does not raise SystemExit when fresh

    def test_check_exits_one_when_stale(self, tmp_path, monkeypatch) -> None:
        export_path = tmp_path / "decisions-index.json"
        export_path.write_text(json.dumps({"decisions": [], "metadata": {}}), encoding="utf-8")
        monkeypatch.setattr("scripts.decisions_index._EXPORT_PATH", export_path)
        monkeypatch.setattr("sys.argv", ["decisions_index", "--check"])
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1

    def test_print_dumps_json_to_stdout(self, monkeypatch, capsys) -> None:
        monkeypatch.setattr("sys.argv", ["decisions_index", "--print"])
        main()
        out = capsys.readouterr().out
        assert json.loads(out) == build_index()

    def test_no_args_prints_help_and_exits_one(self, monkeypatch) -> None:
        monkeypatch.setattr("sys.argv", ["decisions_index"])
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1
