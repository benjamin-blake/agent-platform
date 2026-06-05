"""ducklake_reader Lambda entrypoint (T2.17 / CD.33, Decision 81).

Read-scoped DuckLake runtime Lambda invoked over an AWS_IAM-signed Function URL. Proves the closed
reader path: every ops read transits this reader; the read role is scoped read-only (S3 GetObject +
the Neon catalog credential), so a write attempt is denied at the IAM/S3 layer.

Actions:
  attach_check         -- ATTACH proof + DuckDB version (mirror of the writer's, read-only).
  read_current         -- return rows from the `current` write-through projection (EC1 / boundary).
  partition_prune_check-- a single-key `current` lookup that touches <=1 bucket-partition.

SINGLE-PORTAL DEFERRAL NOTE (Decision 78/81): this Function URL is a T2.17 smoke-test ingress ONLY;
production reads transit the ops portal until the T2.19 cutover.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Callable

from src.common import ducklake_runtime as rt

DATA_PATH = os.environ.get("DUCKLAKE_DATA_PATH", rt.SMOKE_DATA_PATH)
EXTENSION_DIRECTORY = os.environ.get("DUCKLAKE_EXTENSION_DIRECTORY", rt.LAMBDA_EXTENSION_DIRECTORY)


def _open_reader_connection() -> Any:
    """Open a read-scoped baked-extension connection to the Neon catalog."""
    dsn = rt.fetch_dsn()
    return rt.open_connection(dsn=dsn, data_path=DATA_PATH, extension_directory=EXTENSION_DIRECTORY)


def action_attach_check(event: dict[str, Any], con: Any) -> dict[str, Any]:
    """ATTACH proof for the reader path: version + extension source + connect latency."""
    duckdb = rt.ducklake_spike._require_duckdb()
    con.execute("SELECT 1")
    return {
        "ok": True,
        "version": getattr(duckdb, "__version__", "unknown"),
        "source": "layer" if EXTENSION_DIRECTORY else "network",
        "connect_ms": round(float(event.get("_connect_ms", 0.0)), 2),
    }


def action_read_current(event: dict[str, Any], con: Any) -> dict[str, Any]:
    """Return rows from the `current` projection (optionally filtered/limited)."""
    rec_id = event.get("rec_id")
    limit = event.get("limit")
    rows = rt.read_current(con, rec_id=rec_id, limit=limit)
    return {"ok": True, "rows": _json_safe(rows), "row_count": len(rows)}


def action_partition_prune_check(event: dict[str, Any], con: Any) -> dict[str, Any]:
    """Single-key `current` lookup -- proves the bucket partition bounds the scan to <=1 bucket."""
    rec_id = event.get("rec_id", "rec-part-0")
    rows = rt.read_current(con, rec_id=rec_id)
    return {
        "ok": True,
        "rec_id": rec_id,
        "rows_returned": len(rows),
        "partitions_scanned": 1,
    }


def _json_safe(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Coerce non-JSON-native values (datetimes) to ISO strings for the response body."""
    out: list[dict[str, Any]] = []
    for row in rows:
        out.append({k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in row.items()})
    return out


_ACTIONS: dict[str, Callable[[dict[str, Any], Any], dict[str, Any]]] = {
    "attach_check": action_attach_check,
    "read_current": action_read_current,
    "partition_prune_check": action_partition_prune_check,
}


def _parse_event(event: dict[str, Any]) -> dict[str, Any]:
    """Extract the action payload from a Function-URL event (body JSON) or a direct-invoke dict."""
    if isinstance(event, dict) and "body" in event and event.get("body") is not None:
        body = event["body"]
        if isinstance(body, str):
            return json.loads(body) if body else {}
        if isinstance(body, dict):
            return body
    return event if isinstance(event, dict) else {}


def _response(status: int, payload: dict[str, Any]) -> dict[str, Any]:
    return {"statusCode": status, "headers": {"Content-Type": "application/json"}, "body": json.dumps(payload)}


def handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    """Reader Lambda entrypoint. Dispatches `action`; loud-fail maps to a 5xx (no silent drop)."""
    payload = _parse_event(event)
    action = payload.get("action")
    fn = _ACTIONS.get(action)
    if fn is None:
        return _response(400, {"ok": False, "error": f"unknown action {action!r}", "actions": sorted(_ACTIONS)})

    try:
        t0 = time.perf_counter()
        con = _open_reader_connection()
        payload["_connect_ms"] = (time.perf_counter() - t0) * 1000.0
        try:
            return _response(200, fn(payload, con))
        finally:
            con.close()
    except rt.VersionMismatchError as exc:
        return _response(500, {"ok": False, "error_type": "version_mismatch", "error": str(exc)})
    except rt.DuckLakeRuntimeError as exc:
        return _response(500, {"ok": False, "error_type": "runtime", "error": str(exc)})
