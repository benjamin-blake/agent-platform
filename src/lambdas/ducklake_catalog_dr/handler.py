"""ducklake_catalog_dr Lambda entrypoint (T2.18 FP-B / CD.34, Decision 82).

Daily DR Lambda: runs pg_dump --format=custom --serializable-deferrable against the Neon catalog
(DSN runtime-fetched from Secrets Manager, Decision 37) and uploads the engine-version-tagged dump
to the dedicated DR bucket. Emits CatalogDumpSuccess=1 to CloudWatch on success.

Invoked on EventBridge cron(0 3 * * ? *) or directly via Function URL (AWS_IAM).
Accepts force_* event fields per Lambda convention.
Maps loud-fail (CatalogDrError) to 5xx -- a failed dump is never silently swallowed (Decision 55).

pg_dump binary: /opt/bin/pg_dump from the ducklake-pgclient layer (version-asserted to PG16 at
build time; a version mismatch is caught at build time, not first at runtime). lambda-pgclient
layer is NOT a pip wheel -- pg_dump is a native binary vendored under /opt/bin with
LD_LIBRARY_PATH pointing at /opt/lib for the bundled libpq.so.
"""

from __future__ import annotations

import json
import os
from typing import Any

from src.common import catalog_dr
from src.common import ducklake_runtime as rt

DR_BUCKET = os.environ.get("DUCKLAKE_DR_BUCKET", "")
PROFILE = os.environ.get("AWS_PROFILE") or None
REGION = os.environ.get("AWS_DEFAULT_REGION", "eu-west-2")
PG_DUMP_PATH = os.environ.get("PG_DUMP_PATH", catalog_dr.LAMBDA_PG_DUMP_PATH)


def _parse_event(event: dict[str, Any]) -> dict[str, Any]:
    """Extract payload from a Function-URL event (body JSON) or a direct-invoke dict."""
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
    """DR Lambda entrypoint. Loud-fail maps to 5xx (Decision 55 -- no silent drop)."""
    payload = _parse_event(event)

    bucket = payload.get("force_bucket") or DR_BUCKET
    if not bucket:
        return _response(500, {"ok": False, "error": "DUCKLAKE_DR_BUCKET not configured"})

    pg_dump_path = payload.get("force_pg_dump_path") or PG_DUMP_PATH
    pg_version = payload.get("force_pg_version") or catalog_dr.PINNED_PG_VERSION
    duckdb_version = payload.get("force_duckdb_version") or rt.PINNED_DUCKDB_VERSION

    try:
        dsn = rt.fetch_dsn(profile=PROFILE)
        result = catalog_dr.run_catalog_dump(
            dsn,
            bucket=bucket,
            pg_version=pg_version,
            duckdb_version=duckdb_version,
            profile=PROFILE,
            region=REGION,
            pg_dump_path=pg_dump_path,
        )
        return _response(200, result)
    except catalog_dr.CatalogDrError as exc:
        return _response(500, {"ok": False, "error_type": "catalog_dr", "error": str(exc)})
    except rt.DuckLakeRuntimeError as exc:
        return _response(500, {"ok": False, "error_type": "runtime", "error": str(exc)})
