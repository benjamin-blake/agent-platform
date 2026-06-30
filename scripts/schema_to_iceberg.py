"""Pydantic-to-Iceberg DDL generator (T0.13, CD.9, CD.12).

Walks an Annotated-Pydantic model's model_fields and emits Athena Iceberg CREATE TABLE
DDL in the repo house convention.

Type map (int->bigint is deliberate -- Iceberg integer-promotion safety):
  str->string | int->bigint | float->double | bool->boolean
  datetime->timestamp | date->date | list[T]->array<T> | Literal->string
  Optional[T] -> nullable T

DqNotNull -> required field in pyiceberg Schema + COMMENT appends ' [NOT NULL]'
DqDeleted -> excluded from CREATE DDL; surfaced only via --emit-drop
"""

from __future__ import annotations

import argparse
import importlib
import re
import sys
import typing
from datetime import date, datetime
from typing import Any, Literal, get_args, get_origin

from pydantic import BaseModel

from src.schemas.annotations import DqDeleted, DqNotNull

_DDL_TYPE_MAP: dict[type, str] = {
    str: "string",
    int: "bigint",
    float: "double",
    bool: "boolean",
    datetime: "timestamp",
    date: "date",
}


class UnsupportedFieldType(TypeError):
    pass


class MissingPartitionSpec(ValueError):
    pass


class UnknownPartitionColumn(ValueError):
    pass


class DestructiveSchemaChange(ValueError):
    pass


def _unwrap_optional(annotation: Any) -> tuple[Any, bool]:
    """Strip Optional / Union[X, None]; return (inner_type, is_nullable)."""
    origin = get_origin(annotation)
    if origin is typing.Union:
        args = [a for a in get_args(annotation) if a is not type(None)]
        if len(args) == 1:
            return args[0], True
    return annotation, False


def iceberg_type(annotation: Any) -> str:
    """Return the Athena Iceberg DDL type string for a Python type annotation."""
    annotation, _ = _unwrap_optional(annotation)
    origin = get_origin(annotation)

    if origin is list:
        inner_args = get_args(annotation)
        if not inner_args:
            raise UnsupportedFieldType(f"list requires a type argument: {annotation!r}")
        return f"array<{iceberg_type(inner_args[0])}>"

    if origin is Literal:
        return "string"

    result = _DDL_TYPE_MAP.get(annotation)
    if result is None:
        raise UnsupportedFieldType(f"Unsupported type: {annotation!r}")
    return result


def _partition_column(spec: str) -> str:
    """Extract the partition column name from a transform spec.

    Handles single-arg transforms (day(col) -> col), two-arg transforms
    (bucket(N, col) / truncate(W, col) -> col, the last argument), and bare
    columns (col -> col).
    """
    m = re.match(r"^\w+\((.*)\)$", spec.strip())
    if not m:
        return spec.strip()
    args = [a.strip() for a in m.group(1).split(",")]
    return args[-1]


def model_to_iceberg_schema(model: type[BaseModel]) -> Any:
    """Build a pyiceberg Schema from a Pydantic model (type-validity oracle).

    DqDeleted fields are excluded. DqNotNull fields become required fields.
    pyiceberg is imported lazily -- this module is safe to import where pyiceberg is absent.
    """
    from pyiceberg.schema import Schema
    from pyiceberg.types import (
        BooleanType,
        DateType,
        DoubleType,
        ListType,
        LongType,
        NestedField,
        StringType,
        TimestampType,
    )

    _PYTYPE_MAP = {
        str: StringType(),
        int: LongType(),
        float: DoubleType(),
        bool: BooleanType(),
        datetime: TimestampType(),
        date: DateType(),
    }

    counter = iter(range(1, 100_000))

    def _pytype(ann: Any) -> Any:
        ann, _ = _unwrap_optional(ann)
        origin = get_origin(ann)
        if origin is list:
            inner = _pytype(get_args(ann)[0])
            return ListType(element_id=next(counter), element_type=inner, element_required=False)
        if origin is Literal:
            return StringType()
        result = _PYTYPE_MAP.get(ann)
        if result is None:
            raise UnsupportedFieldType(f"Unsupported type: {ann!r}")
        return result

    fields = []
    for name, fi in model.model_fields.items():
        if any(isinstance(m, DqDeleted) for m in fi.metadata):
            continue
        required = any(isinstance(m, DqNotNull) for m in fi.metadata)
        fields.append(
            NestedField(
                field_id=next(counter),
                name=name,
                field_type=_pytype(fi.annotation),
                required=required,
            )
        )

    return Schema(*fields)


def model_to_iceberg_ddl(
    model: type[BaseModel],
    table: str,
    *,
    database: str = "agent_platform",
    location: str,
    deployed_columns: list[str] | None = None,
) -> str:
    """Emit Athena Iceberg CREATE TABLE DDL for a Pydantic model.

    Raises:
        MissingPartitionSpec: model has no @partition_by decorator (CD.9).
        UnknownPartitionColumn: partition transform references a column absent from model.
        DestructiveSchemaChange: deployed_columns contains a column absent from model and not DqDeleted.
        UnsupportedFieldType: a field uses a type with no Iceberg mapping.
    """
    if not hasattr(model, "__partition_by__"):
        raise MissingPartitionSpec(f"{model.__name__} has no @partition_by decorator (required per CD.9)")

    partition_spec: str = model.__partition_by__
    partition_col = _partition_column(partition_spec)
    model_field_names = set(model.model_fields.keys())

    if partition_col not in model_field_names:
        raise UnknownPartitionColumn(f"Partition column '{partition_col}' not found in {model.__name__}.model_fields")

    if deployed_columns is not None:
        dq_deleted_names = {
            name for name, fi in model.model_fields.items() if any(isinstance(m, DqDeleted) for m in fi.metadata)
        }
        for col in deployed_columns:
            if col not in model_field_names and col not in dq_deleted_names:
                raise DestructiveSchemaChange(
                    f"Deployed column '{col}' is absent from {model.__name__} and not marked DqDeleted"
                )

    col_lines: list[str] = []
    for name, fi in model.model_fields.items():
        if any(isinstance(m, DqDeleted) for m in fi.metadata):
            continue
        dq_notnull = any(isinstance(m, DqNotNull) for m in fi.metadata)
        col_type = iceberg_type(fi.annotation)
        comment = fi.description or ""
        if dq_notnull:
            comment = f"{comment} [NOT NULL]".strip() if comment else "[NOT NULL]"
        if comment:
            col_lines.append(f"  {name} {col_type} COMMENT '{comment}'")
        else:
            col_lines.append(f"  {name} {col_type}")

    cols = ",\n".join(col_lines)
    return (
        f"CREATE TABLE IF NOT EXISTS {database}.{table} (\n"
        f"{cols}\n"
        f")\n"
        f"PARTITIONED BY ({partition_spec})\n"
        f"LOCATION '{location}'\n"
        f"TBLPROPERTIES (\n"
        f"  'table_type'='ICEBERG',\n"
        f"  'format'='parquet',\n"
        f"  'write_compression'='gzip'\n"
        f")"
    )


def emit_drop(
    model: type[BaseModel],
    table: str,
    field: str,
    *,
    database: str = "agent_platform",
) -> str:
    """Emit ALTER TABLE DROP COLUMN for a DqDeleted field.

    Raises:
        KeyError: field not found in model.model_fields.
        ValueError: field is not marked DqDeleted.
    """
    if field not in model.model_fields:
        raise KeyError(f"Field '{field}' not found in {model.__name__}.model_fields")
    fi = model.model_fields[field]
    if not any(isinstance(m, DqDeleted) for m in fi.metadata):
        raise ValueError(f"Field '{field}' is not marked DqDeleted; --emit-drop is only valid for retired fields")
    return f"ALTER TABLE {database}.{table} DROP COLUMN {field}"


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns 0 on success."""
    parser = argparse.ArgumentParser(description="Emit Athena Iceberg CREATE TABLE DDL for a Pydantic model")
    parser.add_argument("--model", required=True, help="module.path:ClassName")
    parser.add_argument("--table", required=True, help="Table name")
    parser.add_argument("--database", default="agent_platform", help="Glue database name")
    parser.add_argument("--location", required=True, help="S3 LOCATION URI")
    parser.add_argument(
        "--emit-drop",
        metavar="FIELD",
        dest="emit_drop",
        default=None,
        help="Emit ALTER TABLE DROP COLUMN for a DqDeleted field (never during CREATE generation)",
    )
    args = parser.parse_args(argv)

    module_path, class_name = args.model.rsplit(":", 1)
    module = importlib.import_module(module_path)
    model_cls = getattr(module, class_name)

    if args.emit_drop:
        ddl = emit_drop(model_cls, args.table, args.emit_drop, database=args.database)
    else:
        ddl = model_to_iceberg_ddl(model_cls, args.table, database=args.database, location=args.location)

    print(ddl)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
