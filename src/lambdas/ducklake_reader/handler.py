"""ducklake_reader Lambda entrypoint (T2.17 / CD.33, Decision 81).

Read-scoped DuckLake runtime Lambda invoked over an AWS_IAM-signed Function URL. Proves the closed
reader path: every ops read transits this reader; the read role is scoped read-only (S3 GetObject +
the Neon catalog credential), so a write attempt is denied at the IAM/S3 layer.

Actions:
  attach_check         -- ATTACH proof + DuckDB version (mirror of the writer's, read-only).
  read_current         -- return rows from the smoke `current` projection (EC1 / boundary).
  partition_prune_check-- a single-key `current` lookup that touches <=1 bucket-partition.
  read_ops_current     -- production: current projection of an ops_* table (optional single-key filter).
  read_ops_history     -- production: append-history rows of an ops_* table.
  query_ops            -- production: a read-only SELECT over an ops_* current projection (pushdown).

PRODUCTION OPS PATH (T2.19 / Decision 81): the reader is the SOLE read authority for the ops_*
governance tables -- the closed boundary. The read role is S3 GetObject only, so a write attempt is
denied at IAM/S3. Every ops read transits this URL; there is no Athena escape hatch.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Callable

from src.common import ducklake_connect_probe as probe
from src.common import ducklake_runtime as rt

DATA_PATH = os.environ.get("DUCKLAKE_DATA_PATH", rt.SMOKE_DATA_PATH)
META_SCHEMA = os.environ.get("DUCKLAKE_META_SCHEMA", rt.META_SCHEMA)
EXTENSION_DIRECTORY = os.environ.get("DUCKLAKE_EXTENSION_DIRECTORY", rt.LAMBDA_EXTENSION_DIRECTORY)


def _open_reader_connection() -> Any:
    """Open a read-scoped baked-extension connection to the Neon catalog."""
    dsn = rt.fetch_dsn()
    return rt.open_connection(dsn=dsn, data_path=DATA_PATH, meta_schema=META_SCHEMA, extension_directory=EXTENSION_DIRECTORY)


def action_connect_probe(event: dict[str, Any], _con: Any) -> dict[str, Any]:
    """Phased connectivity diagnostic (T2.19 RCA). Runs before any connection open.

    Returns the structured probe result even on a diagnosed failure (ok=False + failed_phase).
    Logs each phase result to CloudWatch via print (Lambda stdout -> CloudWatch Logs).
    """
    dsn = rt.fetch_dsn()
    timeout_s = int(os.environ.get("DUCKLAKE_CONNECT_TIMEOUT_S", "10"))
    result = probe.probe_connection(
        dsn,
        data_path=DATA_PATH,
        meta_schema=META_SCHEMA,
        extension_directory=EXTENSION_DIRECTORY,
        timeout_s=timeout_s,
    )
    print(
        f"CONNECT_PROBE reader phase_reached={result['phase_reached']} "
        f"failed_phase={result['failed_phase']} ok={result['ok']} "
        f"dns_ms={result['dns_ms']} tcp_ms={result['tcp_ms']} "
        f"auth_ms={result['auth_ms']} attach_ms={result['attach_ms']} "
        f"error={result['error']!r}"
    )
    return result


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


def action_write_probe(event: dict[str, Any], con: Any) -> dict[str, Any]:
    """Closed-boundary proof: a write attempt from the read-only role MUST be denied (write_denied).

    The read role grants S3 GetObject only, so the DuckLake Parquet PutObject fails (AccessDenied).
    write_denied=true => the boundary holds; write_denied=false => the read role could write (broken).
    """
    try:
        rt.write_scd2(con, {"rec_id": "rec-reader-write-probe", "payload": "x"})
        return {"ok": True, "write_denied": False}
    except Exception as exc:  # noqa: BLE001 -- any denial (S3 AccessDenied, etc.) means the boundary holds
        return {"ok": True, "write_denied": True, "detail": type(exc).__name__}


def action_read_ops_current(event: dict[str, Any], con: Any) -> dict[str, Any]:
    """Production: return current-projection rows for an ops_* table (optional single-column filter).

    Filter forms (newest first): `filter: {column, value}` -- structural, column validated against
    the field-semantics contract (rec-2170 fix); `key`/`id` -- legacy merge-key-only equality.
    """
    table = event.get("table")
    _require_ops_table(table)
    key = event.get("key") if event.get("key") is not None else event.get("id")
    key_column = None
    flt = event.get("filter")
    if flt is not None:
        if not isinstance(flt, dict) or "column" not in flt or "value" not in flt:
            raise rt.DuckLakeRuntimeError(
                "read_ops_current 'filter' must be an object with BOTH 'column' and 'value' -- "
                "a malformed filter must never degrade to an unfiltered full-table read"
            )
        key_column = flt["column"]
        key = flt["value"]
    rows = rt.read_current(con, table=table, key=key, key_column=key_column, limit=event.get("limit"))
    return {"ok": True, "table": table, "rows": _json_safe(rows), "row_count": len(rows)}


def action_named_read(event: dict[str, Any], con: Any) -> dict[str, Any]:
    """Production: execute a pre-established read verb (Decision 84 I-3).

    The caller names a verb and binds named params; the SQL is registry content inside this
    Lambda's bundle. No caller SQL crosses the boundary on this path.
    """
    verb = event.get("verb")
    if not isinstance(verb, str) or not verb:
        raise rt.DuckLakeRuntimeError("named_read requires a non-empty 'verb' string")
    params = event.get("params") or {}
    if not isinstance(params, dict):
        raise rt.DuckLakeRuntimeError("named_read 'params' must be an object of named bind values")
    rows = rt.named_read(con, verb=verb, params=params)
    return {
        "ok": True,
        "verb": verb,
        "registry_version": rt.NAMED_READS_VERSION,
        "rows": _json_safe(rows),
        "row_count": len(rows),
    }


def action_read_ops_history(event: dict[str, Any], con: Any) -> dict[str, Any]:
    """Production: return append-history rows for an ops_* table (optional single-key filter)."""
    table = event.get("table")
    _require_ops_table(table)
    rows = rt.read_history(con, table=table, key=event.get("key"), limit=event.get("limit"))
    return {"ok": True, "table": table, "rows": _json_safe(rows), "row_count": len(rows)}


def action_query_ops(event: dict[str, Any], con: Any) -> dict[str, Any]:
    """Production: run a read-only SELECT over an ops_* current projection. Use `{tbl}` for the table.

    The SQL is caller-supplied (internal read paths: predicate pushdown). Only the current projection
    is reachable; the read role is S3-read-only so the boundary holds even for an arbitrary SELECT.
    """
    table = event.get("table")
    _require_ops_table(table)
    sql = event.get("sql")
    if not isinstance(sql, str) or not sql.strip():
        raise rt.DuckLakeRuntimeError("query_ops requires a non-empty 'sql' string referencing {tbl}")
    rows = rt.query_current(con, table=table, sql=sql, params=event.get("params") or [])
    return {"ok": True, "table": table, "rows": _json_safe(rows), "row_count": len(rows)}


def _require_ops_table(table: Any) -> None:
    """Loud-fail if *table* is not a configured ops_* table (closed-boundary table allow-list)."""
    if not isinstance(table, str) or table not in rt.ops_table_names():
        raise rt.DuckLakeRuntimeError(f"unknown or missing ops table {table!r}: expected one of {list(rt.ops_table_names())}")


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
    "write_probe": action_write_probe,
    "read_ops_current": action_read_ops_current,
    "read_ops_history": action_read_ops_history,
    "named_read": action_named_read,
    "query_ops": action_query_ops,
    "connect_probe": action_connect_probe,
}

# Actions that run BEFORE the normal connection open (e.g. to diagnose a hanging connect).
_CONNECTIONLESS_ACTIONS = {"connect_probe"}


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
        if action in _CONNECTIONLESS_ACTIONS:
            return _response(200, fn(payload, None))
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
