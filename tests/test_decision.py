"""Tests for src/schemas/decision.py (T0.12 exit criteria)."""

from __future__ import annotations

import typing

import pytest
from pydantic import ValidationError

from src.schemas.annotations import DqAcceptedValues, DqNotNull
from src.schemas.decision import DecisionPayload

_KNOWN_GOOD_DECISION = {
    "id": "dec-027",
    "decision_id": 27,
    "title": "Git Bash venv Activation Fix via setup.py",
    "status": "Decided",
    "problem": "Git Bash could not activate the venv due to Windows-style path separators.",
    "decision_text": "Implement idempotent fix_venv_activate_for_git_bash() in setup.py.",
    "context": "Pure Python automation is platform-agnostic and does not depend on shell availability.",
    "decided_date": "",
    "related_decisions": [],
    "related_decisions_v2": "",
    "created_timestamp": "2026-04-28 15:01:28.529000",
    "last_updated_timestamp": "2026-04-28 15:01:28.529000",
}


def test_decisionpayload_validates_known_good_dict() -> None:
    dec = DecisionPayload(**_KNOWN_GOOD_DECISION)
    assert dec.id == "dec-027"
    assert dec.decision_id == 27
    assert dec.title == "Git Bash venv Activation Fix via setup.py"


def test_decisionpayload_rejects_invalid_id() -> None:
    bad = dict(_KNOWN_GOOD_DECISION, id="decision-027")
    with pytest.raises(ValidationError):
        DecisionPayload(**bad)


def test_decisionpayload_dual_write_invariant() -> None:
    ok = dict(_KNOWN_GOOD_DECISION, id="dec-050", decision_id=50)
    dec = DecisionPayload(**ok)
    assert dec.id == "dec-050"
    assert dec.decision_id == 50

    bad = dict(_KNOWN_GOOD_DECISION, id="dec-050", decision_id=51)
    with pytest.raises(ValidationError, match="Dual-write invariant"):
        DecisionPayload(**bad)


def test_decisionpayload_annotated_metadata_extractable() -> None:
    hints = typing.get_type_hints(DecisionPayload, include_extras=True)

    id_meta = typing.get_args(hints["id"])
    assert any(isinstance(m, DqNotNull) for m in id_meta)

    status_meta = typing.get_args(hints["status"])
    assert any(isinstance(m, DqAcceptedValues) for m in status_meta)


def test_decisionpayload_coerces_empty_related_v2() -> None:
    dec = DecisionPayload(**_KNOWN_GOOD_DECISION)
    assert dec.related_decisions_v2 is None


def test_decisionpayload_accepts_none_optional_fields() -> None:
    minimal = dict(_KNOWN_GOOD_DECISION, problem=None, decision_text=None, context=None)
    dec = DecisionPayload(**minimal)
    assert dec.problem is None


def test_decisionpayload_ignores_extra_fields() -> None:
    extra = dict(_KNOWN_GOOD_DECISION, unknown_legacy_field="x")
    dec = DecisionPayload(**extra)
    assert not hasattr(dec, "unknown_legacy_field")


def test_decisionpayload_requires_title() -> None:
    bad = {k: v for k, v in _KNOWN_GOOD_DECISION.items() if k != "title"}
    with pytest.raises(ValidationError):
        DecisionPayload(**bad)


def test_decisionpayload_preserves_valid_related_v2_list() -> None:
    ok = dict(_KNOWN_GOOD_DECISION, related_decisions_v2=["dec-001", "dec-002"])
    dec = DecisionPayload(**ok)
    assert dec.related_decisions_v2 == ["dec-001", "dec-002"]
