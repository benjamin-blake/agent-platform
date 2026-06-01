"""DuckLake spike: isolated end-to-end format de-risking.

Writes throwaway records to s3://agent-platform-data-lake/ducklake-spike/
via the DuckDB ducklake extension + a local SQLite catalog file.

Isolation contract (load-bearing constraint per plan):
- Writes ONLY to the ducklake-spike/ S3 prefix + a dedicated catalog file.
- Imports NOTHING from OpsWriter, outbox, or ops_data_portal.
- Reads NO logs/ cache file.
- RAISES RuntimeError if duckdb is unavailable -- never falls back silently.

Exposes a handler()-shaped entrypoint for future FP-B reuse; invoked via
bin/venv-python for the spike itself.

CD.9 note: DuckLake v1.0 does not support PARTITION BY in CREATE TABLE DDL.
The part_date column serves as a logical partition key; physical partitioning
is an FP-A concern documented in docs/ducklake-spike-findings.md.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SPIKE_S3_DATA_PATH = "s3://agent-platform-data-lake/ducklake-spike/"
SPIKE_TABLE = "throwaway_ops"
_DEFAULT_CATALOG = Path("/tmp/ducklake_spike_catalog.db")
_CATALOG_ALIAS = "spike_lake"
_WRITE_LOCK = threading.Lock()

_CREATE_DDL = f"""
CREATE TABLE IF NOT EXISTS {_CATALOG_ALIAS}.{SPIKE_TABLE} (
    id          VARCHAR   NOT NULL,
    event_type  VARCHAR   NOT NULL,
    value       DOUBLE,
    payload     VARCHAR,
    inserted_at TIMESTAMP NOT NULL,
    part_date   DATE      NOT NULL
)
"""


def _require_duckdb() -> Any:
    """Return the duckdb module, raising RuntimeError if unavailable.

    This is the loud-fail guard: callers must not attempt silent fallback
    when duckdb is missing (no Athena degradation in spike code paths).
    """
    try:
        import duckdb as _duckdb  # noqa: PLC0415

        return _duckdb
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "DuckLake spike requires duckdb but import failed. "
            "Ensure duckdb is installed in the venv: pip install 'duckdb>=1.5.3'."
        ) from exc


def _set_s3_credentials(con: Any, *, profile: str | None = None) -> None:
    """Inject AWS credentials into the DuckDB connection via SET commands.

    Resolves credentials through boto3 using the same profile chain as
    iceberg_reader.py (agent_platform profile for local/web, ambient chain
    for Lambda/CI OIDC).
    """
    import boto3  # noqa: PLC0415

    from scripts.aws_profile import resolve_aws_profile  # noqa: PLC0415

    resolved = resolve_aws_profile(profile)
    session = boto3.Session(profile_name=resolved)
    creds = session.get_credentials().get_frozen_credentials()
    region = session.region_name or "eu-west-2"

    con.execute(f"SET s3_region='{region}'")
    con.execute(f"SET s3_access_key_id='{creds.access_key}'")
    con.execute(f"SET s3_secret_access_key='{creds.secret_key}'")
    if creds.token:
        con.execute(f"SET s3_session_token='{creds.token}'")


def _open_connection(catalog_path: Path = _DEFAULT_CATALOG, *, profile: str | None = None) -> Any:
    """Open a DuckDB connection with ducklake + httpfs loaded and the catalog attached.

    Always installs and loads the extensions fresh so the connection is
    self-contained regardless of the duckdb home directory state.
    """
    duckdb = _require_duckdb()
    con = duckdb.connect()
    con.execute("INSTALL ducklake; LOAD ducklake")
    con.execute("INSTALL httpfs; LOAD httpfs")
    _set_s3_credentials(con, profile=profile)
    con.execute(f"ATTACH '{catalog_path}' AS {_CATALOG_ALIAS} (TYPE DUCKLAKE, DATA_PATH '{SPIKE_S3_DATA_PATH}')")
    con.execute(_CREATE_DDL)
    return con


def write_records(
    records: list[dict[str, Any]],
    *,
    catalog_path: Path = _DEFAULT_CATALOG,
    profile: str | None = None,
) -> int:
    """Append *records* to the isolated DuckLake table under a write lock.

    Each record must contain at least 'id' and 'event_type'. Optional fields:
    'value' (float), 'payload' (str). 'inserted_at' and 'part_date' are
    auto-populated from the current UTC time.

    Returns the number of rows inserted.

    Raises RuntimeError if duckdb is unavailable (loud-fail guard).
    Raises ValueError if *records* is empty.
    """
    if not records:
        raise ValueError("write_records: records must be non-empty")

    now = datetime.now(timezone.utc)
    today = now.date()

    rows = [
        (
            str(r["id"]),
            str(r["event_type"]),
            float(r["value"]) if r.get("value") is not None else None,
            str(r["payload"]) if r.get("payload") is not None else None,
            now,
            today,
        )
        for r in records
    ]

    with _WRITE_LOCK:
        con = _open_connection(catalog_path, profile=profile)
        try:
            con.executemany(
                f"INSERT INTO {_CATALOG_ALIAS}.{SPIKE_TABLE} VALUES (?, ?, ?, ?, ?, ?)",
                rows,
            )
        finally:
            con.close()

    return len(rows)


def read_all(
    *,
    catalog_path: Path = _DEFAULT_CATALOG,
    profile: str | None = None,
) -> list[dict[str, Any]]:
    """Return all rows from the isolated DuckLake table, ordered by inserted_at.

    Raises RuntimeError if duckdb is unavailable (loud-fail guard).
    """
    con = _open_connection(catalog_path, profile=profile)
    try:
        cursor = con.execute(
            f"SELECT id, event_type, value, payload, inserted_at, part_date "
            f"FROM {_CATALOG_ALIAS}.{SPIKE_TABLE} ORDER BY inserted_at, id"
        )
        col_names = [desc[0] for desc in cursor.description]
        return [dict(zip(col_names, row)) for row in cursor.fetchall()]
    finally:
        con.close()


def current_state(
    *,
    catalog_path: Path = _DEFAULT_CATALOG,
    profile: str | None = None,
) -> list[dict[str, Any]]:
    """Return the latest row per id (SCD2-style dedup, Decision 56 observation).

    Uses ROW_NUMBER() OVER (PARTITION BY id ORDER BY inserted_at DESC) = 1,
    mirroring the ops-store dedup pattern. Raises RuntimeError if duckdb
    is unavailable.
    """
    con = _open_connection(catalog_path, profile=profile)
    try:
        cursor = con.execute(
            f"SELECT * EXCLUDE(row_num) FROM ("
            f"  SELECT *, ROW_NUMBER() OVER (PARTITION BY id ORDER BY inserted_at DESC) AS row_num"
            f"  FROM {_CATALOG_ALIAS}.{SPIKE_TABLE}"
            f") WHERE row_num = 1"
        )
        col_names = [desc[0] for desc in cursor.description]
        return [dict(zip(col_names, row)) for row in cursor.fetchall()]
    finally:
        con.close()


def count_s3_data_files(
    *,
    catalog_path: Path = _DEFAULT_CATALOG,
    profile: str | None = None,
) -> int:
    """Return the number of S3 Parquet data files tracked by the catalog.

    Returns 0 when data is inlined (DuckLake's sub-threshold storage).
    Used by TestDuckLakeInlining to assert no orphan sub-threshold files.
    """
    con = _open_connection(catalog_path, profile=profile)
    try:
        result = con.execute("SELECT COUNT(*) FROM __ducklake_metadata_spike_lake.ducklake_data_file").fetchone()
        return int(result[0]) if result else 0
    finally:
        con.close()


def measure_write_read(
    n_rows: int = 50,
    *,
    catalog_path: Path = _DEFAULT_CATALOG,
    profile: str | None = None,
) -> dict[str, Any]:
    """Write n_rows records, read them back, and return timing + row data.

    Used by the integration tests and findings authoring to capture
    write/read latency and verify round-trip correctness.
    """
    records = [
        {"id": f"measure-{i}", "event_type": "benchmark", "value": float(i), "payload": f"payload-{i}"} for i in range(n_rows)
    ]

    t0 = time.perf_counter()
    inserted = write_records(records, catalog_path=catalog_path, profile=profile)
    write_ms = (time.perf_counter() - t0) * 1000

    t1 = time.perf_counter()
    rows = read_all(catalog_path=catalog_path, profile=profile)
    read_ms = (time.perf_counter() - t1) * 1000

    return {
        "n_inserted": inserted,
        "n_read": len(rows),
        "write_ms": round(write_ms, 1),
        "read_ms": round(read_ms, 1),
        "rows": rows,
    }


def handler(event: dict[str, Any], context: object | None = None) -> dict[str, Any]:
    """Lambda-shaped entrypoint for future FP-B reuse.

    event keys:
      action: "write" | "read" | "current_state" | "benchmark"
      records: list of dicts (for "write")
      catalog_path: str (optional, defaults to _DEFAULT_CATALOG)
      n_rows: int (for "benchmark", default 50)
    """
    catalog_path = Path(event.get("catalog_path", str(_DEFAULT_CATALOG)))
    action = event.get("action", "benchmark")

    if action == "write":
        inserted = write_records(event["records"], catalog_path=catalog_path)
        return {"action": "write", "inserted": inserted}

    if action == "read":
        rows = read_all(catalog_path=catalog_path)
        return {"action": "read", "count": len(rows)}

    if action == "current_state":
        rows = current_state(catalog_path=catalog_path)
        return {"action": "current_state", "count": len(rows)}

    if action == "benchmark":
        n_rows = int(event.get("n_rows", 50))
        result = measure_write_read(n_rows, catalog_path=catalog_path)
        return {"action": "benchmark", **result}

    raise ValueError(f"handler: unknown action {action!r}")
