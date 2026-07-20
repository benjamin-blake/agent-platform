"""ducklake_maintenance Lambda entrypoint (T2.18 / CD.33, Decision 81; T2.18 c9 follow-on split,
bundled Decision amending Decision 81 clause 1, runtime artifacts 3 -> 4).

Admin-gated singleton retaining the production-destructive and operational verbs. The
non-destructive smoke cadences (action=merge / action=gc / action=hot_merge / action=breaker_probe)
were split out to the CI-invokable src/lambdas/ducklake_maintenance_smoke/handler.py sibling, which
shares src/common/ducklake_maintenance.py -- this function no longer runs them, so it no longer
pre-opens a shared smoke-scoped connection (every remaining action manages its own connection, or
is connectionless). The only surviving SCHEDULED cadence on this function is action=merge_ops
(every 6h, non-destructive, production ops_* catalog).

OPERATIONAL admin actions are invoked over 443 via `aws lambda invoke` (NOT public Function URLs,
NOT agent surfaces): catalog_reinit (rec-2099 fix -- drop the squatting meta-schema + re-init at the
production DATA_PATH), restore_drill (pg_dump->pg_restore + read-your-write DR gate),
reconcile_columns, catalog_stats, and clone_catalog (OQ.12 canary rehearsal). These target the
PRODUCTION catalog (ducklake_ops) via explicit event params. (The TEMPORARY
seed_ops_recommendations bootstrap action was removed at the 2026-06-09 recs sign-off -- the closed
boundary now admits recs writes only via the portal `file_rec`/`update_rec` -> writer path,
Decision 81 cl.7.)

No LLM / agent invocation anywhere in this path (CD.33 clause 5 / Decision 81 clause 6).
Singleton enforced by reserved_concurrent_executions=1 (Decision 81 clause 6; see Terraform).

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

EXTENSION_DIRECTORY = os.environ.get("DUCKLAKE_EXTENSION_DIRECTORY", rt.LAMBDA_EXTENSION_DIRECTORY)

# A SQL identifier (meta-schema name) -- guards the few f-string-interpolated DDL sites below.
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _emit_maintenance_metric(name: str, value: float, *, profile: str | None = None) -> None:
    rt.emit_metric(name, value, namespace=maint.MAINTENANCE_CLOUDWATCH_NAMESPACE, profile=profile)


# ---------------------------------------------------------------------------
# Operational actions (T2.19 recs cutover) -- invoked over 443 via `aws lambda invoke`, NOT public
# Function URLs and NOT agent surfaces. They target the PRODUCTION catalog (ducklake_ops) via explicit
# event params and manage their own connections. catalog_reinit + restore_drill are retained as
# operational DR ops. The TEMPORARY seed_ops_recommendations bootstrap was removed at the
# 2026-06-09 recs sign-off (closed boundary -- recs writes now transit only the portal -> writer
# path, Decision 81 cl.7).
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

    data_path = event.get("data_path")
    if not isinstance(data_path, str) or not data_path.startswith("s3://"):
        raise catalog_dr.CatalogDrError(
            "clone_catalog: data_path is required in the event (production DuckLake S3 path, "
            "e.g. s3://<bucket>/ducklake/) -- the Neon branch records the production data_path "
            "and DuckLake rejects a mismatch; pass the production path, not the scratch path (Decision 55)"
        )

    prod_dsn = rt.fetch_dsn()
    branch_dsn = {**prod_dsn, "host": branch_host}
    meta_schema = "ducklake_ops"

    con = rt.open_connection(
        dsn=branch_dsn,
        data_path=data_path,
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
    "catalog_reinit": action_catalog_reinit,
    "restore_drill": action_restore_drill,
    "merge_ops": action_merge_ops,
    "catalog_stats": action_catalog_stats,
    "reconcile_columns": action_reconcile_columns,
    "clone_catalog": action_clone_catalog,
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
    """Maintenance Lambda entrypoint. Dispatches `action`; loud-fail maps to 4xx/5xx (no silent drop).

    Every remaining action manages its own connection internally (or is connection-free, e.g.
    catalog_stats) -- unlike before the smoke split, this dispatcher never pre-opens a shared
    connection itself.
    """
    payload = _parse_event(event)
    action: str | None = payload.get("action")
    fn = _ACTIONS.get(action or "")
    if fn is None:
        return _response(400, {"ok": False, "error": f"unknown action {action!r}", "actions": sorted(_ACTIONS)})

    try:
        return _response(200, fn(payload, None))
    except maint.DuckLakeMaintenanceError as exc:
        _emit_maintenance_metric("MaintenanceBreakerTrip", 1.0)
        return _response(500, {"ok": False, "error_type": "breaker", "breaker_tripped": True, "error": str(exc)})
    except catalog_dr.CatalogDrError as exc:
        return _response(500, {"ok": False, "error_type": "catalog_dr", "error": str(exc)})
    except rt.VersionMismatchError as exc:
        return _response(500, {"ok": False, "error_type": "version_mismatch", "error": str(exc)})
    except rt.DuckLakeRuntimeError as exc:
        return _response(500, {"ok": False, "error_type": "runtime", "error": str(exc)})
