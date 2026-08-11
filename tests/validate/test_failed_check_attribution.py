"""Dispatch-level failed-check attribution (ci-rca-evidence-fidelity).

Covers scripts/validate.py's _dispatch_check chokepoint end to end: every registered check's
failure labels must attribute back to the check name via
scripts.checks.validation_result.dispatch_recording, and a patch on the check's DEFINING module
(Decision 169, amends Decision 104's `patch("validate.<name>")` dispatch) must keep working
through the delegation.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from scripts.checks import registry, validation_result
from tests.fixtures.validate_module import _validate

_dispatch_check = _validate._dispatch_check


@pytest.fixture(autouse=True)
def _reset_attributions():
    validation_result._ATTRIBUTIONS.clear()
    yield
    validation_result._ATTRIBUTIONS.clear()


def test_dispatch_check_delegates_to_dispatch_recording_with_resolved_callable() -> None:
    with patch("validate.validation_result.dispatch_recording") as mock_dispatch:
        _dispatch_check("validate_invariants", [])
    mock_dispatch.assert_called_once()
    args = mock_dispatch.call_args.args
    assert args[0] == "validate_invariants"
    assert args[1] == []
    assert args[2] is registry.resolve("validate_invariants")


def test_dispatch_check_attributes_a_real_failure_to_the_check_name() -> None:
    with patch(
        "scripts.checks.misc.validate_invariants.validate_invariants",
        lambda failed: failed.append("Coverage below 100%"),
    ):
        failed: list[str] = []
        _dispatch_check("validate_invariants", failed)
    assert failed == ["Coverage below 100%"]
    assert validation_result._ATTRIBUTIONS == [{"check": "validate_invariants", "label": "Coverage below 100%"}]


def test_dispatch_check_attributes_nothing_when_the_check_passes() -> None:
    with patch("scripts.checks.misc.validate_invariants.validate_invariants", lambda failed: None):
        failed: list[str] = []
        _dispatch_check("validate_invariants", failed)
    assert failed == []
    assert validation_result._ATTRIBUTIONS == []


def test_dispatch_check_patch_interception_survives_the_delegation() -> None:
    """A patch on the DEFINING module must still intercept -- _dispatch_check's docstring
    contract -- now that the call is routed through
    validation_result.dispatch_recording(name, failed, registry.resolve(name))."""
    sentinel_calls: list[str] = []

    def _sentinel(failed: list[str]) -> None:
        sentinel_calls.append("called")
        failed.append("sentinel failure")

    with patch("scripts.checks.hygiene.validate_placement.validate_placement", _sentinel):
        failed: list[str] = []
        _dispatch_check("validate_placement", failed)
    assert sentinel_calls == ["called"]
    assert failed == ["sentinel failure"]
    assert validation_result._ATTRIBUTIONS == [{"check": "validate_placement", "label": "sentinel failure"}]


def test_dispatch_check_attributes_multiple_labels_from_one_check() -> None:
    def _two_labels(failed: list[str]) -> None:
        failed.append("first")
        failed.append("second")

    with patch("scripts.checks.misc.validate_invariants.validate_invariants", _two_labels):
        failed: list[str] = []
        _dispatch_check("validate_invariants", failed)
    assert validation_result._ATTRIBUTIONS == [
        {"check": "validate_invariants", "label": "first"},
        {"check": "validate_invariants", "label": "second"},
    ]
