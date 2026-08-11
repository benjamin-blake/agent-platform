"""Mirror test for scripts/checks/_schema.py (Decision 169): Entry field grammar, segment-token
set, and frozen-ness."""

from __future__ import annotations

import dataclasses

import pytest
import yaml

from scripts.checks._common import ROOT
from scripts.checks._schema import SEGMENT_TOKENS, Entry


class TestEntryFrozenness:
    def test_entry_is_frozen(self) -> None:
        entry = Entry(name="validate_x", module="scripts.checks.misc.validate_x", attr="validate_x")
        with pytest.raises(dataclasses.FrozenInstanceError):
            entry.name = "validate_y"  # type: ignore[misc]


class TestEntryFieldGrammar:
    def test_module_and_attr_are_two_separate_fields(self) -> None:
        entry = Entry(name="validate_x", module="scripts.checks.misc.validate_x", attr="validate_x")
        assert entry.module == "scripts.checks.misc.validate_x"
        assert entry.attr == "validate_x"
        assert ":" not in entry.module

    def test_defaults(self) -> None:
        entry = Entry(name="validate_x", module="scripts.checks.misc.validate_x", attr="validate_x")
        assert entry.owner == "platform"
        assert entry.product_coupled is False
        assert entry.pre is False
        assert entry.pre_globs is None
        assert entry.full_segment is None


class TestSegmentTokens:
    def test_segment_tokens_are_the_five_full_tier_segments(self) -> None:
        assert SEGMENT_TOKENS == {
            "full_after_lint",
            "full_after_unit_tests",
            "full_after_terraform_checks",
            "full_after_dependency_health",
            "full_after_ensure_fresh_dq",
        }

    def test_segment_tokens_is_the_single_source_the_contract_is_asserted_against(self) -> None:
        contract = yaml.safe_load((ROOT / "docs" / "contracts" / "check-manifest.yaml").read_text(encoding="utf-8"))
        declared = set(contract["entry_grammar"]["declared_segment_tokens"])
        assert declared == SEGMENT_TOKENS
