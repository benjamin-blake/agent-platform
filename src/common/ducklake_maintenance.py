"""DuckLake table-maintenance primitives (T2.18 / CD.33, Decision 81).

Scheduled pipeline replacing the Iceberg-era ops_compaction Lambda. Implements the full
maintenance sequence as composable primitives:

  flush_inlined_data -> merge_adjacent_files -> expire_snapshots ->
  cleanup_old_files -> delete_orphaned_files (+ optional rewrite)

Two cadences:
  run_merge:  daily non-destructive (merge only; no snapshot expiry or file deletion)
  run_gc:     weekly guarded destructive (all five steps, circuit-breaker protected)

Design invariants (CD.33 / Decision 81):
  - Inlining disabled at the connection level (ducklake_default_data_inlining_row_limit=0 in
    the runtime), so flush_inlined_data is a no-op safety net that will always return empty.
  - Destructive GC guardrails are module-level constants -- tunable knobs, but NEVER relaxed
    to make a gate pass (Decision 55). Changing them requires a Decision superseding CD.33.
  - Circuit breaker aborts the entire GC pass (raises, deletes nothing) when a single pass
    would exceed the file-count or byte budget. The abort is the safety-critical invariant.
  - Singleton enforced by reserved_concurrent_executions=1 on the Lambda.
  - No LLM / agent invocation anywhere in this path (CD.33 clause 5 / Decision 81 clause 6).
  - cleanup_all is NEVER passed as True in scheduled runs (CD.33 H1/R-3/O-3/M-3).

T2.19 expansion forward pointer:
  GC_TABLE_SCOPE is scoped to ducklake_smoke_* for T2.18 FP-A. At the Phase-4 maintenance repoint (Decision 84), the scope
  GENERALISES to the full ducklake_ops catalog and the real ops_* business tables
  (ops_recommendations, ops_decisions, etc.). Wiring rides Phase 4; the restore drill is rec-2113 (T2.26 gate).

CALL signature notes (verified against DuckLake v1.0):
  - All maintenance functions are table functions, not SQL CALL procedures.
  - Use SELECT * FROM / FROM syntax.
  - ducklake_merge_adjacent_files takes (catalog, table, schema=schema) per-table
    or (catalog) catalog-wide (no per-table schema column for the catalog-wide form).
  - ducklake_expire_snapshots, ducklake_cleanup_old_files, ducklake_delete_orphaned_files
    are catalog-wide only; they take keyword args (older_than, dry_run, cleanup_all, versions).
  - ducklake_list_files(catalog, table) returns (data_file, data_file_size_bytes, ...).
  - ducklake_snapshots(catalog) returns (snapshot_id, snapshot_time, ...).
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from src.common.ducklake_runtime import CATALOG_ALIAS, SMOKE_CURRENT_TABLE, SMOKE_HISTORY_TABLE, libpq_conninfo

# A bare SQL identifier (meta-schema name) -- guards the f-string-interpolated catalog_stats query.
_META_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# ---------------------------------------------------------------------------
# Scope -- smoke tables only for T2.18 FP-A (production repoint = consolidation Phase 4, Decision 84)
# ---------------------------------------------------------------------------

GC_TABLE_SCOPE: tuple[str, ...] = (SMOKE_HISTORY_TABLE, SMOKE_CURRENT_TABLE)

# HOT_TABLE_SCOPE: higher-frequency merge cadence for high-write-rate tables (T2.18 FP-B, CD.34).
# Scoped to ducklake_smoke_* for T2.18 (same as GC_TABLE_SCOPE). At T2.19, this EXPANDS to the
# real high-write-rate ops_* tables (ops_recommendations, ops_decisions) once the DuckLake writer
# is the live write path. Wiring the numeric tuning + real tables is a T2.19 exit criterion.
HOT_TABLE_SCOPE: tuple[str, ...] = (SMOKE_HISTORY_TABLE, SMOKE_CURRENT_TABLE)

MAINTENANCE_SCOPE_NOTE = (
    "T2.18 FP-A: scope is ducklake_smoke_* only. "
    "T2.19 expands this to the full ducklake_ops catalog and all ops_* business tables "
    "(ops_recommendations, ops_decisions, etc.). "
    "To expand: set GC_TABLE_SCOPE to all relevant tables or introduce a catalog-table-listing "
    "query (information_schema.tables WHERE table_name LIKE 'ops_%')."
)

# ---------------------------------------------------------------------------
# Guardrail constants (CD.33 / Decision 81 clause 6)
# These are tunable knobs -- but tuning them to make a gate pass is a Decision-55 violation.
# ---------------------------------------------------------------------------

SNAPSHOT_RETAIN_DAYS: int = 30
FILE_CLEANUP_GRACE_DAYS: int = 7
SNAPSHOT_FLOOR: int = 2

_DEFAULT_GC_BREAKER_FILE_FRACTION: float = 0.20
_DEFAULT_GC_BREAKER_BYTES: int = 10 * 1024 * 1024 * 1024  # 10 GiB

# Env-tunable thresholds (FP-B co-tuning mechanism, CD.34 / Decision 81 clause 6).
# The constants below are the effective defaults -- sourced from env when set so the Lambda can
# be tuned without a code deploy. Changing them to make a gate pass is a Decision-55 violation.
GC_BREAKER_FILE_FRACTION: float = float(os.environ.get("GC_BREAKER_FILE_FRACTION", _DEFAULT_GC_BREAKER_FILE_FRACTION))
GC_BREAKER_BYTES: int = int(os.environ.get("GC_BREAKER_BYTES", _DEFAULT_GC_BREAKER_BYTES))

# CloudWatch metric namespace for maintenance metrics (CD.33 T2-d).
MAINTENANCE_CLOUDWATCH_NAMESPACE = "DuckLakeMaintenance"


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------


class DuckLakeMaintenanceError(RuntimeError):
    """Loud-fail for any maintenance abort condition (circuit breaker trip, invariant violation).

    Raised in full -- never caught-and-relaxed (Decision 55).
    """


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _ts_str(dt: datetime) -> str:
    """Format a UTC datetime as 'YYYY-MM-DD HH:MM:SS+00' for DuckDB TIMESTAMPTZ literals."""
    utc = dt.astimezone(timezone.utc)
    return utc.strftime("%Y-%m-%d %H:%M:%S+00")


def _count_files(con: Any, catalog: str, table: str) -> int:
    """Count data files tracked by DuckLake for *table* in *catalog*."""
    try:
        row = con.execute(f"SELECT count(*) FROM ducklake_list_files('{catalog}', '{table}')").fetchone()
        return int(row[0]) if row else 0
    except Exception:  # noqa: BLE001 -- absent in edge cases; caller handles 0
        return 0


def _sum_file_bytes(con: Any, catalog: str, table: str) -> int:
    """Sum data_file_size_bytes for *table* in *catalog*; 0 when no files."""
    try:
        row = con.execute(
            f"SELECT coalesce(sum(data_file_size_bytes), 0) FROM ducklake_list_files('{catalog}', '{table}')"
        ).fetchone()
        return int(row[0]) if row else 0
    except Exception:  # noqa: BLE001
        return 0


def _collect_file_paths(con: Any, catalog: str, table: str) -> dict[str, int]:
    """Return {data_file_path: size_bytes} for all tracked data files in *table*."""
    try:
        rows = con.execute(
            f"SELECT data_file, data_file_size_bytes FROM ducklake_list_files('{catalog}', '{table}')"
        ).fetchall()
        return {r[0]: int(r[1] or 0) for r in rows}
    except Exception:  # noqa: BLE001
        return {}


def _dry_run_cleanup_paths(con: Any, catalog: str, older_than: datetime) -> list[str]:
    """Return file paths that cleanup_old_files (dry_run=True) would delete."""
    ts = _ts_str(older_than)
    try:
        rows = con.execute(
            f"SELECT path FROM ducklake_cleanup_old_files('{catalog}', dry_run=True, "
            f"cleanup_all=False, older_than=TIMESTAMPTZ '{ts}')"
        ).fetchall()
        return [r[0] for r in rows]
    except Exception:  # noqa: BLE001
        return []


def _dry_run_orphan_paths(con: Any, catalog: str, older_than: datetime) -> list[str]:
    """Return file paths that delete_orphaned_files (dry_run=True) would delete."""
    ts = _ts_str(older_than)
    try:
        rows = con.execute(
            f"SELECT path FROM ducklake_delete_orphaned_files('{catalog}', dry_run=True, older_than=TIMESTAMPTZ '{ts}')"
        ).fetchall()
        return [r[0] for r in rows]
    except Exception:  # noqa: BLE001
        return []


# ---------------------------------------------------------------------------
# Circuit breaker (CD.33 H1 / Decision 81 clause 6)
# ---------------------------------------------------------------------------


def check_gc_breaker(
    con: Any,
    tables: tuple[str, ...] | list[str],
    *,
    catalog: str = CATALOG_ALIAS,
    file_fraction: float = GC_BREAKER_FILE_FRACTION,
    byte_budget: int = GC_BREAKER_BYTES,
    _now: datetime | None = None,
) -> dict[str, Any]:
    """Pre-GC circuit breaker: abort if the current pass would delete > file_fraction OR > byte_budget.

    Computes the would-delete count/bytes BEFORE any destructive CALL. Raises DuckLakeMaintenanceError
    if either threshold is exceeded. On raise, no destructive call has been issued.

    Returns a stats dict (for CloudWatch emission / VP evidence).
    """
    now = _now or _now_utc()
    older_than = now - timedelta(days=FILE_CLEANUP_GRACE_DAYS)

    # Aggregate file inventory across all scoped tables.
    all_files: dict[str, int] = {}
    for table in tables:
        all_files.update(_collect_file_paths(con, catalog, table))

    total_files = len(all_files)
    total_bytes = sum(all_files.values())

    # Candidates: files that would be deleted by cleanup + orphan (dry-run).
    would_delete_paths = set(
        _dry_run_cleanup_paths(con, catalog, older_than) + _dry_run_orphan_paths(con, catalog, older_than)
    )
    delete_count = len(would_delete_paths)
    delete_bytes = sum(all_files.get(p, 0) for p in would_delete_paths)

    file_fraction_actual = delete_count / total_files if total_files > 0 else 0.0

    stats = {
        "total_files": total_files,
        "total_bytes": total_bytes,
        "would_delete_files": delete_count,
        "would_delete_bytes": delete_bytes,
        "file_fraction": round(file_fraction_actual, 4),
        "breaker_tripped": False,
    }

    if file_fraction_actual > file_fraction:
        stats["breaker_tripped"] = True
        raise DuckLakeMaintenanceError(
            f"GC circuit breaker tripped: would-delete {delete_count}/{total_files} files "
            f"({file_fraction_actual:.1%}) exceeds the {file_fraction:.0%} threshold "
            f"(CD.33 H1 / Decision 81 clause 6). GC aborted; no files deleted. "
            "RCA the file accumulation before next run -- do NOT raise the threshold to pass."
        )

    if delete_bytes > byte_budget:
        stats["breaker_tripped"] = True
        gb = delete_bytes / (1024**3)
        budget_gb = byte_budget / (1024**3)
        raise DuckLakeMaintenanceError(
            f"GC circuit breaker tripped: would-delete {gb:.2f} GiB exceeds the "
            f"{budget_gb:.0f} GiB budget (CD.33 H1 / Decision 81 clause 6). "
            "GC aborted; no files deleted. "
            "RCA the storage accumulation before next run -- do NOT raise the threshold to pass."
        )

    return stats


# ---------------------------------------------------------------------------
# Maintenance primitives (all table-function calls, no CALL syntax)
# ---------------------------------------------------------------------------


def flush_inlined_data(
    con: Any,
    tables: tuple[str, ...] | list[str],
    *,
    catalog: str = CATALOG_ALIAS,
    schema: str = "main",
) -> None:
    """No-op safety net: flush any inlined rows to S3 Parquet.

    Inlining is disabled (ducklake_default_data_inlining_row_limit=0) on every connection
    via ducklake_runtime.open_connection (CD.34 / EC11), so this function always returns
    empty results. It is retained as a safety net in case the row_limit setting drifts.
    """
    for table in tables:
        con.execute(
            f"SELECT * FROM ducklake_flush_inlined_data('{catalog}', table_name='{table}', schema_name='{schema}')"
        ).fetchall()


def merge_adjacent_files(
    con: Any,
    tables: tuple[str, ...] | list[str],
    *,
    catalog: str = CATALOG_ALIAS,
    schema: str = "main",
) -> None:
    """Merge small adjacent Parquet files into larger ones (non-destructive compaction).

    This is the daily non-destructive step. It does NOT delete any S3 objects; it only creates
    merged files and updates the catalog metadata. Safe to run frequently.
    """
    for table in tables:
        con.execute(f"SELECT * FROM ducklake_merge_adjacent_files('{catalog}', '{table}', schema='{schema}')").fetchall()


def expire_snapshots(
    con: Any,
    *,
    catalog: str = CATALOG_ALIAS,
    retain_days: int = SNAPSHOT_RETAIN_DAYS,
    floor: int = SNAPSHOT_FLOOR,
    _now: datetime | None = None,
) -> int:
    """Expire old snapshots, retaining at least `floor` (default 2) snapshots.

    Returns the number of snapshots expired. 0 when the floor guard fires or there is nothing
    to expire. This step does NOT delete S3 data files; cleanup_old_files must follow.

    Guardrail: never expires below the `floor` most-recent snapshots (CD.33 clause 6).
    """
    now = _now or _now_utc()
    history_cutoff = now - timedelta(days=retain_days)

    # Read current snapshot list in descending time order (most recent first).
    rows = con.execute(
        f"SELECT snapshot_id, snapshot_time FROM ducklake_snapshots('{catalog}') ORDER BY snapshot_time DESC"
    ).fetchall()

    if len(rows) <= floor:
        return 0

    # The `floor`-th snapshot (0-indexed) is the oldest we want to RETAIN.
    # Expire only those older than BOTH the history cutoff AND the floor snapshot.
    floor_time: datetime = rows[floor - 1][1]  # time of the last retained snapshot
    # Expire strictly older than the older of the two cutoffs.
    expire_cutoff = min(history_cutoff, floor_time)

    if expire_cutoff >= now:
        return 0

    ts = _ts_str(expire_cutoff)
    expired = con.execute(
        f"SELECT count(*) FROM ducklake_expire_snapshots('{catalog}', older_than=TIMESTAMPTZ '{ts}')"
    ).fetchone()
    return int(expired[0]) if expired else 0


def cleanup_old_files(
    con: Any,
    *,
    catalog: str = CATALOG_ALIAS,
    grace_days: int = FILE_CLEANUP_GRACE_DAYS,
    _now: datetime | None = None,
) -> int:
    """Delete S3 data files associated with expired snapshots (with grace period).

    Only deletes files that have been in the expired state for at least grace_days (default 7).
    Never passes cleanup_all=True (CD.33 H1 / Decision 81 clause 6).

    Returns the number of files deleted.
    """
    now = _now or _now_utc()
    older_than = now - timedelta(days=grace_days)
    ts = _ts_str(older_than)
    result = con.execute(
        f"SELECT count(*) FROM ducklake_cleanup_old_files('{catalog}', dry_run=False, "
        f"cleanup_all=False, older_than=TIMESTAMPTZ '{ts}')"
    ).fetchone()
    return int(result[0]) if result else 0


def delete_orphaned_files(
    con: Any,
    *,
    catalog: str = CATALOG_ALIAS,
    grace_days: int = FILE_CLEANUP_GRACE_DAYS,
    _now: datetime | None = None,
) -> int:
    """Delete S3 files not referenced by any snapshot (orphans), with grace period.

    Only deletes orphans older than grace_days (default 7). Never passes cleanup_all=True.

    Returns the number of files deleted.
    """
    now = _now or _now_utc()
    older_than = now - timedelta(days=grace_days)
    ts = _ts_str(older_than)
    result = con.execute(
        f"SELECT count(*) FROM ducklake_delete_orphaned_files('{catalog}', dry_run=False, older_than=TIMESTAMPTZ '{ts}')"
    ).fetchone()
    return int(result[0]) if result else 0


def rewrite(
    con: Any,
    tables: tuple[str, ...] | list[str],
    *,
    catalog: str = CATALOG_ALIAS,
    schema: str = "main",
) -> None:
    """Optional: rewrite data files (full compaction / column-store optimisation).

    Not included in the default run_merge or run_gc cadences -- invoked explicitly when
    deep compaction is required. More expensive than merge_adjacent_files.
    """
    for table in tables:
        con.execute(f"SELECT * FROM ducklake_rewrite_data_files('{catalog}', '{table}', schema='{schema}')").fetchall()


# ---------------------------------------------------------------------------
# Orchestrators: the two cadences
# ---------------------------------------------------------------------------


def run_merge(
    con: Any,
    tables: tuple[str, ...] | list[str] = GC_TABLE_SCOPE,
    *,
    catalog: str = CATALOG_ALIAS,
    schema: str = "main",
) -> dict[str, Any]:
    """Daily non-destructive cadence: flush + merge only. No snapshot expiry or file deletion.

    Safe to run frequently. Returns a stats dict for CloudWatch emission (includes
    files_before so smoke-gate VP9 can assert files_after_merge <= files_before).
    """
    files_before = sum(_count_files(con, catalog, t) for t in tables)
    flush_inlined_data(con, tables, catalog=catalog, schema=schema)
    merge_adjacent_files(con, tables, catalog=catalog, schema=schema)
    files_after_merge = sum(_count_files(con, catalog, t) for t in tables)
    return {
        "ok": True,
        "action": "merge",
        "tables": list(tables),
        "files_before": files_before,
        "files_after_merge": files_after_merge,
    }


def run_hot_merge(
    con: Any,
    tables: tuple[str, ...] | list[str] = HOT_TABLE_SCOPE,
    *,
    catalog: str = CATALOG_ALIAS,
    schema: str = "main",
) -> dict[str, Any]:
    """Higher-frequency merge-only cadence for high-write-rate tables (T2.18 FP-B / CD.34).

    Runs merge_adjacent_files ONLY -- no snapshot expiry, no cleanup, no orphan deletion.
    Bounds the small-file COUNT between weekly GC passes without reclaiming storage (that is
    the weekly GC cadence's job). Safe to invoke frequently.

    Table scope: HOT_TABLE_SCOPE (ducklake_smoke_* for T2.18). At T2.19, this expands to the
    real high-write-rate ops_* tables -- wiring is a T2.19 exit criterion.

    Returns a stats dict so the smoke gate (VP12) can assert files_after <= files_before and
    confirm no destructive calls were issued.
    """
    files_before = sum(_count_files(con, catalog, t) for t in tables)
    merge_adjacent_files(con, tables, catalog=catalog, schema=schema)
    files_after = sum(_count_files(con, catalog, t) for t in tables)
    return {
        "ok": True,
        "action": "hot_merge",
        "tables": list(tables),
        "files_before": files_before,
        "files_after": files_after,
    }


def _default_pg_connect(conninfo: str) -> Any:
    """psycopg2.connect, imported lazily (the layer provides it; keeps module import dependency-free)."""
    import psycopg2  # noqa: PLC0415

    return psycopg2.connect(conninfo)


def catalog_stats(
    *,
    meta_schema: str,
    dsn: dict[str, str],
    ops_table_filter: str = "ops_%",
    _connect: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    """Read-only catalog observability (D3a / neon-egress measurement obligation).

    Returns the Postgres catalog-metadata footprint -- the bytes a pg_dump exports and the DuckDB
    postgres scanner sequential-COPYs per query (ducklake #859), which is the Neon egress driver this
    plan attacks. Pure metadata read over the catalog's own Postgres tables (psycopg2): no DuckLake
    ATTACH, no data_path needed, and NO merge/expire/cleanup/orphan -- safe to run against production.

    Reports: total catalog-metadata bytes (exact, via pg_total_relation_size), per-metadata-table bytes
    + estimated row counts (reltuples; refreshed by ANALYZE/autovacuum), the snapshot / data_file /
    file_column_stats row estimates pulled out by name, and a best-effort per-ops_*-table data_file
    count (joined from the metadata; degrades to a note if the catalog's column names differ).

    _connect injects the connection factory for tests (defaults to psycopg2.connect).
    """
    if not _META_IDENT_RE.match(meta_schema or ""):
        raise DuckLakeMaintenanceError(f"catalog_stats: invalid meta_schema identifier {meta_schema!r}")

    connect = _connect or _default_pg_connect
    conn = connect(libpq_conninfo(dsn))
    try:
        with conn.cursor() as cur:
            # Exact bytes per metadata table + estimated rows, in one query (no per-table count scan).
            cur.execute(
                "SELECT c.relname, pg_total_relation_size(c.oid), c.reltuples::bigint "
                "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = %s AND c.relkind = 'r' AND c.relname LIKE 'ducklake_%%' "
                "ORDER BY pg_total_relation_size(c.oid) DESC",
                [meta_schema],
            )
            metadata_tables = [
                {"table": r[0], "bytes": int(r[1] or 0), "est_rows": max(int(r[2] or 0), 0)} for r in cur.fetchall()
            ]
            catalog_metadata_bytes = sum(m["bytes"] for m in metadata_tables)

            def _est(name_sub: str) -> int | None:
                for m in metadata_tables:
                    if name_sub in m["table"]:
                        return m["est_rows"]
                return None

            per_ops_table: list[dict[str, Any]] = []
            per_ops_note = ""
            try:
                cur.execute(
                    f"SELECT t.table_name, count(*) FROM {meta_schema}.ducklake_data_file df "
                    f"JOIN {meta_schema}.ducklake_table t ON df.table_id = t.table_id "
                    f"WHERE t.table_name LIKE %s GROUP BY t.table_name ORDER BY t.table_name",
                    [ops_table_filter],
                )
                per_ops_table = [{"table": r[0], "data_file_count": int(r[1] or 0)} for r in cur.fetchall()]
            except Exception as exc:  # noqa: BLE001 -- observability degrades, never crashes the stats action
                per_ops_note = f"per-ops-table breakdown unavailable ({type(exc).__name__}); catalog totals still reported"
    finally:
        conn.close()

    return {
        "ok": True,
        "meta_schema": meta_schema,
        "catalog_metadata_bytes": catalog_metadata_bytes,
        "snapshot_rows_est": _est("snapshot"),
        "data_file_rows_est": _est("data_file"),
        "file_column_stats_rows_est": _est("file_column_stat"),
        "metadata_table_count": len(metadata_tables),
        "metadata_tables": metadata_tables,
        "per_ops_table": per_ops_table,
        "per_ops_table_note": per_ops_note,
    }


def run_gc(
    con: Any,
    tables: tuple[str, ...] | list[str] = GC_TABLE_SCOPE,
    *,
    catalog: str = CATALOG_ALIAS,
    schema: str = "main",
    file_fraction: float = GC_BREAKER_FILE_FRACTION,
    byte_budget: int = GC_BREAKER_BYTES,
    retain_days: int = SNAPSHOT_RETAIN_DAYS,
    grace_days: int = FILE_CLEANUP_GRACE_DAYS,
    floor: int = SNAPSHOT_FLOOR,
    _now: datetime | None = None,
) -> dict[str, Any]:
    """Weekly guarded destructive cadence: full maintenance sequence with circuit breaker.

    Sequence:
      1. flush_inlined_data  (no-op safety net)
      2. merge_adjacent_files  (non-destructive prep)
      3. circuit breaker check  (pre-destructive, raises DuckLakeMaintenanceError on trip)
      4. expire_snapshots  (marks old snapshots as expired; no S3 deletion yet)
      5. cleanup_old_files  (delete S3 files for expired snapshots, with grace)
      6. delete_orphaned_files  (delete unreferenced S3 files, with grace)

    Returns a stats dict for CloudWatch emission. Raises DuckLakeMaintenanceError on breaker trip.
    """
    now = _now or _now_utc()

    files_before = sum(_count_files(con, catalog, t) for t in tables)

    flush_inlined_data(con, tables, catalog=catalog, schema=schema)
    merge_adjacent_files(con, tables, catalog=catalog, schema=schema)

    breaker_stats = check_gc_breaker(
        con,
        tables,
        catalog=catalog,
        file_fraction=file_fraction,
        byte_budget=byte_budget,
        _now=now,
    )

    expired = expire_snapshots(con, catalog=catalog, retain_days=retain_days, floor=floor, _now=now)
    cleaned = cleanup_old_files(con, catalog=catalog, grace_days=grace_days, _now=now)
    orphaned = delete_orphaned_files(con, catalog=catalog, grace_days=grace_days, _now=now)

    files_after = sum(_count_files(con, catalog, t) for t in tables)

    return {
        "ok": True,
        "action": "gc",
        "tables": list(tables),
        "files_before": files_before,
        "files_after": files_after,
        "snapshots_expired": expired,
        "files_cleaned": cleaned,
        "orphans_deleted": orphaned,
        "breaker_stats": breaker_stats,
    }
