"""ducklake_maintenance Lambda entrypoint (T2.18 / CD.33, Decision 81).

Singleton maintenance Lambda invoked on two EventBridge schedules:
  daily  (cron 04:00 UTC): action=merge  -- non-destructive merge only
  weekly (cron 05:00 UTC Sunday): action=gc  -- full guarded GC with circuit breaker

Also supports action=breaker_probe (forced-threshold test for VP step 11).

T2.19 recs cutover adds OPERATIONAL admin actions invoked over 443 via `aws lambda invoke` (NOT
public Function URLs, NOT agent surfaces): catalog_reinit (rec-2099 fix -- drop the squatting
meta-schema + re-init at the production DATA_PATH) and restore_drill (pg_dump->pg_restore +
read-your-write DR gate). These target the PRODUCTION catalog (ducklake_ops) via explicit event
params; the SCHEDULED merge/gc cadence stays on the smoke catalog (ducklake_smoke, relocated off
ducklake_ops -- rec-2099 root-cause). (The TEMPORARY seed_ops_recommendations bootstrap action was
removed at the 2026-06-09 recs sign-off -- the closed boundary now admits recs writes only via the
portal `file_rec`/`update_rec` -> writer path, Decision 81 cl.7.)

No LLM / agent invocation anywhere in this path (CD.33 clause 5 / Decision 81 clause 6).
Singleton enforced by reserved_concurrent_executions=1 (Decision 81 clause 6; see Terraform).

Scheduled table scope: ducklake_smoke_* (now under the ducklake_smoke meta-schema).
See src/common/ducklake_maintenance.py::MAINTENANCE_SCOPE_NOTE.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any

from src.common import catalog_dr
from src.common import ducklake_maintenance as maint
from src.common import ducklake_runtime as rt

DATA_PATH = os.environ.get("DUCKLAKE_DATA_PATH", rt.SMOKE_DATA_PATH)
META_SCHEMA = os.environ.get("DUCKLAKE_META_SCHEMA", rt.SMOKE_META_SCHEMA)
EXTENSION_DIRECTORY = os.environ.get("DUCKLAKE_EXTENSION_DIRECTORY", rt.LAMBDA_EXTENSION_DIRECTORY)

# A SQL identifier (meta-schema name) -- guards the few f-string-interpolated DDL sites below.
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# GC circuit-breaker thresholds: sourced from env when set (FP-B co-tuning, CD.34).
# Env overrides the module-level defaults but NOT the forced_* event fields (which take precedence).
# Tuning these to pass a gate is a Decision-55 violation.
_ENV_GC_BREAKER_FILE_FRACTION: float = float(os.environ.get("GC_BREAKER_FILE_FRACTION", maint.GC_BREAKER_FILE_FRACTION))
_ENV_GC_BREAKER_BYTES: int = int(os.environ.get("GC_BREAKER_BYTES", maint.GC_BREAKER_BYTES))

# Table scope: ducklake_smoke_* (T2.18 FP-A/B only -- see MAINTENANCE_SCOPE_NOTE for T2.19 expansion).
_SCOPE_TABLES = maint.GC_TABLE_SCOPE
_HOT_SCOPE_TABLES = maint.HOT_TABLE_SCOPE

# Forced-threshold breaker_probe: set these to guaranteed-trip values. The probe writes many small
# files before invoking so the dry-run count lands above the threshold, then checks that the
# MaintenanceBreakerTrip metric was emitted and that no files were deleted.
_BREAKER_PROBE_FILE_FRACTION = 0.0  # 0% -> any 1 deletable file trips it
_BREAKER_PROBE_BYTE_BUDGET = 0  # 0 bytes -> any file trips it


def _open_connection() -> Any:
    """Open a maintenance-scoped baked-extension connection to the Neon catalog.

    The SCHEDULED merge/gc/hot_merge cadence operates on the smoke catalog (`ducklake_smoke` at the
    smoke DATA_PATH); the OPERATIONAL actions (catalog_reinit / seed / restore_drill) manage their own
    connections against the production catalog via explicit event params.
    """
    dsn = rt.fetch_dsn()
    return rt.open_connection(dsn=dsn, data_path=DATA_PATH, meta_schema=META_SCHEMA, extension_directory=EXTENSION_DIRECTORY)


def _make_metric_sink(profile: str | None = None) -> Any:
    """Build a CloudWatch metric sink for the DuckLakeMaintenance namespace."""
    return rt.make_metric_sink(namespace=maint.MAINTENANCE_CLOUDWATCH_NAMESPACE, profile=profile)


def _emit_maintenance_metric(name: str, value: float, *, profile: str | None = None) -> None:
    rt.emit_metric(name, value, namespace=maint.MAINTENANCE_CLOUDWATCH_NAMESPACE, profile=profile)


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------


def action_merge(event: dict[str, Any], con: Any) -> dict[str, Any]:
    """Daily non-destructive merge: flush_inlined_data + merge_adjacent_files.

    Accepts force_recreate_tables=True (re-creates the smoke tables, idempotent re-run).
    """
    if event.get("force_recreate_tables"):
        rt.create_scd2_tables(con, force_recreate=True)

    t0 = time.perf_counter()
    result = maint.run_merge(con, _SCOPE_TABLES)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    result["elapsed_ms"] = round(elapsed_ms, 2)

    _emit_maintenance_metric("MergeDurationMs", elapsed_ms)
    _emit_maintenance_metric("FilesBeforeMerge", float(result["files_before"]))
    _emit_maintenance_metric("FilesAfterMerge", float(result["files_after_merge"]))
    return result


def action_gc(event: dict[str, Any], con: Any) -> dict[str, Any]:
    """Weekly guarded GC: full five-step sequence with circuit breaker.

    Accepts force_* event fields per Lambda convention:
      force_recreate_tables -- drop/recreate smoke tables before GC (test harness)
      force_file_fraction   -- override GC_BREAKER_FILE_FRACTION (test; not used in scheduled runs)
      force_byte_budget     -- override GC_BREAKER_BYTES (test; not used in scheduled runs)
    """
    if event.get("force_recreate_tables"):
        rt.create_scd2_tables(con, force_recreate=True)

    file_fraction = float(event.get("force_file_fraction", _ENV_GC_BREAKER_FILE_FRACTION))
    byte_budget = int(event.get("force_byte_budget", _ENV_GC_BREAKER_BYTES))

    t0 = time.perf_counter()
    result = maint.run_gc(con, _SCOPE_TABLES, file_fraction=file_fraction, byte_budget=byte_budget)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    result["elapsed_ms"] = round(elapsed_ms, 2)

    _emit_maintenance_metric("GcDurationMs", elapsed_ms)
    _emit_maintenance_metric("FilesBeforeGc", float(result["files_before"]))
    _emit_maintenance_metric("FilesAfterGc", float(result["files_after"]))
    _emit_maintenance_metric("SnapshotsExpired", float(result["snapshots_expired"]))
    _emit_maintenance_metric("FilesCleaned", float(result["files_cleaned"]))
    _emit_maintenance_metric("OrphansDeleted", float(result["orphans_deleted"]))
    _emit_maintenance_metric("MaintenanceBreakerTrip", 0.0)
    return result


def action_hot_merge(event: dict[str, Any], con: Any) -> dict[str, Any]:
    """Higher-frequency merge-only cadence (T2.18 FP-B / CD.34).

    Invokes merge_adjacent_files ONLY over HOT_TABLE_SCOPE. No snapshot expiry, no file
    deletion. Bounds the small-file COUNT between weekly GC passes without reclaiming storage.
    Table scope is ducklake_smoke_* for T2.18; expands to real high-write-rate ops_* at T2.19.

    Accepts force_recreate_tables=True (re-creates the smoke tables, idempotent re-run).
    """
    if event.get("force_recreate_tables"):
        rt.create_scd2_tables(con, force_recreate=True)

    t0 = time.perf_counter()
    result = maint.run_hot_merge(con, _HOT_SCOPE_TABLES)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    result["elapsed_ms"] = round(elapsed_ms, 2)

    _emit_maintenance_metric("HotMergeDurationMs", elapsed_ms)
    _emit_maintenance_metric("FilesBeforeHotMerge", float(result["files_before"]))
    _emit_maintenance_metric("FilesAfterHotMerge", float(result["files_after"]))
    return result


def action_breaker_probe(event: dict[str, Any], con: Any) -> dict[str, Any]:
    """Forced-threshold circuit-breaker test (VP step 11).

    Overrides thresholds to zero so the breaker ALWAYS trips on any deletable file.
    Asserts that check_gc_breaker raises DuckLakeMaintenanceError and that no files are
    deleted.

    On trip: re-raises DuckLakeMaintenanceError. The handler's outer catch emits
    MaintenanceBreakerTrip=1 exactly once. Do NOT emit it here -- the outer catch is the
    single emit point for all DuckLakeMaintenanceError paths (H1 fix: no double-emit).

    Returns {"ok": False, "breaker_tripped": True, "error_type": "breaker", "error": ...}
    with status 500 so the smoke-test gate can assert the loud-fail.
    """
    maint.check_gc_breaker(
        con,
        _SCOPE_TABLES,
        file_fraction=_BREAKER_PROBE_FILE_FRACTION,
        byte_budget=_BREAKER_PROBE_BYTE_BUDGET,
    )
    return {"ok": True, "breaker_tripped": False, "message": "Breaker did NOT trip (no deletable files in probe)"}


# ---------------------------------------------------------------------------
# Operational actions (T2.19 recs cutover) -- invoked over 443 via `aws lambda invoke`, NOT public
# Function URLs and NOT agent surfaces. They target the PRODUCTION catalog (ducklake_ops) via explicit
# event params and manage their own connections (the scheduled merge/gc stay on the smoke catalog).
# catalog_reinit + restore_drill are retained as operational DR ops. The TEMPORARY
# seed_ops_recommendations bootstrap was removed at the 2026-06-09 recs sign-off (closed boundary --
# recs writes now transit only the portal -> writer path, Decision 81 cl.7).
# ---------------------------------------------------------------------------


def _require_identifier(name: Any) -> str:
    """Validate *name* is a bare SQL identifier (guards the f-string-interpolated meta-schema DDL)."""
    if not isinstance(name, str) or not _IDENTIFIER_RE.match(name):
        raise rt.DuckLakeRuntimeError(f"invalid SQL identifier {name!r} (expected [A-Za-z_][A-Za-z0-9_]*)")
    return name


def _drop_meta_schema(meta_schema: str, *, recreate: bool = False) -> bool:
    """Break-glass: DROP a DuckLake meta-schema in Neon Postgres (psycopg2). Returns True if it ran.

    The DuckLake DATA_PATH pin lives in this meta-schema's metadata tables, so dropping it is what
    makes a re-ATTACH at a new DATA_PATH possible. DESTRUCTIVE -- the caller has confirmed the state
    is disposable.

    `recreate=True` re-creates the schema EMPTY after the drop. DuckLake v1.0 does not auto-create
    the Postgres meta-schema on ATTACH -- it errors "Schema not found" -- so a reinit/init must leave an
    empty schema for the next ATTACH to initialize its metadata tables into (at the new DATA_PATH).
    """
    import psycopg2  # noqa: PLC0415

    _require_identifier(meta_schema)
    conn = psycopg2.connect(rt.libpq_conninfo(rt.fetch_dsn()))
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(f"DROP SCHEMA IF EXISTS {meta_schema} CASCADE")
            if recreate:
                cur.execute(f"CREATE SCHEMA IF NOT EXISTS {meta_schema}")
    finally:
        conn.close()
    return True


def action_catalog_reinit(event: dict[str, Any], _con: Any) -> dict[str, Any]:
    """OPERATIONAL break-glass: drop the squatting meta-schema + re-initialize it at DATA_PATH (rec-2099).

    T2.17 smoke initialized `ducklake_ops` at the smoke DATA_PATH; DuckLake pins DATA_PATH per
    meta-schema, so a production ATTACH at `ducklake/` fails until the meta-schema is dropped and
    re-initialized. DESTRUCTIVE + IRREVERSIBLE: the existing (disposable smoke) catalog state is
    discarded. The first ATTACH to the now-empty meta-schema initializes it, pinning the new DATA_PATH.
    """
    data_path = event.get("data_path")
    if not isinstance(data_path, str) or not data_path.startswith("s3://"):
        raise rt.DuckLakeRuntimeError("catalog_reinit requires a 'data_path' s3:// URI (the production DuckLake path)")
    raw_schema = event.get("meta_schema")
    if not raw_schema:
        raise rt.DuckLakeRuntimeError(
            "catalog_reinit requires an EXPLICIT 'meta_schema' (no production default: a no-arg invoke "
            "must never drop the live catalog -- destructive-action guard, Decision 84)"
        )
    if event.get("confirm") != raw_schema:
        raise rt.DuckLakeRuntimeError(
            f"catalog_reinit is DESTRUCTIVE and IRREVERSIBLE for meta_schema {raw_schema!r}: "
            f"pass confirm={raw_schema!r} to proceed"
        )
    meta_schema = _require_identifier(raw_schema)

    # Drop the squatting catalog AND leave an empty meta-schema for the ATTACH to initialize into.
    dropped = _drop_meta_schema(meta_schema, recreate=True)

    con = rt.open_connection(
        dsn=rt.fetch_dsn(), data_path=data_path, meta_schema=meta_schema, extension_directory=EXTENSION_DIRECTORY
    )
    try:
        con.execute("SELECT 1")  # ATTACH proof at the new path (initializes the empty meta-schema)
    finally:
        con.close()
    return {
        "ok": True,
        "meta_schema": meta_schema,
        "data_path": data_path,
        "dropped_existing": dropped,
        "reinitialized": True,
    }


def action_restore_drill(event: dict[str, Any], _con: Any) -> dict[str, Any]:
    """OPERATIONAL DR gate: prove a custom-format pg_dump round-trips via pg_restore + read-your-write.

    Self-contained and PRODUCTION-SAFE: initializes a SCRATCH meta-schema at a scratch DATA_PATH,
    writes a known SCD2 row, pg_dumps ONLY that schema (--schema, --format=custom), DROPs it,
    pg_restores, then re-ATTACHes and verifies the known row reads back. Loud-fail (CatalogDrError)
    stops the cutover (Decision 55). Requires the pgclient layer (pg_dump/pg_restore) on this Lambda.
    """
    import tempfile  # noqa: PLC0415

    scratch_meta = _require_identifier(event.get("scratch_meta", "ducklake_restore_drill"))
    # Scratch data lives UNDER the production prefix (ducklake/_restore_drill/) so the maintenance S3
    # grant already covers it -- no extra IAM prefix. Bucket is derived from the smoke path's bucket.
    _bucket = rt.SMOKE_DATA_PATH.split("/")[2]
    scratch_path = event.get("scratch_data_path") or f"s3://{_bucket}/ducklake/_restore_drill/"
    probe_id = event.get("probe_id", "drill-probe")
    dsn = rt.fetch_dsn()

    def _attach() -> Any:
        return rt.open_connection(
            dsn=dsn, data_path=scratch_path, meta_schema=scratch_meta, extension_directory=EXTENSION_DIRECTORY
        )

    # 1. Clean start (drop + recreate empty so ATTACH can initialize) + seed a known row into the
    # scratch catalog (smoke pair, isolated meta-schema).
    _drop_meta_schema(scratch_meta, recreate=True)
    con = _attach()
    try:
        rt.create_scd2_tables(con, force_recreate=True)
        rt.write_scd2(con, {"rec_id": probe_id, "payload": "restore-drill"})
    finally:
        con.close()

    with tempfile.TemporaryDirectory(prefix="restore-drill-") as tmp:
        dump_path = f"{tmp}/scratch.dump"
        # 2. pg_dump ONLY the scratch meta-schema (--format=custom), then 3. DROP it.
        cmd = catalog_dr.build_pg_dump_cmd(catalog_dr.dsn_uri(dsn), dump_path, schema=scratch_meta)
        result = subprocess_run(cmd)
        if result.returncode != 0:
            raise catalog_dr.CatalogDrError(f"restore-drill pg_dump exited {result.returncode}: {result.stderr.strip()[:500]}")
        _drop_meta_schema(scratch_meta)
        # 4. pg_restore the dump (loud-fail on non-zero).
        catalog_dr.run_pg_restore(dump_path, dsn)

    # 5. Re-ATTACH the restored scratch catalog + verify read-your-write.
    con = _attach()
    try:
        rows = rt.read_current(con, rec_id=probe_id)
    finally:
        con.close()
    _drop_meta_schema(scratch_meta)  # cleanup

    restored = bool(rows) and rows[0].get("rec_id") == probe_id
    if not restored:
        raise catalog_dr.CatalogDrError(
            f"restore-drill read-your-write FAILED: probe {probe_id!r} not found after pg_restore -- STOP (Decision 55)"
        )
    return {
        "ok": True,
        "scratch_meta": scratch_meta,
        "probe_id": probe_id,
        "restored": True,
        "pg_version": catalog_dr.PINNED_PG_VERSION,
    }


def subprocess_run(cmd: list[str]) -> Any:
    """Thin wrapper around subprocess.run (capture, text, no check) -- injection point for tests."""
    import subprocess  # noqa: PLC0415

    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)


def action_clone_catalog(event: dict[str, Any], _con: Any) -> dict[str, Any]:
    """OQ.12 canary rehearsal read-clone via Neon native copy-on-write branch (Decision 100).

    The orchestrator (ducklake_neon_smoke_test.canary_rehearsal) owns the branch lifecycle:
    it creates the branch before invoking this action and deletes it in its finally block.
    This action receives branch_host from the event, builds the branch DSN (prod role/password/
    dbname inherited via fetch_dsn, branch endpoint host substituted), ATTACHes the candidate
    DuckDB engine to meta_schema=ducklake_ops, and reads real catalog metadata read-only via
    information_schema. Raises CatalogDrError on ATTACH failure or empty result (Decision 55).

    Never invokes pg_dump, pg_restore, CREATE DATABASE, or DROP DATABASE. Never mutates the
    live ducklake_ops catalog. Never writes the production S3 DATA_PATH.
    """
    branch_host = event.get("branch_host")
    if not branch_host:
        raise catalog_dr.CatalogDrError(
            "clone_catalog: branch_host is required in the event -- orchestrator must create "
            "a Neon branch and pass its endpoint host (Decision 100 / Decision 55)"
        )

    prod_dsn = rt.fetch_dsn()
    branch_dsn = {**prod_dsn, "host": branch_host}
    meta_schema = "ducklake_ops"

    con = rt.open_connection(
        dsn=branch_dsn,
        data_path=rt.SMOKE_DATA_PATH,
        meta_schema=meta_schema,
        extension_directory=EXTENSION_DIRECTORY,
    )
    try:
        rows = con.execute("SELECT schema_name FROM information_schema.schemata LIMIT 1").fetchall()
        if not rows:
            raise catalog_dr.CatalogDrError(
                "clone_catalog FAIL: empty information_schema.schemata on Neon branch -- "
                "candidate DuckDB engine could not read the production catalog clone (Decision 55)"
            )
    finally:
        con.close()

    return {
        "ok": True,
        "meta_schema": meta_schema,
        "branch_host": branch_host,
        "cloned": True,
    }


def action_reconcile_columns(event: dict[str, Any], _con: Any) -> dict[str, Any]:
    """OPERATIONAL: add any spec columns missing from the physical ops_* history+current tables.

    Non-destructive ALTER TABLE ADD COLUMN (never DROP). Idempotent: a second run is a no-op
    because reconcile_table_columns checks physical columns before ALTER. Requires EXPLICIT
    data_path + meta_schema event params (refuses no-arg invokes so it can never hit the smoke
    catalog -- mirrors catalog_reinit's guard, Decision 84/81).

    Expected event:
        {"action": "reconcile_columns", "data_path": "s3://.../ducklake/",
         "meta_schema": "ducklake_ops", "table": "ops_recommendations"}
    """
    data_path = event.get("data_path")
    if not isinstance(data_path, str) or not data_path.startswith("s3://"):
        raise rt.DuckLakeRuntimeError(
            "reconcile_columns requires a 'data_path' s3:// URI (the production DuckLake path); "
            "no-arg invokes refused (smoke-catalog guard, Decision 84/81)"
        )
    raw_schema = event.get("meta_schema")
    if not raw_schema:
        raise rt.DuckLakeRuntimeError(
            "reconcile_columns requires an EXPLICIT 'meta_schema' (e.g. 'ducklake_ops'); "
            "no-arg invokes refused so it can never hit the smoke catalog (Decision 84/81)"
        )
    meta_schema = _require_identifier(raw_schema)
    table = event.get("table")
    if not isinstance(table, str) or not table.strip():
        raise rt.DuckLakeRuntimeError("reconcile_columns requires a non-empty 'table' param (e.g. 'ops_recommendations')")

    con = rt.open_connection(
        dsn=rt.fetch_dsn(), data_path=data_path, meta_schema=meta_schema, extension_directory=EXTENSION_DIRECTORY
    )
    try:
        result = rt.reconcile_table_columns(con, table=table)
    finally:
        con.close()
    return {
        "ok": True,
        "action": "reconcile_columns",
        "table": table,
        "meta_schema": meta_schema,
        "data_path": data_path,
        "added_history": result["added_history"],
        "added_current": result["added_current"],
        # True when the spec columns were ALREADY present (no ALTER issued this run).
        # After reconcile the columns are present either way; this flags the no-op path.
        "columns_pre_existing": {
            "history": not result["added_history"],
            "current": not result["added_current"],
        },
    }


def action_catalog_stats(event: dict[str, Any], _con: Any) -> dict[str, Any]:
    """OPERATIONAL read-only: catalog-metadata footprint of the production ops_* catalog (D3a).

    Connectionless and ATTACH-free: it reads the catalog's own Postgres metadata tables directly
    (psycopg2), so it needs only an explicit meta_schema -- NO data_path (unlike merge_ops). This is
    the supported measurement path for the neon-egress budget (the DR bucket + direct CloudWatch reads
    are IAM-blocked from the dev role by design). Read-only: no merge/expire/cleanup/orphan.

    Expected event: {"action": "catalog_stats", "meta_schema": "ducklake_ops"}
    """
    raw_schema = event.get("meta_schema")
    if not raw_schema:
        raise rt.DuckLakeRuntimeError(
            "catalog_stats requires an explicit 'meta_schema' (e.g. 'ducklake_ops') -- no default production schema"
        )
    meta_schema = _require_identifier(raw_schema)
    ops_filter = event.get("ops_table_filter", "ops_%")
    result = maint.catalog_stats(meta_schema=meta_schema, dsn=rt.fetch_dsn(), ops_table_filter=ops_filter)

    _emit_maintenance_metric("CatalogMetadataBytes", float(result.get("catalog_metadata_bytes") or 0))
    if result.get("file_column_stats_rows_est") is not None:
        _emit_maintenance_metric("CatalogFileColumnStatsRows", float(result["file_column_stats_rows_est"]))
    return result


def action_merge_ops(event: dict[str, Any], _con: Any) -> dict[str, Any]:
    """OPERATIONAL: non-destructive merge over ALL live ops_* SCD2 table pairs in the production catalog.

    Connectionless: opens its own connection from the event's data_path + meta_schema (production).
    Discovers ops_*_history / ops_*_current pairs via information_schema. Runs
    maint.merge_adjacent_files per table. Non-destructive only -- no expire/cleanup/orphan (those
    remain gated by rec-2113 / T2.26).

    Loud-fail if data_path is missing or not s3://, meta_schema is missing/invalid, or no ops_*
    table pairs are discovered (misconfigured data_path / meta_schema guard).
    """
    data_path = event.get("data_path")
    if not isinstance(data_path, str) or not data_path.startswith("s3://"):
        raise rt.DuckLakeRuntimeError("merge_ops requires a 'data_path' s3:// URI (the production DuckLake path)")
    raw_schema = event.get("meta_schema")
    if not raw_schema:
        raise rt.DuckLakeRuntimeError(
            "merge_ops requires an explicit 'meta_schema' (e.g. 'ducklake_ops') -- no default production schema"
        )
    meta_schema = _require_identifier(raw_schema)

    dsn = rt.fetch_dsn()
    con = rt.open_connection(dsn=dsn, data_path=data_path, meta_schema=meta_schema, extension_directory=EXTENSION_DIRECTORY)
    try:
        catalog = maint.CATALOG_ALIAS
        rows = con.execute(
            f"SELECT table_name FROM information_schema.tables "
            f"WHERE table_catalog = '{catalog}' "
            f"AND (table_name LIKE 'ops_%_history' OR table_name LIKE 'ops_%_current') "
            f"ORDER BY table_name"
        ).fetchall()
        tables = [r[0] for r in rows]

        if not tables:
            raise rt.DuckLakeRuntimeError(
                "merge_ops: no ops_*_history / ops_*_current tables discovered in the catalog -- "
                "verify data_path and meta_schema point at the production DuckLake (ducklake_ops @ s3://.../ducklake/)"
            )

        t0 = time.perf_counter()
        per_table: list[dict[str, Any]] = []
        files_before = 0
        files_after = 0
        for table in tables:
            before = maint._count_files(con, catalog, table)
            maint.merge_adjacent_files(con, [table], catalog=catalog)
            after = maint._count_files(con, catalog, table)
            files_before += before
            files_after += after
            per_table.append({"table": table, "files_before": before, "files_after": after})

        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        _emit_maintenance_metric("MergeOpsDurationMs", elapsed_ms)
        _emit_maintenance_metric("MergeOpsFilesBeforeTotal", float(files_before))
        _emit_maintenance_metric("MergeOpsFilesAfterTotal", float(files_after))
        _emit_maintenance_metric("MergeOpsTablesCount", float(len(tables)))

        return {
            "ok": True,
            "action": "merge_ops",
            "tables": tables,
            "files_before": files_before,
            "files_after": files_after,
            "elapsed_ms": round(elapsed_ms, 2),
            "per_table": per_table,
        }
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

_ACTIONS: dict[str, Any] = {
    "merge": action_merge,
    "gc": action_gc,
    "hot_merge": action_hot_merge,
    "breaker_probe": action_breaker_probe,
    "catalog_reinit": action_catalog_reinit,
    "restore_drill": action_restore_drill,
    "merge_ops": action_merge_ops,
    "catalog_stats": action_catalog_stats,
    "reconcile_columns": action_reconcile_columns,
    "clone_catalog": action_clone_catalog,
}

# Operational actions manage their OWN connections (their target catalog/data_path comes from the
# event, not the scheduled smoke env), so the dispatcher must NOT pre-open the smoke connection.
# catalog_stats is ATTACH-free (psycopg2 metadata read) -- also connectionless.
# clone_catalog manages its own scratch-db connection (never the scheduled smoke env).
_CONNECTIONLESS_ACTIONS = {
    "catalog_reinit",
    "restore_drill",
    "merge_ops",
    "catalog_stats",
    "reconcile_columns",
    "clone_catalog",
}


def _parse_event(event: dict[str, Any]) -> dict[str, Any]:
    """Extract action payload from a Function-URL event (body JSON) or a direct-invoke dict."""
    if isinstance(event, dict) and "body" in event and event.get("body") is not None:
        body = event["body"]
        if isinstance(body, str):
            return json.loads(body) if body else {}
        if isinstance(body, dict):
            return body
    return event if isinstance(event, dict) else {}


def _response(status: int, payload: dict[str, Any]) -> dict[str, Any]:
    """Build a Function-URL response envelope."""
    return {"statusCode": status, "headers": {"Content-Type": "application/json"}, "body": json.dumps(payload)}


def handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    """Maintenance Lambda entrypoint. Dispatches `action`; loud-fail maps to 4xx/5xx (no silent drop)."""
    payload = _parse_event(event)
    action: str | None = payload.get("action")
    fn = _ACTIONS.get(action or "")
    if fn is None:
        return _response(400, {"ok": False, "error": f"unknown action {action!r}", "actions": sorted(_ACTIONS)})

    try:
        if action in _CONNECTIONLESS_ACTIONS:
            return _response(200, fn(payload, None))
        t0 = time.perf_counter()
        con = _open_connection()
        payload["_connect_ms"] = (time.perf_counter() - t0) * 1000.0
        try:
            return _response(200, fn(payload, con))
        finally:
            con.close()
    except maint.DuckLakeMaintenanceError as exc:
        _emit_maintenance_metric("MaintenanceBreakerTrip", 1.0)
        return _response(500, {"ok": False, "error_type": "breaker", "breaker_tripped": True, "error": str(exc)})
    except catalog_dr.CatalogDrError as exc:
        return _response(500, {"ok": False, "error_type": "catalog_dr", "error": str(exc)})
    except rt.VersionMismatchError as exc:
        return _response(500, {"ok": False, "error_type": "version_mismatch", "error": str(exc)})
    except rt.DuckLakeRuntimeError as exc:
        return _response(500, {"ok": False, "error_type": "runtime", "error": str(exc)})
