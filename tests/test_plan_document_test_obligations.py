from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from scripts.roadmap.plan_document import PlanDocument

_FIXTURE = Path(__file__).parent / "fixtures" / "plan_documents" / "valid.yaml"


def _base() -> dict:
    data = yaml.safe_load(_FIXTURE.read_text(encoding="utf-8"))
    data["schema_version"] = 4
    data["handoff_policy"] = {"full_validation_required_before_commit": True, "timeout_disposition": "blocked"}
    return data


def _obligation(**overrides: object) -> dict:
    value = {
        "source": "scripts/example.py",
        "behavior": "returns the normalized result",
        "test_selector": "tests/test_example.py::test_normalizes_result",
        "verification_step": 1,
        "red_green_expectation": "fails before the behavior change and passes afterward",
    }
    value.update(overrides)
    return value


def test_selector_obligation_links_to_executable_verification_step() -> None:
    data = _base()
    data["verification_plan"][0]["command"] = "bin/venv-python -m pytest tests/test_example.py::test_normalizes_result"
    data["test_obligations"] = [_obligation()]
    assert PlanDocument.model_validate(data).test_obligations[0].verification_step == 1


def test_graduate_obligation_preserves_registry_identity() -> None:
    data = _base()
    data["verification_plan"][0].update(
        command="pytest tests/test_example.py::test_normalizes_result",
        graduation="graduate",
        graduation_check_id="test-obligation-graduation-linkage",
    )
    data["test_obligations"] = [_obligation()]
    doc = PlanDocument.model_validate(data)
    linked = next(step for step in doc.verification_plan if step.step == doc.test_obligations[0].verification_step)
    assert linked.graduation_check_id == "test-obligation-graduation-linkage"


def test_command_obligation_is_supported() -> None:
    data = _base()
    data["verification_plan"][0]["command"] = "bin/venv-python -m pytest tests/test_example.py"
    data["test_obligations"] = [_obligation(test_selector=None, command="bin/venv-python -m pytest tests/test_example.py")]
    assert PlanDocument.model_validate(data).test_obligations[0].command


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"behavior": " "}, "behavior must be non-blank"),
        ({"verification_step": 99}, "links missing verification_plan step 99"),
        ({"test_selector": "tests/test_other.py"}, "evidence is not executable"),
        ({"red_green_expectation": None, "waiver_reason": "thin"}, "must be substantive"),
    ],
)
def test_malformed_obligation_fails(overrides: dict, message: str) -> None:
    data = _base()
    data["verification_plan"][0]["command"] = "bin/venv-python -m pytest tests/test_example.py::test_normalizes_result"
    data["test_obligations"] = [_obligation(**overrides)]
    with pytest.raises(ValidationError, match=message):
        PlanDocument.model_validate(data)


@pytest.mark.parametrize(
    "overrides",
    [
        {"test_selector": None},
        {"command": "pytest tests/test_example.py", "test_selector": "tests/test_example.py::test_normalizes_result"},
        {"red_green_expectation": None},
        {"waiver_reason": "A substantive deterministic limitation applies.", "red_green_expectation": "red then green"},
    ],
)
def test_obligation_requires_exactly_one_evidence_and_outcome(overrides: dict) -> None:
    data = _base()
    data["verification_plan"][0]["command"] = "pytest tests/test_example.py::test_normalizes_result"
    data["test_obligations"] = [_obligation(**overrides)]
    with pytest.raises(ValidationError):
        PlanDocument.model_validate(data)


def test_historical_plan_without_obligations_remains_valid() -> None:
    data = _base()
    data["schema_version"] = 3
    assert PlanDocument.model_validate(data).test_obligations == []


def test_substantive_plan_waiver_is_valid() -> None:
    data = _base()
    data["test_obligation_waiver_reason"] = "Only static documentation metadata changes are in scope."
    assert PlanDocument.model_validate(data).test_obligation_waiver_reason


def test_thin_plan_waiver_is_rejected() -> None:
    data = _base()
    data["test_obligation_waiver_reason"] = "thin"
    with pytest.raises(ValidationError, match="must be substantive"):
        PlanDocument.model_validate(data)


def test_obligations_and_plan_waiver_are_mutually_exclusive() -> None:
    data = _base()
    data["verification_plan"][0]["command"] = "pytest tests/test_example.py::test_normalizes_result"
    data["test_obligations"] = [_obligation()]
    data["test_obligation_waiver_reason"] = "The deterministic environment cannot execute this behavior."
    with pytest.raises(ValidationError, match="mutually exclusive"):
        PlanDocument.model_validate(data)
