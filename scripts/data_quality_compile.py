"""Data quality compile path: YAML/tombstones manifest -> Check objects, DuckLake SQL translation."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from scripts.data_quality_models import _TOMBSTONES_PATH, Check

# ---------------------------------------------------------------------------
# Tombstone resurrection checks
# ---------------------------------------------------------------------------


def load_tombstones(path: Path = _TOMBSTONES_PATH) -> list[dict]:
    """Load the list of hard-deleted record IDs from dq_tombstones.yaml."""
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        spec = yaml.safe_load(f)
    return spec.get("tombstones", []) if spec else []


def build_tombstone_checks(
    tombstones: list[dict],
    table_filter: str | None = None,
    database: str = "agent_platform",
) -> list[Check]:
    """Generate tombstone_resurrection Check objects from the tombstones manifest."""
    checks: list[Check] = []
    for entry in tombstones:
        table = entry.get("table", "")
        rec_id = entry.get("id", "")
        if not table or not rec_id:
            continue
        if table_filter and table != table_filter:
            continue
        view_name = f"{table}_current" if table == "ops_recommendations" else table
        query_table = f"{database}.{view_name}"
        checks.append(
            Check(
                table=table,
                column="id",
                test_type="tombstone_resurrection",
                sql=(f"SELECT COUNT(*) AS violation FROM {query_table} WHERE id = '{rec_id}'"),
                description=f"{table}: tombstoned record {rec_id} must not exist in {view_name}",
                severity="error",
                enforced=True,
            )
        )
    return checks


# ---------------------------------------------------------------------------
# YAML loading
# ---------------------------------------------------------------------------


def load_checks(
    yaml_path: Path,
    table_filter: str | None = None,
) -> tuple[list[Check], dict[str, Any]]:
    """Load and compile checks from a YAML file.

    Returns (checks, metadata) where metadata has database/workgroup info.
    """
    with open(yaml_path, encoding="utf-8") as f:
        spec = yaml.safe_load(f)

    database = spec.get("database", "agent_platform")
    workgroup = spec.get("athena_workgroup", "agent-platform-production")
    metadata = {"database": database, "athena_workgroup": workgroup}

    checks: list[Check] = []
    tables = spec.get("tables", {})

    for table_name, table_def in tables.items():
        if table_filter and table_name != table_filter:
            continue

        view_suffix = table_def.get("view_suffix", "")
        query_table = f"{database}.{table_name}{view_suffix}"

        # Table-level checks
        if "row_count" in table_def:
            rc = table_def["row_count"]
            min_rows = rc.get("min", 1)
            severity = rc.get("severity", "error")
            enforced = rc.get("enforced", True)
            exclude_before = rc.get("exclude_before")
            checks.append(
                Check(
                    table=table_name,
                    column=None,
                    test_type="row_count",
                    sql=(
                        f"SELECT CASE WHEN cnt < {min_rows} THEN 1 ELSE 0 END "
                        f"AS violation FROM "
                        f"(SELECT COUNT(*) AS cnt FROM {query_table})"
                    ),
                    description=f"{table_name}: must have >= {min_rows} rows",
                    severity=severity,
                    enforced=enforced,
                    exclude_before=exclude_before,
                )
            )

        if "recency" in table_def:
            rec = table_def["recency"]
            col = rec["column"]
            error_h = rec.get("error_after_hours", 168)
            enforced = rec.get("enforced", True)
            exclude_before = rec.get("exclude_before")
            # Use error threshold for the check; runner can distinguish warn vs error
            checks.append(
                Check(
                    table=table_name,
                    column=col,
                    test_type="recency",
                    sql=(
                        f"SELECT CASE WHEN "
                        f"date_diff('hour', MAX({col}), CURRENT_TIMESTAMP) > {error_h} "
                        f"THEN 1 ELSE 0 END AS violation "
                        f"FROM {query_table}"
                    ),
                    description=(f"{table_name}.{col}: most recent value must be within {error_h}h of now"),
                    severity="error",
                    enforced=enforced,
                    exclude_before=exclude_before,
                )
            )

        # Column-level checks
        columns = table_def.get("columns", {})
        for col_name, col_def in columns.items():
            tests = col_def.get("tests", [])
            for test in tests:
                compiled = _compile_column_test(
                    query_table,
                    table_name,
                    col_name,
                    test,
                )
                if compiled:
                    checks.append(compiled)

    return checks, metadata


def _compile_column_test(
    query_table: str,
    table_name: str,
    col_name: str,
    test: str | dict,
) -> Check | None:
    """Compile a single column test definition to a Check."""
    # Simple string tests: not_null, unique
    if isinstance(test, str):
        if test == "not_null":
            return Check(
                table=table_name,
                column=col_name,
                test_type="not_null",
                sql=(f"SELECT COUNT(*) AS violation FROM {query_table} WHERE {col_name} IS NULL"),
                description=f"{table_name}.{col_name}: must not be NULL",
            )
        if test == "unique":
            return Check(
                table=table_name,
                column=col_name,
                test_type="unique",
                sql=(
                    f"SELECT COUNT(*) AS violation FROM ("
                    f"SELECT {col_name}, COUNT(*) AS n "
                    f"FROM {query_table} "
                    f"GROUP BY {col_name} HAVING COUNT(*) > 1"
                    f")"
                ),
                description=f"{table_name}.{col_name}: must be unique",
            )
        return None

    # Dict tests: accepted_values, relationships, expression
    if isinstance(test, dict):
        test_type = next(iter(test))
        params = test[test_type]

        if test_type == "accepted_values":
            if isinstance(params, list):
                values = params
                severity = "error"
                enforced = True
                eb = None
            else:
                values = params.get("values", [])
                severity = params.get("severity", "error")
                enforced = params.get("enforced", True)
                eb = params.get("exclude_before")
            quoted = ", ".join(f"'{v}'" for v in values)
            temporal = f" AND created_timestamp >= DATE('{eb}')" if eb else ""
            return Check(
                table=table_name,
                column=col_name,
                test_type="accepted_values",
                sql=(
                    f"SELECT COUNT(*) AS violation "
                    f"FROM {query_table} "
                    f"WHERE {col_name} IS NOT NULL "
                    f"AND {col_name} NOT IN ({quoted})"
                    f"{temporal}"
                ),
                description=(f"{table_name}.{col_name}: values must be in [{', '.join(values)}]"),
                severity=severity,
                enforced=enforced,
                exclude_before=eb,
            )

        if test_type == "relationships":
            if not isinstance(params, dict):
                return None
            to_table = params.get("to_table", "")
            to_column = params.get("to_column", "")
            severity = params.get("severity", "error")
            enforced = params.get("enforced", True)
            eb = params.get("exclude_before")
            # Resolve the target table in the same database
            db = query_table.split(".")[0]
            # For SCD tables, check against _current view if it exists
            target = f"{db}.{to_table}"
            temporal = f" AND child.created_timestamp >= DATE('{eb}')" if eb else ""
            return Check(
                table=table_name,
                column=col_name,
                test_type="relationships",
                sql=(
                    f"SELECT COUNT(*) AS violation "
                    f"FROM {query_table} child "
                    f"LEFT JOIN {target} parent "
                    f"ON child.{col_name} = parent.{to_column} "
                    f"WHERE child.{col_name} IS NOT NULL "
                    f"AND parent.{to_column} IS NULL"
                    f"{temporal}"
                ),
                description=(f"{table_name}.{col_name} -> {to_table}.{to_column}: FK must resolve"),
                severity=severity,
                enforced=enforced,
                exclude_before=eb,
            )

        if test_type == "expression":
            if not isinstance(params, dict):
                return None
            sql_expr = params.get("sql", "")
            desc = params.get("description", f"expression: {sql_expr}")
            severity = params.get("severity", "error")
            enforced = params.get("enforced", True)
            eb = params.get("exclude_before")
            temporal = f" AND created_timestamp >= DATE('{eb}')" if eb else ""
            return Check(
                table=table_name,
                column=col_name,
                test_type="expression",
                sql=(f"SELECT COUNT(*) AS violation FROM {query_table} WHERE NOT ({sql_expr}){temporal}"),
                description=f"{table_name}.{col_name}: {desc}",
                severity=severity,
                enforced=enforced,
                exclude_before=eb,
            )

        # not_null / unique can also appear as dict for severity override
        if test_type == "not_null":
            severity = params.get("severity", "error") if isinstance(params, dict) else "error"
            enforced = params.get("enforced", True) if isinstance(params, dict) else True
            eb = params.get("exclude_before") if isinstance(params, dict) else None
            temporal = f" AND created_timestamp >= DATE('{eb}')" if eb else ""
            return Check(
                table=table_name,
                column=col_name,
                test_type="not_null",
                sql=(f"SELECT COUNT(*) AS violation FROM {query_table} WHERE {col_name} IS NULL{temporal}"),
                description=f"{table_name}.{col_name}: must not be NULL",
                severity=severity,
                enforced=enforced,
                exclude_before=eb,
            )

        if test_type == "unique":
            severity = params.get("severity", "error") if isinstance(params, dict) else "error"
            enforced = params.get("enforced", True) if isinstance(params, dict) else True
            eb = params.get("exclude_before") if isinstance(params, dict) else None
            where_clause = f"WHERE created_timestamp >= DATE('{eb}') " if eb else ""
            return Check(
                table=table_name,
                column=col_name,
                test_type="unique",
                sql=(
                    f"SELECT COUNT(*) AS violation FROM ("
                    f"SELECT {col_name}, COUNT(*) AS n "
                    f"FROM {query_table} "
                    f"{where_clause}"
                    f"GROUP BY {col_name} HAVING COUNT(*) > 1"
                    f")"
                ),
                description=f"{table_name}.{col_name}: must be unique",
                severity=severity,
                enforced=enforced,
                exclude_before=eb,
            )

    return None


def to_ducklake_sql(sql: str, table: str, database: str) -> str:
    """Translate an Athena/Trino check SQL to DuckDB dialect over the DuckLake `current` table.

    - Rewrite the Athena table reference (`{database}.{table}_current` or `{database}.{table}`) to the
      `{tbl}` placeholder the reader's query_ops substitutes with the DuckLake current TABLE.
    - Translate Trino `regexp_like(x, p)` -> DuckDB `regexp_matches(x, p)`. `date_diff`, CURRENT_TIMESTAMP,
      DATE('...'), COUNT(*), NOT IN, IS NULL are already DuckDB-compatible.
    """
    out = sql.replace(f"{database}.{table}_current", "{tbl}").replace(f"{database}.{table}", "{tbl}")
    out = re.sub(r"\bregexp_like\(", "regexp_matches(", out)
    return out


def _uniqueness_sql(column: str) -> str:
    """DuckDB COUNT-of-duplicates violation query for *column* over the `{tbl}` placeholder."""
    dupes = f"SELECT {column}, COUNT(*) n FROM {{tbl}} GROUP BY {column} HAVING COUNT(*) > 1"
    return f"SELECT COUNT(*) AS violation FROM ({dupes}) d"


def build_clause8_checks(spec_yaml: dict, database: str, table_filter: str | None = None) -> list[Check]:
    """Generate the CD.33 clause-8 DuckLake checks (ULID-history uniqueness, current merge-key uniqueness).

    Driven by the ops.yaml `ducklake.clause8_checks` declaration + the field_semantics merge keys.
    Referential integrity is enforced in-writer (L1); the relationships checks in ops.yaml are the L2
    backstop, so no separate referential check is generated here. DuckLake backend only.
    """
    from src.common.ducklake_runtime import resolve_table_spec  # noqa: PLC0415

    cfg = (spec_yaml.get("ducklake") or {}).get("clause8_checks") or {}
    checks: list[Check] = []
    for table in cfg.get("tables", []):
        if table_filter and table != table_filter:
            continue
        spec = resolve_table_spec(table)
        if cfg.get("ulid_history_unique"):
            checks.append(
                Check(
                    table=table,
                    column="ulid",
                    test_type="ulid_history_unique",
                    sql=_uniqueness_sql("ulid"),
                    description=f"{spec.history_table}.ulid: history ULID unique (idempotency PK)",
                    backend="ducklake",
                )
            )
        if cfg.get("current_merge_key_unique"):
            mk = spec.merge_key
            checks.append(
                Check(
                    table=table,
                    column=mk,
                    test_type="current_merge_key_unique",
                    sql=_uniqueness_sql(mk),
                    description=f"{spec.current_table}.{mk}: current has one row per merge key",
                    backend="ducklake",
                )
            )
    return checks
