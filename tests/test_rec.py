"""Tests for src/schemas/rec.py (T0.12 exit criteria)."""

from __future__ import annotations

import typing

import pytest
from pydantic import ValidationError

from src.schemas.annotations import DqAcceptedValues, DqNotNull
from src.schemas.rec import RecPayload

_KNOWN_GOOD_REC = {
    "id": "rec-720",
    "title": "Update TelemetryAgentInvocations docstring to include cron_workflow invocation type",
    "source": "code-review",
    "effort": "XS",
    "priority": "Medium",
    "status": "open",
    "automatable": True,
    "file": "scripts/telemetry_schemas.py",
    "context": (
        "TelemetryAgentInvocations class docstring at line 330 says 'One row per scheduled agent "
        "Lambda invocation' but workflow_run_id was added in cc-scheduled-agents-phase-3 to support "
        "Claude Code cron_workflow trigger (non-Lambda). Any agent reading the docstring for context "
        "will incorrectly assume Lambda-only scope for this table."
    ),
    "acceptance": (
        "grep -A1 'class TelemetryAgentInvocations' scripts/telemetry_schemas.py | grep -iE 'cron_workflow|claude code'"
    ),
    "risk": "low",
    "created_timestamp": "2026-05-09 00:00:00.000000",
    "last_updated_timestamp": "2026-05-09 21:55:56.127000",
}


def test_recpayload_validates_known_good_dict() -> None:
    rec = RecPayload(**_KNOWN_GOOD_REC)
    assert rec.id == "rec-720"
    assert rec.status == "open"
    assert rec.effort == "XS"


def test_recpayload_rejects_invalid_status() -> None:
    bad = dict(_KNOWN_GOOD_REC, status="done")
    with pytest.raises(ValidationError):
        RecPayload(**bad)


def test_recpayload_rejects_invalid_effort() -> None:
    bad = dict(_KNOWN_GOOD_REC, effort="XXL")
    with pytest.raises(ValidationError):
        RecPayload(**bad)


def test_recpayload_annotated_metadata_extractable() -> None:
    hints = typing.get_type_hints(RecPayload, include_extras=True)

    status_meta = typing.get_args(hints["status"])
    dq_types = {type(m) for m in status_meta if isinstance(m, (DqNotNull, DqAcceptedValues))}
    assert DqNotNull in dq_types
    assert DqAcceptedValues in dq_types

    effort_meta = typing.get_args(hints["effort"])
    dq_effort = {type(m) for m in effort_meta if isinstance(m, (DqNotNull, DqAcceptedValues))}
    assert DqNotNull in dq_effort
    assert DqAcceptedValues in dq_effort


def test_recpayload_id_pattern() -> None:
    bad = dict(_KNOWN_GOOD_REC, id="bad-id")
    with pytest.raises(ValidationError):
        RecPayload(**bad)


def test_recpayload_accepts_agent_prefix() -> None:
    ok = dict(_KNOWN_GOOD_REC, id="agent-001")
    rec = RecPayload(**ok)
    assert rec.id == "agent-001"


def test_recpayload_ignores_extra_fields() -> None:
    extra = dict(_KNOWN_GOOD_REC, execution_result="success", unknown_field="x")
    rec = RecPayload(**extra)
    assert not hasattr(rec, "execution_result")


def test_recpayload_requires_all_core_fields() -> None:
    minimal = {k: v for k, v in _KNOWN_GOOD_REC.items() if k != "title"}
    with pytest.raises(ValidationError):
        RecPayload(**minimal)
