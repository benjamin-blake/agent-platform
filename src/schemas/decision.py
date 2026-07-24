"""Canonical write-side DecisionPayload model (T0.12, CD.12).

Mirrors ops.yaml::tables.ops_decisions. Most fields have enforced: false because
the decisions table is in a multi-phase normalisation migration; markers document
the intended final-state DQ discipline.

Read-side counterpart lives in scripts/executor/jsonl_store.py::Decision.
"""

from __future__ import annotations

import re
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from src.schemas.annotations import DqAcceptedValues, DqNotNull

_DECISION_ID_RE = re.compile(r"^dec-\d+$")


class DecisionPayload(BaseModel):
    """Write-side canonical decision payload with Annotated DQ metadata."""

    model_config = ConfigDict(extra="ignore")

    id: Annotated[str, DqNotNull(enforced=False)]
    decision_id: Annotated[int | None, DqNotNull(enforced=False)] = None
    title: Annotated[str, DqNotNull()]
    status: Annotated[
        str,
        DqNotNull(),
        DqAcceptedValues(values=("Decided", "Superseded", "Open"), enforced=False),
    ]
    problem: str | None = None
    decision_text: str | None = None
    context: str | None = None
    decided_date: str | None = None
    related_decisions: list[int] | None = None
    related_decisions_v2: list[str] | None = None
    # DAF-01 parity backstop (PLAN-daf-etl-parity-fidelity, Decision 134 cl.4) plus intent
    # (PLAN-dcg-intent-capture, Decision 151, audit finding DCG-06). Plain `str | None` -- NEVER
    # Annotated[...]/DqNotNull/any Dq* marker: validate_pydantic_yaml_drift walks this model's
    # Annotated fields against config/agent/data_quality/ops.yaml, and a Dq-wrapped field here
    # would demand matching ops.yaml blocks out of scope. The DQ intent for these fields lives in
    # config/agent/data_quality/decisions/ops_decisions.yaml instead (Phase-2 deferral pattern).
    raw_block: str | None = None
    reversal_conditions: str | None = None
    superseded_by: str | None = None
    content_hash: str | None = None
    intent: str | None = None
    created_timestamp: str
    last_updated_timestamp: str

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        val = str(v).strip()
        if not _DECISION_ID_RE.match(val):
            raise ValueError(f"Decision ID must match ^dec-\\d+$: {val!r}")
        return val

    @field_validator("related_decisions_v2", mode="before")
    @classmethod
    def _coerce_related_v2(cls, v: Any) -> list[str] | None:
        if v == "" or v is None:
            return None
        return v

    @model_validator(mode="after")
    def validate_dual_write(self) -> "DecisionPayload":
        if self.id is not None and self.decision_id is not None:
            expected = int(self.id.split("-")[1])
            if expected != self.decision_id:
                raise ValueError(
                    f"Dual-write invariant violated: id={self.id!r} implies decision_id={expected}, "
                    f"but got decision_id={self.decision_id}"
                )
        return self
