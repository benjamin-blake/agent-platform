"""ducklake_maintenance_smoke Lambda entrypoint (T2.18 c9 follow-on; bundled Decision amending
Decision 81 clause 1, runtime artifacts 3 -> 4).

CI-invokable smoke-safe sibling of ducklake_maintenance (src/lambdas/ducklake_maintenance/handler.py).
Dispatch table is EXACTLY {merge, gc, breaker_probe, hot_merge} -- the four non-destructive,
disposable-smoke-catalog cadences, sharing src/common/ducklake_maintenance.py with the admin
function. None of the admin function's production-destructive or operational verbs are reachable
here: the boundary is the resource shape -- a separate Lambda + IAM execution role scoped to the
smoke S3 prefix only -- not an in-handler guard an agent-authored codebase could edit out (Fable
frontier-architecture consult, bundled Decision: scope every identity by the worst verb it can
reach). See src/lambdas/ducklake_maintenance/handler.py's module docstring for the admin verb list.

Always operates on the smoke catalog: DUCKLAKE_DATA_PATH / DUCKLAKE_META_SCHEMA default to the
smoke path/schema and are NEVER read from the event -- env-pinned, so a crafted CI payload cannot
redirect this Lambda at the production catalog.

Singleton via reserved_concurrent_executions=1 (Terraform), same invariant as the admin function.
No LLM / agent invocation anywhere in this path (CD.33 clause 5 / Decision 81 clause 6).
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

from src.common import ducklake_maintenance as maint
from src.common import ducklake_runtime as rt

DATA_PATH = os.environ.get("DUCKLAKE_DATA_PATH", rt.SMOKE_DATA_PATH)
META_SCHEMA = os.environ.get("DUCKLAKE_META_SCHEMA", rt.SMOKE_META_SCHEMA)
EXTENSION_DIRECTORY = os.environ.get("DUCKLAKE_EXTENSION_DIRECTORY", rt.LAMBDA_EXTENSION_DIRECTORY)

# GC circuit-breaker thresholds: sourced from env when set (FP-B co-tuning, CD.34), mirroring the
# admin handler. Tuning these to make a gate pass is a Decision-55 violation.
_ENV_GC_BREAKER_FILE_FRACTION: float = float(os.environ.get("GC_BREAKER_FILE_FRACTION", maint.GC_BREAKER_FILE_FRACTION))
_ENV_GC_BREAKER_BYTES: int = int(os.environ.get("GC_BREAKER_BYTES", maint.GC_BREAKER_BYTES))

# Table scope: ducklake_smoke_* only (this Lambda never targets the production catalog).
_SCOPE_TABLES = maint.GC_TABLE_SCOPE
_HOT_SCOPE_TABLES = maint.HOT_TABLE_SCOPE

# Forced-threshold breaker_probe: guaranteed-trip values (mirrors the admin handler).
_BREAKER_PROBE_FILE_FRACTION = 0.0  # 0% -> any 1 deletable file trips it
_BREAKER_PROBE_BYTE_BUDGET = 0  # 0 bytes -> any file trips it


def _open_connection() -> Any:
    """Open a smoke-scoped baked-extension connection to the Neon catalog (always ducklake_smoke)."""
    dsn = rt.fetch_dsn()
    return rt.open_connection(dsn=dsn, data_path=DATA_PATH, meta_schema=META_SCHEMA, extension_directory=EXTENSION_DIRECTORY)


def _emit_maintenance_metric(name: str, value: float, *, profile: str | None = None) -> None:
    rt.emit_metric(name, value, namespace=maint.MAINTENANCE_CLOUDWATCH_NAMESPACE, profile=profile)


# ---------------------------------------------------------------------------
# Actions -- smoke-safe subset only (logic mirrors the admin handler's
# action_merge/action_gc/action_hot_merge/action_breaker_probe verbatim)
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
    deletion. Accepts force_recreate_tables=True (re-creates the smoke tables, idempotent re-run).
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
    """Forced-threshold circuit-breaker test.

    Overrides thresholds to zero so the breaker ALWAYS trips on any deletable file. Asserts that
    check_gc_breaker raises DuckLakeMaintenanceError and that no files are deleted.

    On trip: re-raises DuckLakeMaintenanceError. The handler's outer catch emits
    MaintenanceBreakerTrip=1 exactly once -- do NOT emit it here (single emit point, no double-emit).

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
# Dispatch -- EXACTLY the 4 smoke actions. No production-destructive or operational verb is
# reachable here (blast-radius invariant; enforced by the resource split, not this dict alone).
# ---------------------------------------------------------------------------

_ACTIONS: dict[str, Any] = {
    "merge": action_merge,
    "gc": action_gc,
    "hot_merge": action_hot_merge,
    "breaker_probe": action_breaker_probe,
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
    """Smoke-safe maintenance Lambda entrypoint. Dispatches `action`; loud-fail maps to 4xx/5xx."""
    payload = _parse_event(event)
    action: str | None = payload.get("action")
    fn = _ACTIONS.get(action or "")
    if fn is None:
        return _response(400, {"ok": False, "error": f"unknown action {action!r}", "actions": sorted(_ACTIONS)})

    try:
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
    except rt.VersionMismatchError as exc:
        return _response(500, {"ok": False, "error_type": "version_mismatch", "error": str(exc)})
    except rt.DuckLakeRuntimeError as exc:
        return _response(500, {"ok": False, "error_type": "runtime", "error": str(exc)})
