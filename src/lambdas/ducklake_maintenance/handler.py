"""ducklake_maintenance Lambda entrypoint (T2.18 / CD.33, Decision 81).

Singleton maintenance Lambda invoked on two EventBridge schedules:
  daily  (cron 04:00 UTC): action=merge  -- non-destructive merge only
  weekly (cron 05:00 UTC Sunday): action=gc  -- full guarded GC with circuit breaker

Also supports action=breaker_probe (forced-threshold test for VP step 11).

No LLM / agent invocation anywhere in this path (CD.33 clause 5 / Decision 81 clause 6).
Singleton enforced by reserved_concurrent_executions=1 (Decision 81 clause 6; see Terraform).

Table scope: ducklake_smoke_* for T2.18 FP-A. Generalises to ops_* at T2.19.
See src/common/ducklake_maintenance.py::MAINTENANCE_SCOPE_NOTE.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

from src.common import ducklake_maintenance as maint
from src.common import ducklake_runtime as rt

DATA_PATH = os.environ.get("DUCKLAKE_DATA_PATH", rt.SMOKE_DATA_PATH)
EXTENSION_DIRECTORY = os.environ.get("DUCKLAKE_EXTENSION_DIRECTORY", rt.LAMBDA_EXTENSION_DIRECTORY)

# Table scope: ducklake_smoke_* (T2.18 FP-A only -- see MAINTENANCE_SCOPE_NOTE for T2.19 expansion).
_SCOPE_TABLES = maint.GC_TABLE_SCOPE

# Forced-threshold breaker_probe: set these to guaranteed-trip values. The probe writes many small
# files before invoking so the dry-run count lands above the threshold, then checks that the
# MaintenanceBreakerTrip metric was emitted and that no files were deleted.
_BREAKER_PROBE_FILE_FRACTION = 0.0  # 0% -> any 1 deletable file trips it
_BREAKER_PROBE_BYTE_BUDGET = 0  # 0 bytes -> any file trips it


def _open_connection() -> Any:
    """Open a maintenance-scoped baked-extension connection to the Neon catalog."""
    dsn = rt.fetch_dsn()
    return rt.open_connection(dsn=dsn, data_path=DATA_PATH, extension_directory=EXTENSION_DIRECTORY)


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

    file_fraction = float(event.get("force_file_fraction", maint.GC_BREAKER_FILE_FRACTION))
    byte_budget = int(event.get("force_byte_budget", maint.GC_BREAKER_BYTES))

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
# Dispatch
# ---------------------------------------------------------------------------

_ACTIONS: dict[str, Any] = {
    "merge": action_merge,
    "gc": action_gc,
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
    """Maintenance Lambda entrypoint. Dispatches `action`; loud-fail maps to 4xx/5xx (no silent drop)."""
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
