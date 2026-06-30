"""Synthetic type-coverage fixture for the Iceberg DDL generator (T0.13).

Deliberately NOT a product or market_data schema -- platform-tool delivery stays
decoupled from product schema authoring (KG.1 PLATFORM-only boundary).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, Field

from src.schemas.annotations import DqDeleted, DqNotNull, partition_by


@partition_by("day(last_updated_timestamp)")
class CoverageModel(BaseModel):
    """One field per supported Iceberg type plus DqNotNull, SCD2 timestamps, and a DqDeleted field."""

    name: Annotated[str, Field(description="Name")]
    count: Annotated[int, Field(description="Count")]
    score: Annotated[float, Field(description="Score")]
    active: Annotated[bool, Field(description="Active")]
    event_date: Annotated[date, Field(description="Event date")]
    tags: Annotated[list[str], Field(description="Tags")]
    category: Annotated[Literal["a", "b"], Field(description="Category")]
    optional_note: Annotated[Optional[str], Field(description="Optional note")] = None
    required_field: Annotated[str, DqNotNull(), Field(description="Required")]
    created_timestamp: Annotated[datetime, Field(description="SCD2 created")]
    last_updated_timestamp: Annotated[datetime, Field(description="SCD2 last updated")]
    retired_col: Annotated[str, DqDeleted(since="2026-01-01"), Field(description="Retired")] = ""
