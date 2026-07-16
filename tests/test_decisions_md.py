"""Tests for scripts/decisions_md.py (PLAN-daf-etl-parity-fidelity, Decision 134 cl.4 / DAF-01).

Covers the DAF-01 parity-fidelity acceptance assertions: decorated-Decision-marker
tolerance, reversal_conditions extraction, the ISO-only decided_date fallback guard,
raw_block/content_hash presence, plural-cite parsing + dedupe, per-file byte-reconstruction
coverage (with a synthetic sectioner-narrowing mutation proving the assertion is live, not
vacuous), archive coverage, and dual schema-model field sync (DecisionPayload / jsonl_store.
Decision both carry the four new fields as plain, non-Dq-Annotated optional strings).
"""

from __future__ import annotations

import re
import typing
from pathlib import Path

import pytest

from scripts.decisions_md import (
    _DECISIONS_MD_PATHS,
    _extract_decided_date,
    _extract_related_decisions,
    _extract_section,
    _iter_decision_sections,
    parse_decisions_md,
    read_jsonl,
)


@pytest.fixture(scope="module")
def parsed_rows() -> dict[int, dict]:
    return {r["decision_id"]: r for r in parse_decisions_md()}


class TestParityAnchors:
    """The DAF-01 acceptance assertions named in the plan and the audit."""

    def test_parity_anchors_dec084_decision_text_non_empty(self, parsed_rows: dict[int, dict]) -> None:
        """Decorated marker '**Decision (four invariants):**' must not yield an empty body."""
        assert parsed_rows[84]["decision_text"]

    def test_parity_anchors_dec114_reversal_conditions_present(self, parsed_rows: dict[int, dict]) -> None:
        assert parsed_rows[114]["reversal_conditions"]

    def test_parity_anchors_dec067_decided_date_empty_or_iso(self, parsed_rows: dict[int, dict]) -> None:
        """The Status-suffix fallback must not harvest a non-date clause as a date."""
        decided_date = parsed_rows[67]["decided_date"]
        assert decided_date == "" or decided_date[:4].isdigit()

    def test_parity_anchors_raw_block_and_content_hash_present_for_every_entry(self, parsed_rows: dict[int, dict]) -> None:
        assert parsed_rows, "expected at least one parsed decision entry"
        for decision_id, row in parsed_rows.items():
            assert row["raw_block"], f"dec-{decision_id:03d} has an empty raw_block"
            content_hash = row["content_hash"]
            assert len(content_hash) == 64, f"dec-{decision_id:03d} content_hash is not 64 chars"
            assert re.fullmatch(r"[0-9a-f]{64}", content_hash), f"dec-{decision_id:03d} content_hash is not hex"


class TestPluralCiteParsing:
    """DAF-01: 'Decisions 69/78' plural cites were previously invisible to the parser."""

    def test_plural_cite_slash_form_parsed_and_deduped(self) -> None:
        text = (
            "**Related:** Decision 84 (...), Decisions 69/78 (Single-Portal Invariant), Decision 70 (...), Decision 70 (dup)."
        )
        assert _extract_related_decisions(text) == [84, 69, 78, 70]

    def test_plural_cite_comma_form_parsed(self) -> None:
        text = "**Related:** Decisions 24, 73 (two-tier CI)."
        assert _extract_related_decisions(text) == [24, 73]

    def test_plural_cite_dec087_related_includes_both_numbers_deduped(self, parsed_rows: dict[int, dict]) -> None:
        """Decision 87's Related line cites 'Decisions 69/78' -- both must parse, deduped."""
        related = parsed_rows[87]["related_decisions"]
        assert 69 in related
        assert 78 in related
        assert related.count(70) == 1


class TestArchiveCoverage:
    """Confirms docs/DECISIONS_ARCHIVE.md is covered identically to the live file."""

    def test_archive_only_entry_dec036_present_with_raw_block_and_hash(self, parsed_rows: dict[int, dict]) -> None:
        """dec-36 exists only in DECISIONS_ARCHIVE.md -- proves archive coverage is wired."""
        assert 36 in parsed_rows
        assert parsed_rows[36]["raw_block"]
        assert len(parsed_rows[36]["content_hash"]) == 64

    def test_archive_and_live_paths_both_configured(self) -> None:
        names = {p.name for p in _DECISIONS_MD_PATHS}
        assert names == {"DECISIONS.md", "DECISIONS_ARCHIVE.md"}


class TestByteReconstruction:
    """Per-file coverage: preamble + concatenated heading-inclusive raw_blocks == source file."""

    @pytest.mark.parametrize("md_path", _DECISIONS_MD_PATHS, ids=lambda p: p.name)
    def test_byte_reconstruction_reconstructs_source_file_exactly(self, md_path: Path) -> None:
        content = md_path.read_text(encoding="utf-8", errors="replace")
        sections = _iter_decision_sections(content)
        assert sections, f"{md_path} produced no decision sections"
        preamble = content[: sections[0][0].start()]
        reconstructed = preamble + "".join(raw_block for _, raw_block in sections)
        assert reconstructed == content

    def test_byte_reconstruction_synthetic_sectioner_narrowing_mutation_fails(self) -> None:
        """Proves the reconstruction check is a live invariant, not vacuously true.

        A sectioner that silently narrows a raw_block (drops trailing bytes) must fail the
        same byte-equality assertion the real coverage test above relies on -- otherwise
        future drift in the sectioning boundaries would fail silently, not loudly.
        """
        fixture = (
            "# Preamble text\n\n"
            "## Decision 1: First (Decided)\n\nBody one.\n\n---\n\n"
            "## Decision 2: Second (Decided)\n\nBody two.\n"
        )
        sections = _iter_decision_sections(fixture)
        assert len(sections) == 2
        preamble = fixture[: sections[0][0].start()]

        good_reconstruction = preamble + "".join(rb for _, rb in sections)
        assert good_reconstruction == fixture

        # Simulate a sectioner bug: narrow the first raw_block by dropping trailing bytes.
        narrowed_sections = [(sections[0][0], sections[0][1][:-5]), sections[1]]
        bad_reconstruction = preamble + "".join(rb for _, rb in narrowed_sections)
        assert bad_reconstruction != fixture


class TestDualModelFieldSync:
    """DecisionPayload (write-side) and jsonl_store.Decision (read-side) must both carry
    the four DAF-01 fields, as plain (non-Dq-Annotated) optional strings, with the
    dual-write invariant preserved.
    """

    _NEW_FIELDS = ("raw_block", "reversal_conditions", "superseded_by", "content_hash")

    def test_dual_model_both_declare_the_four_fields(self) -> None:
        from scripts.executor.jsonl_store import Decision
        from src.schemas.decision import DecisionPayload

        for field in self._NEW_FIELDS:
            assert field in DecisionPayload.model_fields, f"DecisionPayload missing {field}"
            assert field in Decision.model_fields, f"jsonl_store.Decision missing {field}"

    def test_dual_model_fields_are_plain_not_annotated(self) -> None:
        """Never Annotated[...]/DqNotNull -- would redden validate_pydantic_yaml_drift."""
        from src.schemas.decision import DecisionPayload

        hints = typing.get_type_hints(DecisionPayload, include_extras=True)
        for field in self._NEW_FIELDS:
            assert typing.get_origin(hints[field]) is not typing.Annotated, (
                f"DecisionPayload.{field} must be a plain str | None, not Annotated[...]"
            )

    def test_dual_model_record_validates_on_both_and_dual_write_invariant_holds(self) -> None:
        from scripts.executor.jsonl_store import Decision
        from src.schemas.decision import DecisionPayload

        record = {
            "id": "dec-999",
            "decision_id": 999,
            "title": "Synthetic test decision",
            "status": "Decided",
            "created_timestamp": "2026-07-16T00:00:00Z",
            "last_updated_timestamp": "2026-07-16T00:00:00Z",
            "raw_block": "## Decision 999: Synthetic test decision (Decided)\n\n**Decision:** test.",
            "reversal_conditions": "revisit if X changes",
            "superseded_by": "dec-998",
            "content_hash": "a" * 64,
        }
        payload = DecisionPayload.model_validate(record)
        read_side = Decision.model_validate(record)
        assert payload.raw_block == read_side.raw_block == record["raw_block"]
        assert payload.reversal_conditions == read_side.reversal_conditions == record["reversal_conditions"]
        assert payload.superseded_by == read_side.superseded_by == record["superseded_by"]
        assert payload.content_hash == read_side.content_hash == record["content_hash"]

        mismatched = {**record, "decision_id": 998}
        with pytest.raises(Exception, match="Dual-write invariant"):
            DecisionPayload.model_validate(mismatched)
        with pytest.raises(Exception, match="Dual-write invariant"):
            Decision.model_validate(mismatched)


class TestExtractSectionHelper:
    """_extract_section is a pre-existing single-line extraction helper (unused elsewhere in
    the codebase currently, but retained public surface); covered directly for completeness."""

    def test_extract_section_returns_matched_value(self) -> None:
        text = "**Foo:** bar baz\n\n**Next:** ignored"
        assert _extract_section(text, "Foo") == "bar baz"

    def test_extract_section_returns_empty_when_no_key_matches(self) -> None:
        assert _extract_section("no markers here", "Missing") == ""


class TestDecidedDateIsoFallback:
    """The Status-suffix fallback in _extract_decided_date (DAF-01 ISO guard)."""

    def test_status_suffix_fallback_accepts_iso_shaped_value(self) -> None:
        text = "**Status:** Decided -- 2026-04-01"
        assert _extract_decided_date(text) == "2026-04-01"

    def test_status_suffix_fallback_rejects_non_iso_value(self) -> None:
        text = "**Status:** Active -- remove when reversal condition is met"
        assert _extract_decided_date(text) == ""


class TestParseDecisionsMdMissingFile:
    def test_parse_decisions_md_skips_nonexistent_path(self, tmp_path: Path) -> None:
        missing = tmp_path / "does-not-exist.md"
        assert parse_decisions_md(paths=[missing]) == []


class TestReadJsonl:
    """read_jsonl -- a pre-existing local-JSONL reader retained on this module."""

    def test_read_jsonl_parses_valid_entries_and_skips_blanks_and_comments(self, tmp_path: Path) -> None:
        path = tmp_path / "sample.jsonl"
        path.write_text('# a comment\n\n{"id": "dec-001"}\n{"id": "dec-002"}\n', encoding="utf-8")
        assert read_jsonl(path) == [{"id": "dec-001"}, {"id": "dec-002"}]

    def test_read_jsonl_missing_file_returns_empty_list(self, tmp_path: Path) -> None:
        missing = tmp_path / "missing.jsonl"
        assert read_jsonl(missing) == []

    def test_read_jsonl_skips_malformed_json_line(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.jsonl"
        path.write_text('{"id": "dec-001"}\nnot json\n{"id": "dec-002"}\n', encoding="utf-8")
        assert read_jsonl(path) == [{"id": "dec-001"}, {"id": "dec-002"}]

    def test_read_jsonl_skips_schema_comment_line(self, tmp_path: Path) -> None:
        path = tmp_path / "schema.jsonl"
        path.write_text('{"_schema": "v1"}\n{"id": "dec-001"}\n', encoding="utf-8")
        assert read_jsonl(path) == [{"id": "dec-001"}]
