"""Tests for the decision-corpus currency derivation (PLAN-decision-corpus-currency,
rec-3055/rec-3056): scripts.decisions_md.bold_status / status_is_superseded / is_compacted_stub
/ derive_currency.

New file rather than an append to test_parse.py: that sibling is at 493 SLOC and cannot absorb
this coverage.
"""

from __future__ import annotations

import pytest

from scripts.decisions_md import bold_status, derive_currency, is_compacted_stub, status_is_superseded


def _row(decision_id: int, raw_block: str, superseded_by: str = "") -> dict:
    return {"decision_id": decision_id, "raw_block": raw_block, "superseded_by": superseded_by}


class TestBoldStatus:
    def test_returns_normalized_value(self) -> None:
        assert bold_status("**Status:** Superseded -- legacy note\n") == "Superseded"

    def test_strips_whitespace(self) -> None:
        assert bold_status("**Status:**   Decided  \n") == "Decided"

    def test_empty_when_no_marker(self) -> None:
        assert bold_status("no status marker here\n") == ""

    def test_first_match_wins(self) -> None:
        block = "**Status:** Decided\n\n> quoting: **Status:** Superseded\n"
        assert bold_status(block) == "Decided"


class TestStatusIsSuperseded:
    @pytest.mark.parametrize(
        ("block", "expected"),
        [
            ("**Status:** Superseded\n", True),
            ("**Status:** Superseded -- 2026-01\n", True),
            ("**Status:** Decided\n", False),
            ("no marker\n", False),
        ],
    )
    def test_cases(self, block: str, expected: bool) -> None:
        assert status_is_superseded(block) is expected


class TestIsCompactedStub:
    """Mirrors tests/checks/decisions/test_validate_decision_entry_conformance.py::
    TestIsCompactedStubHelper -- same behaviour, now exercised directly against the promoted
    public symbol rather than only through the checks-module alias."""

    @pytest.mark.parametrize(
        ("block", "expected"),
        [
            ("## Decision 1: No status (Decided)\n\n**Decision:** X.\n", False),
            ("**Status:** Decided\n\n**Decision:** X.\n", False),
            ("**Status:** Superseded\n\n**Decision:** X.\n", False),
            ("**Status:** Superseded\n\n**Decision:** See Decision 6.\n\n**Superseded by: Decision 6**\n", True),
        ],
        ids=["no_status_marker", "status_not_superseded", "superseded_no_pointer", "superseded_with_pointer"],
    )
    def test_cases(self, block: str, expected: bool) -> None:
        assert is_compacted_stub(block) is expected


class TestDeriveCurrencyPrecedence:
    """Precedence: superseded_compacted > superseded_pointer > amended > current. Synthetic rows
    cover both inbound-edge cases (title/envelope-borne, not victim-side) and the two cases the
    real corpus does not discriminate on its own (stub-vs-amended, pointer-vs-amended)."""

    def test_compacted_stub_wins_over_inbound_amends(self) -> None:
        # A row that is BOTH a compacted stub AND the target of an inbound amends edge must
        # resolve to superseded_compacted -- precedence position 1 beats position 3.
        row = _row(
            9001,
            "**Status:** Superseded\n\n**Decision:** See Decision 9002.\n\n**Superseded by: Decision 9002**\n",
        )
        assert derive_currency(row, inbound_supersedes=set(), inbound_amends={9001}) == "superseded_compacted"

    def test_victim_side_superseded_by_yields_pointer(self) -> None:
        row = _row(9002, "**Status:** Decided\n\n**Decision:** X.\n", superseded_by="dec-009")
        assert derive_currency(row, inbound_supersedes=set(), inbound_amends=set()) == "superseded_pointer"

    def test_inbound_supersedes_edge_alone_yields_pointer(self) -> None:
        # No victim-side pointer at all -- only a corpus-wide inbound supersedes edge (the
        # Decision 80 shape: superseded purely by another entry's inbound title edge).
        row = _row(9003, "**Status:** Decided\n\n**Decision:** X.\n")
        assert derive_currency(row, inbound_supersedes={9003}, inbound_amends=set()) == "superseded_pointer"

    def test_inbound_supersedes_beats_inbound_amends(self) -> None:
        row = _row(9004, "**Status:** Decided\n\n**Decision:** X.\n")
        assert derive_currency(row, inbound_supersedes={9004}, inbound_amends={9004}) == "superseded_pointer"

    def test_inbound_amends_edge_alone_yields_amended(self) -> None:
        row = _row(9005, "**Status:** Decided\n\n**Decision:** X.\n")
        assert derive_currency(row, inbound_supersedes=set(), inbound_amends={9005}) == "amended"

    def test_status_prose_amended_yields_amended(self) -> None:
        row = _row(9006, "**Status:** Amended by Decision 9007 (2026-01-01).\n\n**Decision:** X.\n")
        assert derive_currency(row, inbound_supersedes=set(), inbound_amends=set()) == "amended"

    def test_no_edges_no_amendment_prose_yields_current(self) -> None:
        row = _row(9007, "**Status:** Decided\n\n**Decision:** X.\n")
        assert derive_currency(row, inbound_supersedes=set(), inbound_amends=set()) == "current"
