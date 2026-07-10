"""DuckLake closed read-boundary primitives (Decision 84 I-3; split from ducklake_runtime).

Owner concern: every read path over the current/history projections, plus the read-only SQL
guard that is the application-layer half of the closed reader boundary (OQ.7). Imports the
named-read registry and table-spec resolver FROM ducklake_scd2_schema (+ stdlib) only, and NEVER
from the ducklake_runtime facade (Decision 80 acyclic-import discipline).
"""

from __future__ import annotations

import re
from typing import Any

from src.common.ducklake_scd2_schema import (
    CATALOG_ALIAS,
    NAMED_READS,
    DuckLakeRuntimeError,
    SchemaGateError,
    resolve_table_spec,
)

# ---------------------------------------------------------------------------
# Read primitive
# ---------------------------------------------------------------------------


def read_current(
    con: Any,
    *,
    table: str | None = None,
    rec_id: str | None = None,
    key: str | None = None,
    key_column: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Return rows from the current write-through projection (latest version per merge key).

    `table=None` reads the smoke current table (T2.17); a name selects an ops_tables entry (T2.19).
    `key` (or the back-compat `rec_id` alias) filters to a single value; `key_column` names the
    filtered column and is VALIDATED against the spec (defaults to the merge key). The structural
    (column, value) pair replaces SQL-fragment filters at this boundary (rec-2170: a value bound
    against the wrong column returned a silent false zero). `limit` bounds the row count.
    """
    spec = resolve_table_spec(table)
    if spec.current_table is None:
        raise DuckLakeRuntimeError(
            f"table {spec.table!r} is append_only: read_current is not supported "
            "(write_mode=append_only has no current write-through projection; "
            "read from the history table via read_history() instead)"
        )
    cols = ", ".join(c for c, _ in spec.ordered_columns)
    sql = f"SELECT {cols} FROM {CATALOG_ALIAS}.{spec.current_table}"
    filter_value = key if key is not None else rec_id
    filter_column = key_column if key_column is not None else spec.merge_key
    if filter_column not in spec.fields:
        raise DuckLakeRuntimeError(
            f"unknown filter column {filter_column!r} for {spec.current_table}: not in the field-semantics contract"
        )
    params: list[Any] = []
    if filter_value is not None:
        sql += f" WHERE {filter_column} = ?"
        params.append(filter_value)
    sql += f" ORDER BY {spec.merge_key}"
    if limit is not None:
        sql += f" LIMIT {int(limit)}"
    cursor = con.execute(sql, params) if params else con.execute(sql)
    col_names = [desc[0] for desc in cursor.description]
    return [dict(zip(col_names, row)) for row in cursor.fetchall()]


def read_history(
    con: Any, *, table: str | None = None, key: str | None = None, limit: int | None = None
) -> list[dict[str, Any]]:
    """Return append-history rows for *table* (optionally a single merge key), newest-first."""
    spec = resolve_table_spec(table)
    cols = ", ".join(c for c, _ in spec.ordered_columns)
    sql = f"SELECT {cols} FROM {CATALOG_ALIAS}.{spec.history_table}"
    params: list[Any] = []
    if key is not None:
        sql += f" WHERE {spec.merge_key} = ?"
        params.append(key)
    sql += " ORDER BY last_updated_timestamp DESC, ulid DESC"
    if limit is not None:
        sql += f" LIMIT {int(limit)}"
    cursor = con.execute(sql, params) if params else con.execute(sql)
    col_names = [desc[0] for desc in cursor.description]
    return [dict(zip(col_names, row)) for row in cursor.fetchall()]


def assert_read_only_sql(sql: str) -> None:
    """Loud-fail unless *sql* is a read-only statement (SELECT/WITH only).

    The reader holds the full Neon catalog credential; S3-read-only IAM blocks Parquet writes but NOT
    Postgres catalog DDL (DROP/ALTER TABLE on the DuckLake metadata). This verb guard is the
    application-layer half of the closed read boundary (OQ.7): a non-SELECT statement never reaches
    the catalog. Reject anything whose first keyword is not SELECT or WITH (CTE) -- this also blocks
    a multi-statement payload (the leading verb of a `SELECT 1; DROP TABLE x` is SELECT, but DuckDB
    rejects multi-statement in one execute; the guard plus single-statement execution close it).
    """
    if not re.match(r"^\s*(?:SELECT|WITH)\b", sql, re.IGNORECASE):
        raise SchemaGateError(
            "read-only boundary: only SELECT/WITH statements may execute on the reader path "
            f"(got {sql.strip()[:60]!r}). Catalog DDL/DML is denied at the closed boundary (OQ.7)."
        )
    if ";" in sql.rstrip().rstrip(";"):
        raise SchemaGateError("read-only boundary: multi-statement SQL is rejected on the reader path (OQ.7).")


def named_read(con: Any, *, verb: str, params: dict[str, Any] | None = None, limit: int | None = None) -> list[dict[str, Any]]:
    """Execute a pre-established read verb from the NAMED_READS registry (Decision 84 I-3).

    The SQL is server-side registry content; the caller supplies only the verb name and named
    bind params. Param presence is validated against the verb's declared param list; `{tbl}` and
    `{hist}` resolve to the verb's table current/history pair. Loud-fail on an unknown verb or a
    missing/extra param.

    `limit` (T1.16 c1): a server-side integer-cast trailing LIMIT appended to the rendered SQL, for
    `paginable` verbs only -- no caller SQL crosses the boundary (Decision 84 I-3). Loud-fail if
    `limit` is supplied for a non-paginable verb (its SQL has no total-order guarantee for a
    caller-visible bound).
    """
    entry = NAMED_READS.get(verb)
    if entry is None:
        raise DuckLakeRuntimeError(f"unknown read verb {verb!r}: expected one of {sorted(NAMED_READS)}")
    supplied = dict(params or {})
    if set(supplied) != set(entry.params):
        raise DuckLakeRuntimeError(f"read verb {verb!r} requires params {list(entry.params)}; got {sorted(supplied)}")
    if limit is not None and not entry.paginable:
        raise DuckLakeRuntimeError(f"read verb {verb!r} is not paginable: `limit` is not accepted")
    spec = resolve_table_spec(entry.table)
    final_sql = entry.sql.replace("{tbl}", f"{CATALOG_ALIAS}.{spec.current_table}").replace(
        "{hist}", f"{CATALOG_ALIAS}.{spec.history_table}"
    )
    if limit is not None:
        final_sql += f" LIMIT {int(limit)}"
    bound = [supplied[name] for name in entry.params]
    cursor = con.execute(final_sql, bound) if bound else con.execute(final_sql)
    col_names = [desc[0] for desc in cursor.description]
    return [dict(zip(col_names, row)) for row in cursor.fetchall()]


def query_current(con: Any, *, table: str, sql: str, params: list[Any] | tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    """Run a read-only *sql* over the current projection of *table*. Use `{tbl}` for the table ref.

    Mirrors the Reader.query semantics: the caller supplies a SELECT referencing `{tbl}`; `?` binds
    params. The reader Lambda exposes this so the portal/sync read paths can push predicates down.
    A read-only verb guard (assert_read_only_sql) rejects any non-SELECT/WITH statement BEFORE it
    reaches the catalog -- catalog DDL is not blocked by the S3-read-only IAM, so the guard is the
    application-layer half of the closed read boundary (OQ.7 / CD.33 clause 6).
    """
    assert_read_only_sql(sql)
    spec = resolve_table_spec(table)
    if spec.current_table is None:
        raise DuckLakeRuntimeError(
            f"table {spec.table!r} is append_only: query_current is not supported "
            "(write_mode=append_only has no current write-through projection)"
        )
    final_sql = sql.replace("{tbl}", f"{CATALOG_ALIAS}.{spec.current_table}")
    cursor = con.execute(final_sql, list(params)) if params else con.execute(final_sql)
    col_names = [desc[0] for desc in cursor.description]
    return [dict(zip(col_names, row)) for row in cursor.fetchall()]
