"""validate_decision_entry_conformance's --pre tier registration (PLAN-decision-entry-flow-
governance, CFG-03's "fails --pre" acceptance). A NEW module: tests/test_checks_registry.py is
at 643/643 SLOC with a dec-159 raise-approved pin and zero headroom -- any added line would fail
both validate_sloc_limits and validate_sloc_budget_raises in --pre. That file is out of this
plan's scope and is not edited here.

Before this plan, validate_decision_entry_conformance was full-tier only (registry.py), so it
fired post-merge on main and never gated the PR -- this module's own assertion is genuinely red
against the pre-change tree, because the pre-existing
test_pre_sequence_meets_required_floor asserts a SUBSET floor (REQUIRED_PRE_CHECKS <= actual),
which adding a check never reddens.
"""

from __future__ import annotations

from scripts.checks import registry
from scripts.validate import validate_decision_entry_conformance as _validate_module_export


class TestPreTierRegistration:
    def test_present_in_pre_sequence_with_decisions_glob_gate(self) -> None:
        steps = {step.name: step for step in registry.pre_sequence() if step.kind == "check"}
        assert "validate_decision_entry_conformance" in steps
        step = steps["validate_decision_entry_conformance"]
        assert step.pre_globs == ("docs/DECISIONS.md", "docs/DECISIONS_ARCHIVE.md")

    def test_resolves_as_a_module_level_global_of_validate_py(self) -> None:
        """Dispatch is globals()[name](failed) in scripts/validate.py -- without the facade
        re-export line, --pre KeyErrors on the check name."""
        import scripts.validate as validate_module

        assert hasattr(validate_module, "validate_decision_entry_conformance")
        assert validate_module.validate_decision_entry_conformance is _validate_module_export

    def test_also_present_in_full_sequence(self) -> None:
        """Full-tier registration (pre-existing) is unchanged by this plan -- both tiers now
        carry the check, --pre newly gated on the two DECISIONS files, full unscoped."""
        full_names = {step.name for step in registry.full_sequence() if step.kind == "check"}
        assert "validate_decision_entry_conformance" in full_names
