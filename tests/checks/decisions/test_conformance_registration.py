"""validate_decision_entry_conformance's --pre tier registration (PLAN-decision-entry-flow-
governance, CFG-03's "fails --pre" acceptance).

Before this plan, validate_decision_entry_conformance was full-tier only (registry.py), so it
fired post-merge on main and never gated the PR -- this module's own assertion is genuinely red
against the pre-change tree, because the pre-existing
test_pre_sequence_meets_required_floor asserts a SUBSET floor (REQUIRED_PRE_CHECKS <= actual),
which adding a check never reddens.
"""

from __future__ import annotations

from scripts.checks import registry
from scripts.checks.decisions.validate_decision_entry_conformance import (
    validate_decision_entry_conformance as _defining_module_export,
)


class TestPreTierRegistration:
    def test_present_in_pre_sequence_with_decisions_glob_gate(self) -> None:
        steps = {step.name: step for step in registry.pre_sequence() if step.kind == "check"}
        assert "validate_decision_entry_conformance" in steps
        step = steps["validate_decision_entry_conformance"]
        assert step.pre_globs == ("docs/DECISIONS.md", "docs/DECISIONS_ARCHIVE.md")

    def test_resolves_via_the_registry_to_its_defining_module(self) -> None:
        """Dispatch is registry.resolve(name)(failed) in scripts/validate.py (Decision 169) --
        without a manifest Entry, resolve() raises UnknownCheckError on the check name."""
        assert registry.resolve("validate_decision_entry_conformance") is _defining_module_export

    def test_also_present_in_full_sequence(self) -> None:
        """Full-tier registration (pre-existing) is unchanged by this plan -- both tiers now
        carry the check, --pre newly gated on the two DECISIONS files, full unscoped."""
        full_names = {step.name for step in registry.full_sequence() if step.kind == "check"}
        assert "validate_decision_entry_conformance" in full_names
