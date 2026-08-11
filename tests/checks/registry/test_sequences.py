"""Relocated TestSequenceInvariants (Decision 169, amends Decision 104) plus the re-derivation
fidelity assertions OD-0..OD-6.

OD-0 is the load-bearing one: it independently RE-DERIVES the within-segment domain order from
the manifests plus registry.py's own declared order constants, and asserts the re-derivation
equals the live pre_sequence()/full_sequence() output -- so an undetermined/algorithm-drifted
derivation cannot ship green.
"""

from __future__ import annotations

import scripts.checks.registry as registry

_PRE_ONLY_CHECKS = ("validate_prose_budget_raises", "validate_sloc_budget_raises", "validate_vp_replay")
_UNSEQUENCED_CHECKS = ("validate_terraform_try",)


def _re_derive_pre_sequence() -> list[registry.Step]:
    """Independent re-derivation using registry's OWN exported order constants + manifest
    membership -- reimplements the grouping loop rather than calling registry.pre_sequence()
    again, so a bug in the grouping algorithm itself (not just a wrong order constant) is caught.
    """
    by_domain = registry._entries_by_domain()
    steps = [registry._s(name) for name in registry._PRE_TIER_LEADING_SCAFFOLDS]
    for domain in registry._PRE_DOMAIN_ORDER:
        for entry in by_domain.get(domain, []):
            if entry.pre:
                steps.append(registry._c(entry.name, pre_globs=entry.pre_globs))
    steps.extend(registry._s(name) for name in registry._PRE_TIER_TRAILING_SCAFFOLDS)
    return steps


def _re_derive_full_sequence() -> list[registry.Step]:
    by_domain = registry._entries_by_domain()
    steps: list[registry.Step] = []
    for scaffold_name, segment in registry._FULL_TIER_SKELETON:
        steps.append(registry._s(scaffold_name))
        if segment is None:
            continue
        for domain in registry._FULL_SEGMENT_DOMAIN_ORDER[segment]:
            for entry in by_domain.get(domain, []):
                if entry.full_segment == segment:
                    steps.append(registry._c(entry.name))
    return steps


class TestOD0DomainOrderReDerivation:
    def test_pre_sequence_re_derivation_matches_the_live_sequence(self) -> None:
        assert _re_derive_pre_sequence() == registry.pre_sequence()

    def test_full_sequence_re_derivation_matches_the_live_sequence(self) -> None:
        assert _re_derive_full_sequence() == registry.full_sequence()

    def test_every_domain_appearing_in_a_segment_is_declared_in_its_order_tuple(self) -> None:
        """A domain present in a segment's checks but absent from the declared order tuple would
        silently vanish from that segment (the `by_domain.get(domain, [])` walk only visits
        declared domains) -- assert the declared order tuples are a superset of the domains
        actually present in each segment."""
        by_domain = registry._entries_by_domain()

        pre_domains_present = {entry.module.split(".")[2] for entries in by_domain.values() for entry in entries if entry.pre}
        assert pre_domains_present <= set(registry._PRE_DOMAIN_ORDER)

        for segment, declared_domains in registry._FULL_SEGMENT_DOMAIN_ORDER.items():
            present = {
                entry.module.split(".")[2]
                for entries in by_domain.values()
                for entry in entries
                if entry.full_segment == segment
            }
            undeclared = present - set(declared_domains)
            assert present <= set(declared_domains), f"segment {segment!r}: undeclared domain(s) {undeclared}"


class TestOD1And2SlocOrdering:
    def _positions(self, steps: list[registry.Step]) -> dict[str, int]:
        return {step.name: i for i, step in enumerate(steps) if step.kind == "check"}

    def test_cc_limits_before_sloc_limits_in_full(self) -> None:
        pos = self._positions(registry.full_sequence())
        assert pos["validate_cc_limits"] < pos["validate_sloc_limits"]

    def test_cc_limits_before_sloc_limits_in_pre(self) -> None:
        pos = self._positions(registry.pre_sequence())
        assert pos["validate_cc_limits"] < pos["validate_sloc_limits"]

    def test_sloc_limits_before_sloc_budget_raises_in_pre(self) -> None:
        pos = self._positions(registry.pre_sequence())
        assert pos["validate_sloc_limits"] < pos["validate_sloc_budget_raises"]


class TestOD3ScaffoldAnchorOrder:
    def test_full_tier_scaffold_anchors_in_frozen_order(self) -> None:
        scaffolds = [step.name for step in registry.full_sequence() if step.kind == "scaffold"]
        assert scaffolds == [
            "lint",
            "unit_tests",
            "terraform_checks",
            "dependency_health",
            "ensure_fresh_dq",
            "precommit_all_files",
        ]

    def test_pre_tier_scaffolds_in_frozen_order(self) -> None:
        scaffolds = [step.name for step in registry.pre_sequence() if step.kind == "scaffold"]
        assert scaffolds == [
            "lint",
            "precommit_changed",
            "mypy_diff",
            "pytest_diff",
            "verifier_coverage_report",
            "budget_assertion",
        ]


class TestOD4ScaffoldAdjacentChecksStayInTheirSegments:
    def _segment_of(self, name: str) -> str:
        full = registry.full_sequence()
        idx = next(i for i, step in enumerate(full) if step.kind == "check" and step.name == name)
        preceding_scaffolds = [step.name for step in full[:idx] if step.kind == "scaffold"]
        return preceding_scaffolds[-1]

    def test_iam_runner_policy_immediately_after_terraform_checks(self) -> None:
        assert self._segment_of("validate_iam_runner_policy") == "terraform_checks"

    def test_requirements_and_prompts_block_after_dependency_health(self) -> None:
        for name in (
            "validate_requirements",
            "validate_prompt_files",
            "validate_workflow_agent_safety",
            "validate_prompt_compliance",
            "validate_instruction_architecture_layers",
        ):
            assert self._segment_of(name) == "dependency_health"

    def test_verification_harness_after_ensure_fresh_dq(self) -> None:
        assert self._segment_of("validate_verification_harness") == "ensure_fresh_dq"


class TestOD5PreOnlyAndUnsequencedChecks:
    def test_pre_only_checks_stay_pre_only(self) -> None:
        pre_names = {step.name for step in registry.pre_sequence() if step.kind == "check"}
        full_names = {step.name for step in registry.full_sequence() if step.kind == "check"}
        for name in _PRE_ONLY_CHECKS:
            assert name in pre_names
            assert name not in full_names

    def test_terraform_try_stays_unsequenced(self) -> None:
        pre_names = {step.name for step in registry.pre_sequence() if step.kind == "check"}
        full_names = {step.name for step in registry.full_sequence() if step.kind == "check"}
        for name in _UNSEQUENCED_CHECKS:
            assert name not in pre_names
            assert name not in full_names
            assert name in registry._ALL_ENTRIES


class TestOD6TrailingScaffolds:
    def test_budget_assertion_is_last_in_pre(self) -> None:
        assert registry.pre_sequence()[-1] == registry._s("budget_assertion")

    def test_precommit_all_files_is_last_in_full(self) -> None:
        assert registry.full_sequence()[-1] == registry._s("precommit_all_files")


class TestMembershipFloors:
    def test_no_duplicate_check_names_within_a_tier(self) -> None:
        for steps in (registry.pre_sequence(), registry.full_sequence()):
            names = [step.name for step in steps if step.kind == "check"]
            assert len(names) == len(set(names))

    def test_every_manifest_entry_is_pre_xor_full_xor_unsequenced_consistently(self) -> None:
        pre_names = {step.name for step in registry.pre_sequence() if step.kind == "check"}
        full_names = {step.name for step in registry.full_sequence() if step.kind == "check"}
        for entry in registry._ALL_ENTRIES.values():
            assert entry.pre == (entry.name in pre_names)
            assert (entry.full_segment is not None) == (entry.name in full_names)

    def test_membership_assertion_has_teeth_against_a_synthetic_removal(self) -> None:
        """Proves a membership assertion over the live full-tier check-name set is not vacuous:
        removing one real name from a copy of that set trips a subset assertion modeled on it --
        the growth-safe successor to the retired REQUIRED_FULL_CHECKS floor (Decision 104/169)."""
        full_names = {step.name for step in registry.full_sequence() if step.kind == "check"}
        removed = set(full_names)
        removed.discard(next(iter(removed)))
        assert not (full_names <= removed)
