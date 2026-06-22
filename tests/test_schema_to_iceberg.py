"""Tests for scripts/schema_to_iceberg.py (T0.13 exit criteria)."""

from __future__ import annotations

import io
from contextlib import redirect_stdout
from datetime import date, datetime
from pathlib import Path
from typing import Annotated, List, Literal, Optional

import pytest
from pydantic import BaseModel

from scripts.schema_to_iceberg import (
    DestructiveSchemaChange,
    MissingPartitionSpec,
    UnknownPartitionColumn,
    UnsupportedFieldType,
    emit_drop,
    iceberg_type,
    main,
    model_to_iceberg_ddl,
    model_to_iceberg_schema,
)
from src.schemas.annotations import DqNotNull, partition_by
from tests.fixtures.iceberg_fixture import CoverageModel

_GOLDEN = Path("tests/fixtures/iceberg/coverage_model.ddl.sql").read_text()
_GOLDEN_DDL = _GOLDEN.rstrip("\n")  # model_to_iceberg_ddl() returns DDL without trailing newline


def test_golden_byte_match_api() -> None:
    ddl = model_to_iceberg_ddl(
        CoverageModel,
        "coverage_model",
        database="agent_platform",
        location="s3://agent-platform-data-lake/iceberg/coverage_model/",
    )
    assert ddl == _GOLDEN_DDL


def test_golden_byte_match_cli() -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        ret = main(
            [
                "--model",
                "tests.fixtures.iceberg_fixture:CoverageModel",
                "--table",
                "coverage_model",
                "--database",
                "agent_platform",
                "--location",
                "s3://agent-platform-data-lake/iceberg/coverage_model/",
            ]
        )
    assert ret == 0
    assert buf.getvalue() == _GOLDEN


def test_type_matrix() -> None:
    assert iceberg_type(str) == "string"
    assert iceberg_type(int) == "bigint"
    assert iceberg_type(float) == "double"
    assert iceberg_type(bool) == "boolean"
    assert iceberg_type(datetime) == "timestamp"
    assert iceberg_type(date) == "date"
    assert iceberg_type(list[str]) == "array<string>"
    assert iceberg_type(list[int]) == "array<bigint>"
    assert iceberg_type(Literal["a", "b"]) == "string"
    assert iceberg_type(Optional[str]) == "string"
    assert iceberg_type(list[list[str]]) == "array<array<string>>"


def test_iceberg_type_bare_list_raises() -> None:
    with pytest.raises(UnsupportedFieldType):
        iceberg_type(List)  # typing.List without type param -> get_args returns ()


def test_unsupported_type_raise() -> None:
    with pytest.raises(UnsupportedFieldType):
        iceberg_type(bytes)


def test_pyiceberg_schema_valid() -> None:
    from pyiceberg.schema import Schema

    schema = model_to_iceberg_schema(CoverageModel)
    assert isinstance(schema, Schema)
    required_names = {f.name for f in schema.fields if f.required}
    assert required_names == {"required_field"}


def test_pyiceberg_schema_unsupported_type() -> None:
    @partition_by("day(ts)")
    class _BadTypeModel(BaseModel):
        ts: datetime
        data: bytes

    with pytest.raises(UnsupportedFieldType):
        model_to_iceberg_schema(_BadTypeModel)


def test_dqdeleted_excluded() -> None:
    ddl = model_to_iceberg_ddl(CoverageModel, "coverage_model", database="db", location="s3://x/")
    assert "retired_col" not in ddl


def test_nondestructive() -> None:
    with pytest.raises(DestructiveSchemaChange, match="nonexistent_column"):
        model_to_iceberg_ddl(
            CoverageModel,
            "t",
            database="db",
            location="s3://x/",
            deployed_columns=["nonexistent_column"],
        )
    # DqDeleted column in deployed_columns is not a destructive change
    ddl = model_to_iceberg_ddl(
        CoverageModel,
        "t",
        database="db",
        location="s3://x/",
        deployed_columns=["retired_col"],
    )
    assert ddl is not None


def test_emit_drop_requires_dqdeleted() -> None:
    with pytest.raises(ValueError, match="not marked DqDeleted"):
        emit_drop(CoverageModel, "coverage_model", "name")
    sql = emit_drop(CoverageModel, "coverage_model", "retired_col")
    assert "DROP COLUMN" in sql
    assert "retired_col" in sql


def test_emit_drop_unknown_field() -> None:
    with pytest.raises(KeyError, match="nonexistent"):
        emit_drop(CoverageModel, "coverage_model", "nonexistent")


def test_missing_partition_raises() -> None:
    class _NoPartitionModel(BaseModel):
        x: str = ""

    with pytest.raises(MissingPartitionSpec):
        model_to_iceberg_ddl(_NoPartitionModel, "t", database="db", location="s3://x/")


def test_partition_unknown_column_raises() -> None:
    @partition_by("day(nonexistent_col)")
    class _BadPartitionModel(BaseModel):
        x: str = ""

    with pytest.raises(UnknownPartitionColumn, match="nonexistent_col"):
        model_to_iceberg_ddl(_BadPartitionModel, "t", database="db", location="s3://x/")


def test_identity_partition() -> None:
    @partition_by("event_date")
    class _BarePartitionModel(BaseModel):
        event_date: date

    ddl = model_to_iceberg_ddl(_BarePartitionModel, "t", database="db", location="s3://x/")
    assert "PARTITIONED BY (event_date)" in ddl


def test_field_without_description() -> None:
    @partition_by("day(ts)")
    class _NoDescModel(BaseModel):
        ts: datetime

    ddl = model_to_iceberg_ddl(_NoDescModel, "t", database="db", location="s3://x/")
    assert "COMMENT" not in ddl
    assert "ts timestamp" in ddl


def test_dqnotnull_no_description() -> None:
    @partition_by("day(ts)")
    class _NNNoDescModel(BaseModel):
        x: Annotated[str, DqNotNull()]
        ts: datetime

    ddl = model_to_iceberg_ddl(_NNNoDescModel, "t", database="db", location="s3://x/")
    assert "COMMENT '[NOT NULL]'" in ddl


def test_main_emit_drop() -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        ret = main(
            [
                "--model",
                "tests.fixtures.iceberg_fixture:CoverageModel",
                "--table",
                "coverage_model",
                "--database",
                "agent_platform",
                "--location",
                "s3://dummy/",
                "--emit-drop",
                "retired_col",
            ]
        )
    assert ret == 0
    output = buf.getvalue()
    assert "DROP COLUMN" in output
    assert "retired_col" in output
