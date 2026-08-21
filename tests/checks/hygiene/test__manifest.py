"""Mirror test for scripts/checks/hygiene/_manifest.py (Decision 169, amends Decision 104)."""

from __future__ import annotations

import importlib

import pytest

from scripts.checks import registry
from scripts.checks.hygiene import _manifest


class TestHygieneManifest:
    """Every hygiene Entry names a bare-literal module/attr pair resolving to the same-named
    registered check inside this package."""

    def test_entries_is_non_empty(self) -> None:
        assert _manifest.ENTRIES

    def test_no_duplicate_names_within_this_manifest(self) -> None:
        names = [entry.name for entry in _manifest.ENTRIES]
        assert len(names) == len(set(names))

    @pytest.mark.parametrize("entry", _manifest.ENTRIES, ids=[entry.name for entry in _manifest.ENTRIES])
    def test_entry_module_is_inside_this_domain_package(self, entry) -> None:
        assert entry.module.startswith("scripts.checks.hygiene.")

    @pytest.mark.parametrize("entry", _manifest.ENTRIES, ids=[entry.name for entry in _manifest.ENTRIES])
    def test_entry_resolves_to_a_callable_named_its_own_attr(self, entry) -> None:
        module = importlib.import_module(entry.module)
        fn = getattr(module, entry.attr)
        assert callable(fn)
        assert fn.__name__ == entry.attr

    @pytest.mark.parametrize("entry", _manifest.ENTRIES, ids=[entry.name for entry in _manifest.ENTRIES])
    def test_registry_resolve_matches_the_manifest_entry(self, entry) -> None:
        module = importlib.import_module(entry.module)
        assert registry.resolve(entry.name) is getattr(module, entry.attr)


class TestValidateCheckAccountingDispatchedInBothTiers:
    """VP step 7: the new check is actually dispatched in both tiers, not merely defined."""

    def test_registered_in_both_pre_and_full_sequence(self) -> None:
        pre_names = {step.name for step in registry.pre_sequence() if step.kind == "check"}
        full_names = {step.name for step in registry.full_sequence() if step.kind == "check"}
        assert "validate_check_accounting" in pre_names
        assert "validate_check_accounting" in full_names


class TestValidateRootScopedDiffBaseDispatchedInBothTiers:
    """rec-3166: the new guard is actually dispatched in both tiers, not merely defined."""

    def test_registered_in_both_pre_and_full_sequence(self) -> None:
        pre_names = {step.name for step in registry.pre_sequence() if step.kind == "check"}
        full_names = {step.name for step in registry.full_sequence() if step.kind == "check"}
        assert "validate_root_scoped_diff_base" in pre_names
        assert "validate_root_scoped_diff_base" in full_names


class TestValidateVacuityJustifiedDispatched:
    """VP step 3: validate_vacuity_justified (rec-3163) is dispatched full-tier only -- it
    adjudicates a full-tier check's own declaration, so it belongs in that check's segment, not
    --pre (promoting coverage enforcement pre-merge is rec-3221's territory, not this plan's)."""

    def test_registered_in_full_sequence_only(self) -> None:
        pre_names = {step.name for step in registry.pre_sequence() if step.kind == "check"}
        full_names = {step.name for step in registry.full_sequence() if step.kind == "check"}
        assert "validate_vacuity_justified" in full_names
        assert "validate_vacuity_justified" not in pre_names
