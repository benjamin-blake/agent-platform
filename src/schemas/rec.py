"""Canonical write-side RecPayload model (T0.12, CD.12).

Mirrors ops.yaml::tables.ops_recommendations write-time + enforced fields.
DqXxx markers document DQ intent; Pydantic Literal/field_validator enforce at runtime.

Read-side counterpart (extra="ignore", Optional fields) lives in
scripts/executor/jsonl_store.py::Recommendation -- do not conflate the two.
"""

from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, field_validator

from src.schemas.annotations import DqAcceptedValues, DqNotNull

_REC_ID_RE = re.compile(r"^(rec|agent|test)-\d+$")


class RecPayload(BaseModel):
    """Write-side canonical recommendation payload with Annotated DQ metadata."""

    model_config = ConfigDict(extra="ignore")

    id: Annotated[str, DqNotNull(exclude_before="2026-05-01")]
    title: Annotated[str, DqNotNull(write_time=True, exclude_before="2026-05-01")]
    source: Annotated[str, DqNotNull(write_time=True, exclude_before="2026-05-01")]
    effort: Annotated[
        Literal["XS", "S", "M", "L", "XL"],
        DqNotNull(write_time=True, exclude_before="2026-05-01"),
        DqAcceptedValues(values=("XS", "S", "M", "L", "XL")),
    ]
    priority: Annotated[
        Literal["Critical", "High", "Medium", "Low"],
        DqNotNull(write_time=True, exclude_before="2026-05-01"),
        DqAcceptedValues(values=("Critical", "High", "Medium", "Low")),
    ]
    status: Annotated[
        Literal["open", "closed", "failed", "declined", "superseded"],
        DqNotNull(write_time=True),
        DqAcceptedValues(values=("open", "closed", "failed", "declined", "superseded")),
    ]
    automatable: Annotated[bool, DqNotNull(write_time=True)]
    file: Annotated[str, DqNotNull(write_time=True, exclude_before="2026-05-01")]
    context: Annotated[str, DqNotNull(write_time=True, exclude_before="2026-05-01")]
    acceptance: Annotated[str, DqNotNull(write_time=True, exclude_before="2026-05-01")]
    risk: Annotated[
        Literal["low", "medium", "high"],
        DqNotNull(write_time=True),
        DqAcceptedValues(values=("low", "medium", "high")),
    ]
    created_timestamp: Annotated[str, DqNotNull(exclude_before="2026-05-01")]
    last_updated_timestamp: str

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        val = str(v).strip()
        if not _REC_ID_RE.match(val):
            raise ValueError(f"RecPayload id must match (rec|agent|test)-\\d+: {val!r}")
        return val
