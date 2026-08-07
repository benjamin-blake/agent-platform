"""Contract-derived property tests for the decision-corpus field grammar (CFG-06 class fix,
audits/contract-first-governance-33c8667.yaml; PLAN-decision-extractor-grammar-fixes).

Every accepted/rejected form and both terminator regexes are DECLARED in
docs/contracts/decision-entry.yaml's field_grammar section and loaded here, not hardcoded --
so a future divergence between the contract and scripts/decisions_md.py's actual behaviour fails
this suite instead of silently corrupting the ops_decisions related_decisions column or the
docs/decisions-index.json amends column.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from scripts.decisions_md import (
    _MARKER_SECTION_TERMINATOR,
    _TYPED_ID_LIST_TERMINATOR,
    _extract_multiline_section,
    _extract_related_decisions,
    extract_amends_edges,
    parse_decisions_md,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_CONTRACT_PATH = _REPO_ROOT / "docs" / "contracts" / "decision-entry.yaml"
_CONTRACT: dict[str, Any] = yaml.safe_load(_CONTRACT_PATH.read_text(encoding="utf-8"))
_FIELD_GRAMMAR: dict[str, Any] = _CONTRACT["field_grammar"]

_TITLE_RELATION = _FIELD_GRAMMAR["title_relation_continuation"]
_ACCEPTED_TITLE_FORMS: list[dict[str, Any]] = _TITLE_RELATION["accepted_forms"]
_REJECTED_TITLE_FORMS: list[dict[str, Any]] = _TITLE_RELATION["rejected_forms"]

_TYPED_ID_LIST = _FIELD_GRAMMAR["typed_id_list_terminator"]
_ACCEPTED_ID_LIST_FORMS: list[dict[str, Any]] = _TYPED_ID_LIST["accepted_forms"]
_REJECTED_ID_LIST_FORMS: list[dict[str, Any]] = _TYPED_ID_LIST["rejected_forms"]


class TestTitleRelationContinuationContractDerived:
    """extract_amends_edges() honours every accepted/rejected continuation form
    decision-entry.yaml's field_grammar.title_relation_continuation declares."""

    @pytest.mark.parametrize("case", _ACCEPTED_TITLE_FORMS, ids=[c["example"] for c in _ACCEPTED_TITLE_FORMS])
    def test_accepted_form_parses(self, case: dict[str, Any]) -> None:
        assert extract_amends_edges(case["example"]) == case["expected"]

    @pytest.mark.parametrize("case", _REJECTED_TITLE_FORMS, ids=[c["example"] for c in _REJECTED_TITLE_FORMS])
    def test_rejected_form_rejects(self, case: dict[str, Any]) -> None:
        assert extract_amends_edges(case["example"]) == case["expected"]


class TestTypedIdListTerminatorContractDerived:
    """_extract_related_decisions() honours every accepted/rejected form
    decision-entry.yaml's field_grammar.typed_id_list_terminator declares."""

    @pytest.mark.parametrize("case", _ACCEPTED_ID_LIST_FORMS, ids=[c["example"][:40] for c in _ACCEPTED_ID_LIST_FORMS])
    def test_accepted_form_parses(self, case: dict[str, Any]) -> None:
        assert _extract_related_decisions(case["example"]) == case["expected"]

    @pytest.mark.parametrize("case", _REJECTED_ID_LIST_FORMS, ids=[c["example"][:40] for c in _REJECTED_ID_LIST_FORMS])
    def test_rejected_form_rejects(self, case: dict[str, Any]) -> None:
        assert _extract_related_decisions(case["example"]) == case["expected"]


class TestTerminatorConstantToContractPin:
    """The module's terminator constants must equal the exact regex decision-entry.yaml states
    -- a divergence here is exactly the contract-vs-code drift class CFG-06 exists to close."""

    def test_marker_section_terminator_matches_contract(self) -> None:
        assert _MARKER_SECTION_TERMINATOR == _FIELD_GRAMMAR["prose_terminator"]["regex"]

    def test_typed_id_list_terminator_matches_contract(self) -> None:
        assert _TYPED_ID_LIST_TERMINATOR == _FIELD_GRAMMAR["typed_id_list_terminator"]["regex"]


class TestCrossRuleAgreement:
    """The production _TYPED_ID_LIST_TERMINATOR must agree, on the whole live+archive corpus,
    with an INDEPENDENTLY implemented paragraph-break rule ("\\n\\n"). This is the property that
    catches an unlisted future annotation spelling a hard-coded opener enumeration cannot -- it
    is what would have caught rows 89/105 and 60/62/68/71 at CFG-06 planning time.
    """

    _ALT_RELATED_RE = re.compile(r"\*\*Related:\*\*(.+?)(?=\n\n|\Z)", re.DOTALL)

    @classmethod
    def _alt_related_decisions(cls, text: str) -> list[int]:
        m = cls._ALT_RELATED_RE.search(text)
        if not m:
            return []
        related_text = m.group(1)
        seen: set[int] = set()
        result: list[int] = []
        for cite in re.finditer(r"Decisions?\s+(\d+(?:\s*[/,]\s*\d+)*)", related_text):
            for n_str in re.findall(r"\d+", cite.group(1)):
                n = int(n_str)
                if n not in seen:
                    seen.add(n)
                    result.append(n)
        return result

    def test_production_terminator_agrees_with_independent_paragraph_break_rule(self) -> None:
        rows = parse_decisions_md()
        mismatches = {}
        for row in rows:
            alt = self._alt_related_decisions(row["raw_block"])
            if alt != row["related_decisions"]:
                mismatches[row["decision_id"]] = (row["related_decisions"], alt)
        assert not mismatches, mismatches


def test_intent_retains_dated_in_section_accretion() -> None:
    """Decision 151 clause 3(ii): a dated in-Intent-section accretion -- using the SAME
    amendment_forms annotation vocabulary as a typed-id-list trailer -- must stay part of the
    typed intent value. The prose terminator set deliberately does not treat amendment_forms
    openers as terminators (unlike the typed-id-list terminator), so this must not be truncated.
    """
    body = (
        "**Status:** Decided\n\n"
        "**Intent:** Make the durable why quotable.\n\n"
        "> **Update (2026-07-20):** Clarifies that quoting applies to ratified decisions only.\n\n"
        "**Decision:** Do the thing.\n"
    )
    intent = _extract_multiline_section(body, "Intent")
    assert "Make the durable why quotable." in intent
    assert "Clarifies that quoting applies to ratified decisions only." in intent
