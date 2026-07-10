"""DuckLake table-lifecycle DDL (T2.17/T2.19, CD.33, Decision 81; split from ducklake_runtime).

Owner concern: creating and reconciling the physical history/current table pairs. Imports the
table-spec resolver and DDL builder FROM ducklake_scd2_schema (+ stdlib) only, and NEVER from the
ducklake_runtime facade (Decision 80 acyclic-import discipline) or from ducklake_writes -- there is
no tables<->writes call in either direction.
"""

from __future__ import annotations

from typing import Any

from src.common.ducklake_scd2_schema import CATALOG_ALIAS, _column_ddl, resolve_table_spec

# ---------------------------------------------------------------------------
# Table DDL -- CREATE + partition transforms BEFORE first write (post-ALTER-only, M-5)
# ---------------------------------------------------------------------------


def create_scd2_tables(con: Any, *, table: str | None = None, force_recreate: bool = False) -> None:
    """Create the history + current tables for *table* and partition them BEFORE first write.

    `table=None` is the smoke pair (T2.17); a name selects an ops_tables entry (T2.19). The column
    list, the merge-key bucket, and the day(created_timestamp) history partition all come from the
    resolved spec, so the DDL never drifts from the gate.

    Partition transforms are post-ALTER-only (CD.33 M-5): they MUST be applied before any row lands.
    `force_recreate=True` drops both tables first -- the backfill's resurrection-loop guard: a
    re-run DROPs + recreates rather than appending onto a half-populated catalog. Re-ALTER on an
    already-partitioned table is idempotent in DuckLake v1.0, so the non-force path converges too.
    """
    spec = resolve_table_spec(table)
    history = f"{CATALOG_ALIAS}.{spec.history_table}"
    columns = _column_ddl(spec)

    if spec.write_mode == "append_only":
        if force_recreate:
            con.execute(f"DROP TABLE IF EXISTS {history}")
        con.execute(f"CREATE TABLE IF NOT EXISTS {history} ({columns})")
        con.execute(f"ALTER TABLE {history} SET PARTITIONED BY ({spec.partition_history})")
        return

    current = f"{CATALOG_ALIAS}.{spec.current_table}"
    if force_recreate:
        con.execute(f"DROP TABLE IF EXISTS {history}")
        con.execute(f"DROP TABLE IF EXISTS {current}")

    con.execute(f"CREATE TABLE IF NOT EXISTS {history} ({columns})")
    con.execute(f"CREATE TABLE IF NOT EXISTS {current} ({columns})")

    # Partition transforms BEFORE first write: history by day(created_timestamp) for date-range
    # pruning; current by bucket(N, merge_key) to bound the single-key lookup/MERGE scan footprint.
    con.execute(f"ALTER TABLE {history} SET PARTITIONED BY ({spec.partition_history})")
    con.execute(f"ALTER TABLE {current} SET PARTITIONED BY ({spec.partition_current})")


def reconcile_table_columns(con: Any, *, table: str) -> dict[str, list[str]]:
    """Add any spec columns missing from the physical history+current tables (idempotent via introspection).

    Reads the column spec from the field_semantics.yaml contract via resolve_table_spec, introspects
    the physical tables using DuckDB information_schema, and issues ALTER TABLE ADD COLUMN for each
    spec column absent from the live table. Idempotency is guaranteed by the pre-check (not SQL IF NOT
    EXISTS -- there is no ADD COLUMN IF NOT EXISTS precedent in DuckLake v1.0). Never DROPs.

    Args:
        con: Open DuckDB connection with the production catalog attached.
        table: ops_* table logical name (e.g. 'ops_recommendations').

    Returns:
        Dict with 'added_history' and 'added_current' lists of column names added per table.
    """
    spec = resolve_table_spec(table)
    history_fq = f"{CATALOG_ALIAS}.{spec.history_table}"

    def _physical_columns(table_fq: str) -> set[str]:
        rows = con.execute(
            f"SELECT column_name FROM information_schema.columns "
            f"WHERE table_catalog = '{CATALOG_ALIAS}' "
            f"AND table_name = '{table_fq.split('.')[-1]}' "
            f"ORDER BY ordinal_position"
        ).fetchall()
        if not rows:
            rows = con.execute(f"PRAGMA table_info('{table_fq}')").fetchall()
            return {r[1] for r in rows}
        return {r[0] for r in rows}

    added_history: list[str] = []
    added_current: list[str] = []

    tables_to_reconcile: list[tuple[str, list[str]]] = [(history_fq, added_history)]
    if spec.write_mode != "append_only":
        current_fq = f"{CATALOG_ALIAS}.{spec.current_table}"
        tables_to_reconcile.append((current_fq, added_current))

    for table_fq, added_list in tables_to_reconcile:
        existing = _physical_columns(table_fq)
        for col_name, col_spec in spec.fields.items():
            if col_name in existing:
                continue
            sql_type = col_spec.get("sql_type", "VARCHAR")
            nullable = col_spec.get("nullable", True)
            null_clause = "" if nullable else " NOT NULL"
            con.execute(f"ALTER TABLE {table_fq} ADD COLUMN {col_name} {sql_type}{null_clause}")
            added_list.append(col_name)

    return {"added_history": added_history, "added_current": added_current}
