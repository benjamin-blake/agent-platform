"""Home for TestCheckValidation and TestOwnerMetadata, relocated from the retired
tests/test_checks_registry.py monolith (Decision 169, amends Decision 104).

TestCheckValidation is the only cover of Check.__post_init__'s _VALID_OWNERS raise.
TestOwnerMetadata is what scripts/checks/registry.py's own Check docstring names as the sole
reader of owner/product_coupled.
"""

from __future__ import annotations

import pytest

import scripts.checks.registry as registry

OWNER_EXPECTATIONS: dict[str, tuple[str, bool]] = {
    "validate_broker_env_reads": ("trading", False),
    "validate_product_roadmap": ("platform", True),
    "validate_environment_taxonomy": ("platform", True),
}


class TestCheckValidation:
    """Check.__post_init__'s owner validation (the _VALID_OWNERS guard)."""

    def test_invalid_owner_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="owner must be one of"):
            registry.Check(name="bogus_check", owner="not-a-real-owner")


class TestOwnerMetadata:
    """Owner/product_coupled metadata correctness -- populated once per check's
    @register(...) call site, never derived from dispatch."""

    def setup_method(self) -> None:
        # registry.get_check() reads _REGISTRY, populated only after a check module has been
        # imported at least once (Decision 169's lazy-import contract) -- all_checks() imports
        # every manifest-declared module, so it is the reliable way to populate _REGISTRY here.
        registry.all_checks()
        self.all_names = tuple(sorted(registry._ALL_ENTRIES))

    @pytest.mark.parametrize("name,expected", list(OWNER_EXPECTATIONS.items()))
    def test_pinned_owner(self, name: str, expected: tuple[str, bool]) -> None:
        owner, product_coupled = expected
        check = registry.get_check(name)
        assert check.owner == owner
        assert check.product_coupled is product_coupled

    def test_default_owner_is_platform_for_every_other_check(self) -> None:
        for name in self.all_names:
            if name in OWNER_EXPECTATIONS:
                continue
            check = registry.get_check(name)
            assert check.owner == "platform"
            assert check.product_coupled is False

    def test_exactly_three_pinned_checks(self) -> None:
        """Sampled others=platform per the plan's ownership audit: exactly one trading check
        and two platform/product_coupled=trading checks exist in the whole registry."""
        trading = [n for n in self.all_names if registry.get_check(n).owner == "trading"]
        product_coupled = [n for n in self.all_names if registry.get_check(n).product_coupled]
        assert trading == ["validate_broker_env_reads"]
        assert sorted(product_coupled) == ["validate_environment_taxonomy", "validate_product_roadmap"]
