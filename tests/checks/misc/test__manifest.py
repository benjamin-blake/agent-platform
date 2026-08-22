"""Mirror test for scripts/checks/misc/_manifest.py (Decision 169, amends Decision 104)."""

from __future__ import annotations

import importlib

import pytest

from scripts.checks import registry
from scripts.checks.misc import _manifest


class TestMiscManifest:
    """Every misc Entry names a bare-literal module/attr pair resolving to the same-named
    registered check inside this package."""

    def test_entries_is_non_empty(self) -> None:
        assert _manifest.ENTRIES

    def test_no_duplicate_names_within_this_manifest(self) -> None:
        names = [entry.name for entry in _manifest.ENTRIES]
        assert len(names) == len(set(names))

    @pytest.mark.parametrize("entry", _manifest.ENTRIES, ids=[entry.name for entry in _manifest.ENTRIES])
    def test_entry_module_is_inside_this_domain_package(self, entry) -> None:
        assert entry.module.startswith("scripts.checks.misc.")

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


class TestDiffCoveragePreTierOnlyDisposition:
    """validate_diff_coverage (PLAN-premerge-diff-coverage-gate) is registered pre=True with NO
    full_segment -- a DECLARED unsequenced-from-full disposition (misc sits in full_after_lint,
    which the full-tier skeleton dispatches BEFORE the unit_tests scaffold, so a full-tier leg
    would have no coverage artifact to read). This must be asserted, not assumed -- it fails
    loudly if anyone later adds a full_segment to this Entry."""

    def test_registered_pre_true(self) -> None:
        entry = next(e for e in _manifest.ENTRIES if e.name == "validate_diff_coverage")
        assert entry.pre is True

    def test_declares_no_full_segment(self) -> None:
        entry = next(e for e in _manifest.ENTRIES if e.name == "validate_diff_coverage")
        assert entry.full_segment is None

    def test_present_in_pre_sequence(self) -> None:
        names = {step.name for step in registry.pre_sequence()}
        assert "validate_diff_coverage" in names

    def test_absent_from_full_sequence(self) -> None:
        names = {step.name for step in registry.full_sequence() if step.kind == "check"}
        assert "validate_diff_coverage" not in names
