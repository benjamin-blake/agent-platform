"""Tests for scripts/roadmap/plan_document.py -- schema v4 test_obligations (per-source waivers
and linked-step executability), covering the T1.11 exit criteria.

Split from the former tests/test_plan_document.py monolith (PLAN-decompose-test-plan-document,
Decision 128 decompose-by-default): TestTestObligations relocated verbatim. Peeled into its own
module (rather than left in test_optional_fields.py) so the module PLAN-plan-resolution-content-keyed
extends next keeps the most headroom.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from scripts.roadmap.plan_document import PlanDocument
from tests.fixtures.plan_document_helpers import _base, _mutate


class TestTestObligations:
    """Schema v4 test obligations: per-source waivers and real linked-step executability."""

    @staticmethod
    def _v4(**overrides) -> dict:
        d = _mutate(
            schema_version=4,
            handoff_policy={"full_validation_required_before_commit": True, "timeout_disposition": "blocked"},
        )
        d["verification_plan"][0]["command"] = "bin/venv-python -m pytest tests/test_example.py::test_normalizes"
        d.update(overrides)
        return d

    @staticmethod
    def _obligation(**overrides) -> dict:
        row = {
            "source": "scripts/example.py",
            "behavior": "returns the normalized result",
            "test_selector": "tests/test_example.py::test_normalizes",
            "verification_step": 1,
            "red_green_expectation": "fails before the behavior change and passes afterward",
        }
        row.update(overrides)
        return row

    def test_selector_obligation_exposes_its_evidence(self) -> None:
        doc = PlanDocument.model_validate(self._v4(test_obligations=[self._obligation()]))
        assert doc.test_obligations[0].evidence == "tests/test_example.py::test_normalizes"

    def test_command_obligation_matches_the_step_by_substring(self) -> None:
        d = self._v4(test_obligations=[self._obligation(test_selector=None, command="pytest tests/test_example.py")])
        d["verification_plan"][0]["command"] = "pytest tests/test_example.py --maxfail=1"
        assert PlanDocument.model_validate(d).test_obligations[0].command

    @pytest.mark.parametrize(
        "step_command",
        [
            "bin/venv-python -m pytest tests/",
            "bin/venv-python -m pytest tests",
            "bin/venv-python -m pytest tests/test_example.py",
            "bin/venv-python -m pytest tests/test_example.py::test_normalizes",
            'pytest tests/test_example.py::test_normalizes "',
            "pytest --ignore= tests/test_example.py::test_normalizes",
        ],
    )
    def test_step_that_hosts_the_selector_is_accepted(self, step_command: str) -> None:
        d = self._v4(test_obligations=[self._obligation()])
        d["verification_plan"][0]["command"] = step_command
        assert PlanDocument.model_validate(d).test_obligations

    @pytest.mark.parametrize(
        "step_command",
        [
            "pytest --ignore=tests/test_example.py tests/",
            "pytest --ignore tests/test_example.py tests/",
            "pytest --deselect=tests/test_example.py::test_normalizes tests/",
            "pytest --ignore-glob=tests/ tests/",
        ],
    )
    def test_step_that_excludes_the_selector_is_rejected(self, step_command: str) -> None:
        d = self._v4(test_obligations=[self._obligation()])
        d["verification_plan"][0]["command"] = step_command
        with pytest.raises(ValidationError, match="explicitly excludes"):
            PlanDocument.model_validate(d)

    @pytest.mark.parametrize(
        ("overrides", "message"),
        [
            ({"behavior": " "}, "behavior must be non-blank"),
            ({"verification_step": 99}, "links missing verification_plan step 99"),
            ({"test_selector": "tests/test_other.py"}, "evidence is not executable"),
            ({"red_green_expectation": None, "waiver_reason": "thin"}, "must be substantive"),
            ({"test_selector": None}, "exactly one non-blank test_selector or command"),
            ({"command": "pytest tests/test_example.py"}, "exactly one non-blank test_selector or command"),
            ({"red_green_expectation": None}, "exactly one red_green_expectation"),
            ({"waiver_reason": "A substantive deterministic limit."}, "exactly one red_green_expectation"),
        ],
    )
    def test_malformed_obligation_is_rejected(self, overrides: dict, message: str) -> None:
        d = self._v4(test_obligations=[self._obligation(**overrides)])
        with pytest.raises(ValidationError, match=message):
            PlanDocument.model_validate(d)

    def test_waiver_is_declared_per_source(self) -> None:
        waived = self._obligation(red_green_expectation=None, waiver_reason="No deterministic runtime path exists here.")
        assert PlanDocument.model_validate(self._v4(test_obligations=[waived])).test_obligations[0].waiver_reason

    def test_plan_level_waiver_field_no_longer_exists(self) -> None:
        d = self._v4(test_obligation_waiver_reason="Only static documentation metadata changes are in scope.")
        with pytest.raises(ValidationError, match="test_obligation_waiver_reason"):
            PlanDocument.model_validate(d)

    def test_historical_plan_without_obligations_remains_valid(self) -> None:
        assert PlanDocument.model_validate(_base()).test_obligations == []
