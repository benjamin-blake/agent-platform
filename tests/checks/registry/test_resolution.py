"""Tests for scripts/checks/registry.py's resolve() (Decision 169, amends Decision 104):
late-bound, non-caching dispatch through a check's DEFINING module -- driven end to end via a
real _validate.main() --pre run, not merely a direct _dispatch_check/resolve() call.
"""

from __future__ import annotations

import itertools
import sys
from unittest.mock import patch

import pytest

import scripts.checks.registry as registry
from tests.fixtures.pre_sequence_stub import select_steps
from tests.fixtures.subprocess_stubs import _pre_mock_run
from tests.fixtures.validate_module import _validate


class TestResolveUnknownName:
    def test_unknown_name_raises_a_named_error(self) -> None:
        with pytest.raises(registry.UnknownCheckError):
            registry.resolve("not_a_real_registered_check")


class TestResolveIsLateBoundAndNeverCachesTheCallable:
    def test_resolve_rebinds_between_two_calls(self) -> None:
        """A second assertion rebinds the module attribute between two dispatches and requires
        the second resolve() to see the new object -- proving no callable is cached anywhere on
        the resolve() path."""
        import scripts.checks.misc.validate_invariants as defining_module

        original = registry.resolve("validate_invariants")
        assert original is defining_module.validate_invariants

        def _patched(failed: list[str]) -> None:
            failed.append("patched")

        with patch.object(defining_module, "validate_invariants", _patched):
            rebound = registry.resolve("validate_invariants")
            assert rebound is _patched
            assert rebound is not original

        # Patch context exited -- resolve() must see the ORIGINAL object again, proving nothing
        # was cached during the patched window either.
        restored = registry.resolve("validate_invariants")
        assert restored is original


class TestDispatchInterceptsThroughARealTierRun:
    """The decisive end-to-end assertion (VP step 2): drives a ONE-CHECK --pre tier through
    scripts.validate.main() while the check's DEFINING module is patched, and observes the patch
    took effect. Calling _dispatch_check directly is NOT sufficient: a `_DISPATCH` table built at
    main() entry would still be EMPTY at a direct call, so a direct call resolves live and passes
    while the real dispatch path could still silently no-op."""

    def test_patch_on_defining_module_intercepts_through_main(self, monkeypatch: pytest.MonkeyPatch) -> None:
        sentinel_calls: list[str] = []

        def _sentinel(failed: list[str]) -> None:
            sentinel_calls.append("called")
            failed.append("sentinel failure")

        steps = select_steps(checks=("validate_placement",), scaffolds=(), sequence="pre")
        assert steps, "validate_placement must still be a live --pre check for this test to be meaningful"

        monkeypatch.setattr(sys, "argv", ["validate", "--pre"])
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("CI", raising=False)

        import scripts.checks.hygiene.validate_placement as defining_module

        with (
            patch.object(registry, "pre_sequence", return_value=steps),
            patch.object(defining_module, "validate_placement", _sentinel),
            patch("scripts.checks._common.get_changed_files", return_value=["scripts/validate.py"]),
            patch("scripts.checks._common.run", side_effect=_pre_mock_run),
            patch("time.monotonic", side_effect=itertools.chain([0.0], itertools.repeat(1.0))),
            pytest.raises(SystemExit) as exc_info,
        ):
            _validate.main()

        assert sentinel_calls == ["called"], "the patch on the DEFINING module did not intercept through main()"
        assert exc_info.value.code == 1

    def test_second_dispatch_sees_a_rebound_object_through_main(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Rebinding the module attribute BETWEEN two separate --pre runs must be observed by the
        second run -- proving main()'s own dispatch loop never warms a callable cache across runs."""
        steps = select_steps(checks=("validate_placement",), scaffolds=(), sequence="pre")

        monkeypatch.setattr(sys, "argv", ["validate", "--pre"])
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("CI", raising=False)

        import scripts.checks.hygiene.validate_placement as defining_module

        def _run_once(fn) -> int | str | None:
            monkeypatch.setenv("_VALIDATE_DEPTH", "0")  # reset the recursion guard for each run
            with (
                patch.object(registry, "pre_sequence", return_value=steps),
                patch.object(defining_module, "validate_placement", fn),
                patch("scripts.checks._common.get_changed_files", return_value=["scripts/validate.py"]),
                patch("scripts.checks._common.run", side_effect=_pre_mock_run),
                patch("time.monotonic", side_effect=itertools.chain([0.0], itertools.repeat(1.0))),
                pytest.raises(SystemExit) as exc_info,
            ):
                _validate.main()
            return exc_info.value.code

        assert _run_once(lambda failed: None) == 0
        assert _run_once(lambda failed: failed.append("second run failure")) == 1
