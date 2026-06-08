"""DuckLake operational-lakehouse runtime (T2.17 / CD.33, Decision 81).

Single ATTACH/connection authority plus the CD.33 write/read primitives shared by the
ducklake_writer and ducklake_reader Lambdas and the Neon smoke test. There is exactly ONE
ATTACH implementation: the dev/smoke path installs extensions over the network, the Lambda
path loads them from a baked layer (extension_directory + autoload/autoinstall off +
custom_extension_repository fail-closed). An `extension_directory` argument selects the mode.

Design invariants (CD.33):
  - Idempotent append: the history table is keyed by a monotonic ULID minted ONCE per write,
    OUTSIDE the OCC-retry loop, and reused on every retry. MERGE-on-ULID insert-if-not-matched
    de-duplicates, so a retried write never double-appends (no engine PK; the ULID is a logical
    key enforced by MERGE).
  - SCD2 derivations minted once: `created_timestamp` is stamped at first insert and CARRIED
    unchanged on update (never re-stamped); `last_updated_timestamp` is minted once with the
    ULID and is stable across retries.
  - Schema gate + OCC exhaustion LOUD-FAIL (Decision 55): a rejected field or an exhausted
    retry budget raises; there is never a silent drop or an Athena fallback.
  - Version lockstep (OQ.12): DuckDB is pinned to PINNED_DUCKDB_VERSION; a runtime assert fails
    loudly on mismatch. A bump follows the clone-rehearsal policy in the catalog-operations
    runbook.

Field semantics (input vs derived, derivation rules, partition transforms) are sourced from
config/lambda/ducklake/field_semantics.yaml -- the single contract the schema gate, the
derivation engine, and the tests all read.
"""

from __future__ import annotations

import os
import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Optional

import yaml

from src.common import ducklake_spike

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PINNED_DUCKDB_VERSION = "1.5.3"  # lockstep with DuckLake v1.0 (OQ.12); Lambda layer pins ==1.5.3

DSN_SECRET_ID = "ducklake-neon-catalog-dsn"
CATALOG_ALIAS = "ops_catalog"
META_SCHEMA = "ducklake_ops"

# Representative SCD2 smoke-table pair (real ops_* business schema is T2.19).
SMOKE_DATA_PATH = "s3://agent-platform-data-lake/ducklake-neon-smoke/"
SMOKE_HISTORY_TABLE = "ducklake_smoke_history"
SMOKE_CURRENT_TABLE = "ducklake_smoke_current"

# Baked extensions in the Lambda layer: (LOAD/INSTALL name, on-disk file stem). DuckDB publishes
# the Postgres extension binary as `postgres_scanner.duckdb_extension` even though it INSTALLs and
# LOADs under the name `postgres` (verified against v1.5.3/linux_amd64).
BAKED_EXTENSIONS: tuple[tuple[str, str], ...] = (
    ("ducklake", "ducklake"),
    ("httpfs", "httpfs"),
    ("postgres", "postgres_scanner"),
)

# Default location DuckDB looks for baked extensions inside the Lambda (the layer unpacks to /opt).
LAMBDA_EXTENSION_DIRECTORY = "/opt/duckdb_extensions"

# OCC retry budget (CD.33): bounded application-level retry with backoff + jitter, loud-fail on
# exhaustion. NOT a knob to loosen so a gate passes (Decision 55).
OCC_MAX_ATTEMPTS = 5
OCC_BASE_BACKOFF_S = 0.05
OCC_MAX_BACKOFF_S = 1.0

# Substrings of a Postgres/DuckLake error that indicate an optimistic-concurrency / serialization
# collision (the expected, retryable contention signal) rather than a hard failure.
_OCC_COLLISION_MARKERS = (
    "could not serialize",
    "deadlock detected",
    "concurrent update",
    "conflict",
    "transaction conflict",
    "write-write",
)

# CD.33 churn gate budget (single source -- rec-2091; ducklake_writer and smoke test import from here).
# Values are CD.33 / Decision 55 / Decision 81 invariants -- never relax without a Decision superseding CD.33.
COMMIT_LATENCY_BUDGET_MS = 2000.0  # p95 commit latency ceiling (in-Lambda, DIRECT endpoint)
OCC_COLLISION_RATE_BUDGET = 0.20  # max fraction of churn writers that hit an OCC collision
CHURN_WRITERS = 4  # concurrent invocation fan-out for EC8 (Decision 82: N steered 8->4; budget VALUES above unchanged)
CHURN_WRITES_PER_WRITER = 5  # writes per writer per churn iteration

# CloudWatch metric namespace for OCC-retry + commit-latency emission (EC9).
CLOUDWATCH_NAMESPACE = "DuckLakeWriter"

_FIELD_SEMANTICS_ENV = "DUCKLAKE_FIELD_SEMANTICS_PATH"
_DEFAULT_FIELD_SEMANTICS_PATH = Path(__file__).resolve().parents[2] / "config" / "lambda" / "ducklake" / "field_semantics.yaml"

# SQL-type -> Python type for the schema gate's input-field validation. Extended for the real ops_*
# column types (T2.19): arrays (tags/dependencies/related_decisions -> list), integers
# (decision_id/execution_steps/rank -> int), booleans (automatable -> bool). DuckDB array types are
# spelled `<base>[]` (e.g. VARCHAR[], BIGINT[]); they map to a Python list at the gate.
_PY_TYPE_FOR_SQL: dict[str, type] = {
    "VARCHAR": str,
    "TIMESTAMP WITH TIME ZONE": datetime,
    "BIGINT": int,
    "INTEGER": int,
    "BOOLEAN": bool,
    "VARCHAR[]": list,
    "BIGINT[]": list,
    "INTEGER[]": list,
}


# ---------------------------------------------------------------------------
# Exceptions -- all loud-fail (Decision 55)
# ---------------------------------------------------------------------------


class DuckLakeRuntimeError(RuntimeError):
    """Base for all DuckLake runtime loud-fail conditions."""


class VersionMismatchError(DuckLakeRuntimeError):
    """Raised when the live DuckDB version differs from the pinned lockstep version (OQ.12)."""


class SchemaGateError(DuckLakeRuntimeError):
    """Raised when a write record fails the schema gate (unknown/derived/missing/mis-typed field)."""


class OCCRetryExhaustedError(DuckLakeRuntimeError):
    """Raised when the bounded OCC-retry budget is exhausted (CD.33). Stop-and-RCA, never relax."""


class ReferentialError(DuckLakeRuntimeError):
    """Raised when an update targets a merge-key absent from the current projection (CD.33 cl.8 / D-5).

    The in-transaction existence check replaces the prior permissive upsert-on-absent: an update of a
    non-existent record loud-fails instead of silently creating a partial row.
    """


# ---------------------------------------------------------------------------
# Write identity (minted once, outside the OCC-retry loop)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WriteIdentity:
    """The deterministic identity minted ONCE per write op, reused on every OCC retry.

    ulid: monotonic ULID, the history logical PK + idempotency dedup key.
    timestamp: high-precision write timestamp, stable across retries (SCD2 ordering).
    """

    ulid: str
    timestamp: datetime


@dataclass(frozen=True)
class WriteResult:
    """Outcome of a write_scd2 call. occ_retries + commit_ms drive the CloudWatch metrics."""

    ulid: str
    rec_id: str
    occ_retries: int
    commit_ms: float
    created_timestamp: datetime
    last_updated_timestamp: datetime


def mint_write_identity(*, now: datetime | None = None) -> WriteIdentity:
    """Mint the ULID + timestamp ONCE for a write op. Call OUTSIDE the OCC-retry loop (CD.33).

    The ULID embeds the same instant as `timestamp` (ULID.from_datetime), so the history PK and
    the SCD2 ordering key are coherent. On retry the SAME WriteIdentity is reused -- never re-minted.
    """
    from ulid import ULID  # noqa: PLC0415

    moment = now or datetime.now(timezone.utc)
    return WriteIdentity(ulid=str(ULID.from_datetime(moment)), timestamp=moment)


# ---------------------------------------------------------------------------
# Version assertion (OQ.12 lockstep)
# ---------------------------------------------------------------------------


def assert_duckdb_version(duckdb_module: Any = None) -> str:
    """Assert the live DuckDB equals the pinned version. Loud-fail on mismatch (OQ.12).

    Returns the asserted version string. Pass `duckdb_module` to inject a fake in tests.
    """
    duckdb_module = duckdb_module if duckdb_module is not None else ducklake_spike._require_duckdb()
    actual = getattr(duckdb_module, "__version__", None)
    if actual != PINNED_DUCKDB_VERSION:
        raise VersionMismatchError(
            f"DuckDB version mismatch: runtime has {actual!r}, pinned {PINNED_DUCKDB_VERSION!r}. "
            "DuckLake v1.0 is lockstep with DuckDB 1.5.3 (OQ.12). Follow the clone-rehearsal "
            "version-bump policy in docs/runbooks/ducklake-catalog-operations.md before bumping."
        )
    return actual


# ---------------------------------------------------------------------------
# DSN fetch + conninfo (moved here from the smoke test -- single implementation)
# ---------------------------------------------------------------------------


def fetch_dsn(secret_id: str = DSN_SECRET_ID, *, profile: str | None = None) -> dict[str, str]:
    """Fetch + parse the Neon DSN JSON from Secrets Manager (Decision 37 runtime-fetch).

    Returns a dict with at least host / dbname / username / password (sslmode optional, defaults
    to require). Raises RuntimeError if the secret is missing a required key.
    """
    import boto3  # noqa: PLC0415

    from scripts.aws_profile import resolve_aws_profile  # noqa: PLC0415

    session = boto3.Session(profile_name=resolve_aws_profile(profile))
    client = session.client("secretsmanager")
    resp = client.get_secret_value(SecretId=secret_id)
    payload = _parse_secret_string(resp["SecretString"])
    missing = [k for k in ("host", "dbname", "username", "password") if not payload.get(k)]
    if missing:
        raise RuntimeError(f"DSN secret {secret_id!r} is missing required keys: {missing}")
    return payload


def _parse_secret_string(secret_string: str) -> dict[str, str]:
    """Parse the Secrets Manager SecretString JSON into a dict."""
    import json  # noqa: PLC0415

    return json.loads(secret_string)


def libpq_conninfo(dsn: dict[str, str]) -> str:
    """Return a libpq keyword/value conninfo string for the DuckLake postgres backend.

    sslmode defaults to require so TLS is always enforced even if the secret omits it (the
    Terraform-written secret always sets it; this is defence in depth).
    """
    sslmode = dsn.get("sslmode") or "require"
    return f"dbname={dsn['dbname']} host={dsn['host']} user={dsn['username']} password={dsn['password']} sslmode={sslmode}"


# ---------------------------------------------------------------------------
# Connection authority -- the single ATTACH (dev INSTALL vs Lambda baked layer)
# ---------------------------------------------------------------------------


def open_connection(
    *,
    dsn: dict[str, str],
    data_path: str = SMOKE_DATA_PATH,
    extension_directory: str | None = None,
    profile: str | None = None,
    _creds: tuple[str, str, str | None, str] | None = None,
) -> Any:
    """Open a DuckDB connection with ducklake/httpfs/postgres loaded and the Neon catalog ATTACHed.

    extension_directory:
      - None  -> dev/smoke mode: network INSTALL + LOAD of each extension.
      - set   -> Lambda baked mode: LOAD from the directory with autoload/autoinstall DISABLED and
                 custom_extension_repository EMPTY (fail-closed: no network INSTALL at runtime).

    The ATTACH validates DATA_PATH against the catalog's stored value and fails loud on mismatch
    (no silent rebind). DuckLake pins the data_path at catalog-init; OVERRIDE_DATA_PATH is only a
    per-session override and does NOT persist, so relocating the catalog means reinitialising it --
    see docs/runbooks/ducklake-catalog-operations.md.

    Inlining is disabled (ducklake_default_data_inlining_row_limit=0) on every connection so S3
    Parquet is written immediately for ALL tables (EC11 / smoke #921). The ATTACH targets the Neon
    DIRECT endpoint over TLS (sslmode=require, enforced by libpq_conninfo).
    """
    duckdb = ducklake_spike._require_duckdb()
    assert_duckdb_version(duckdb)
    con = duckdb.connect()
    # Limit DuckDB's internal thread pool to 1. The churn gate runs 8 Python threads, each with its
    # own connection; DuckDB's background parallelism compounds vCPU starvation on constrained Lambda
    # allocations. Our caller provides the concurrency -- DuckDB does not need to add its own.
    con.execute("SET threads=1")

    if extension_directory is not None:
        con.execute(f"SET extension_directory={ducklake_spike._sql_str_literal(extension_directory)}")
        con.execute("SET autoinstall_known_extensions=false")
        con.execute("SET autoload_known_extensions=false")
        con.execute("SET custom_extension_repository=''")
        for load_name, _stem in BAKED_EXTENSIONS:
            con.execute(f"LOAD {load_name}")
    else:
        for load_name, _stem in BAKED_EXTENSIONS:
            con.execute(f"INSTALL {load_name}; LOAD {load_name}")

    if _creds is not None:
        ak, sk, tok, region = _creds
        con.execute(f"SET s3_region={ducklake_spike._sql_str_literal(region)}")
        con.execute(f"SET s3_access_key_id={ducklake_spike._sql_str_literal(ak)}")
        con.execute(f"SET s3_secret_access_key={ducklake_spike._sql_str_literal(sk)}")
        if tok:
            con.execute(f"SET s3_session_token={ducklake_spike._sql_str_literal(tok)}")
    else:
        ducklake_spike._set_s3_credentials(con, profile=profile)

    # Inlining off for ALL tables (CD.34 / EC11): write S3 Parquet immediately, never inline rows.
    con.execute("SET ducklake_default_data_inlining_row_limit=0")

    conninfo = libpq_conninfo(dsn)
    con.execute(
        f"ATTACH 'ducklake:postgres:{conninfo}' AS {CATALOG_ALIAS} (DATA_PATH '{data_path}', META_SCHEMA '{META_SCHEMA}')"
    )
    return con


# ---------------------------------------------------------------------------
# Field-semantics contract -- the single source the gate + derivations + tests read
# ---------------------------------------------------------------------------


def _field_semantics_path() -> Path:
    """Resolve the field-semantics YAML path (env override for Lambda-bundle relocation)."""
    override = os.environ.get(_FIELD_SEMANTICS_ENV)
    return Path(override) if override else _DEFAULT_FIELD_SEMANTICS_PATH


@lru_cache(maxsize=4)
def _load_field_semantics_cached(path_str: str) -> dict[str, Any]:
    return yaml.safe_load(Path(path_str).read_text(encoding="utf-8"))


def load_field_semantics(path: str | Path | None = None) -> dict[str, Any]:
    """Load + cache the field-semantics contract. Pass `path` to override (tests)."""
    resolved = Path(path) if path is not None else _field_semantics_path()
    return _load_field_semantics_cached(str(resolved))


# ---------------------------------------------------------------------------
# Table spec -- the single resolved shape that drives the gate, DDL, MERGE, and reads.
# table=None selects the smoke pair (T2.17 back-compat); a name selects an ops_tables entry (T2.19).
# ---------------------------------------------------------------------------

# Derived SCD2-envelope columns minted by the runtime (never caller-supplied). Physical column order
# is: ulid first, then the input columns (merge_key first), then created/last_updated last.
_DERIVED_LEAD = "ulid"
_DERIVED_TAIL = ("created_timestamp", "last_updated_timestamp")


@dataclass(frozen=True)
class ScdTableSpec:
    """Resolved SCD2 table shape. Drives create/gate/write/read uniformly for smoke + ops_* tables."""

    table: str | None  # None = smoke
    history_table: str
    current_table: str
    merge_key: str
    fields: dict[str, Any]  # column name -> {role, sql_type, nullable}; the schema-gate contract
    ordered_columns: tuple[tuple[str, str], ...]  # (name, sql_type) in physical (DDL/INSERT) order
    partition_history: str
    partition_current: str


def _order_columns(fields: dict[str, Any], merge_key: str) -> tuple[tuple[str, str], ...]:
    """Return ((name, sql_type), ...) in physical order: ulid, merge_key, other inputs, created, updated.

    A stable, deterministic order so the DDL, the MERGE source SELECT, the INSERT VALUES list, and the
    read projection all agree without a separate ordering source.
    """
    inputs = [c for c, s in fields.items() if s.get("role") == "input"]
    other_inputs = [c for c in inputs if c != merge_key]
    ordered = [_DERIVED_LEAD, merge_key, *other_inputs, *_DERIVED_TAIL]
    return tuple((c, fields[c]["sql_type"]) for c in ordered)


def resolve_table_spec(table: str | None = None, semantics: dict[str, Any] | None = None) -> ScdTableSpec:
    """Resolve the SCD2 spec for *table* (None = smoke). Loud-fail on an unknown ops table name."""
    semantics = semantics if semantics is not None else load_field_semantics()
    if table is None:
        partitions = semantics.get("partition_transforms", {})
        return ScdTableSpec(
            table=None,
            history_table=SMOKE_HISTORY_TABLE,
            current_table=SMOKE_CURRENT_TABLE,
            merge_key="rec_id",
            fields=semantics["fields"],
            ordered_columns=_order_columns(semantics["fields"], "rec_id"),
            partition_history=partitions.get("history", "day(created_timestamp)"),
            partition_current=partitions.get("current", "bucket(8, rec_id)"),
        )
    ops_tables = semantics.get("ops_tables", {})
    spec = ops_tables.get(table)
    if spec is None:
        raise SchemaGateError(f"unknown ops table {table!r}: not in field_semantics ops_tables (have {sorted(ops_tables)})")
    merge_key = spec["merge_key"]
    fields = spec["columns"]
    part = spec.get("partition", {})
    return ScdTableSpec(
        table=table,
        history_table=spec["history_table"],
        current_table=spec["current_table"],
        merge_key=merge_key,
        fields=fields,
        ordered_columns=_order_columns(fields, merge_key),
        partition_history=part.get("history", "day(created_timestamp)"),
        partition_current=part.get("current", f"bucket(8, {merge_key})"),
    )


def ops_table_names(semantics: dict[str, Any] | None = None) -> tuple[str, ...]:
    """Return the configured ops_* table names (live + dormant)."""
    semantics = semantics if semantics is not None else load_field_semantics()
    return tuple(semantics.get("ops_tables", {}).keys())


def _column_ddl(spec: ScdTableSpec) -> str:
    """Compose the CREATE-TABLE column list from the spec (NOT NULL on non-nullable columns)."""
    parts: list[str] = []
    for name, sql_type in spec.ordered_columns:
        nullable = bool(spec.fields[name].get("nullable", True))
        parts.append(f"{name} {sql_type}" + ("" if nullable else " NOT NULL"))
    return ", ".join(parts)


def _build_merge_history_sql(spec: ScdTableSpec) -> str:
    cols = [c for c, _ in spec.ordered_columns]
    select = ", ".join(f"? AS {c}" for c in cols)
    values = ", ".join(f"s.{c}" for c in cols)
    return (
        f"MERGE INTO {CATALOG_ALIAS}.{spec.history_table} AS t "
        f"USING (SELECT {select}) AS s "
        "ON t.ulid = s.ulid "
        f"WHEN NOT MATCHED THEN INSERT VALUES ({values})"
    )


def _build_merge_current_sql(spec: ScdTableSpec) -> str:
    cols = [c for c, _ in spec.ordered_columns]
    select = ", ".join(f"? AS {c}" for c in cols)
    values = ", ".join(f"s.{c}" for c in cols)
    # created_timestamp is carried (never re-stamped on update); the merge key is the ON predicate.
    update_cols = [c for c in cols if c not in (spec.merge_key, "created_timestamp")]
    set_clause = ", ".join(f"{c} = s.{c}" for c in update_cols)
    return (
        f"MERGE INTO {CATALOG_ALIAS}.{spec.current_table} AS t "
        f"USING (SELECT {select}) AS s "
        f"ON t.{spec.merge_key} = s.{spec.merge_key} "
        f"WHEN MATCHED THEN UPDATE SET {set_clause} "
        f"WHEN NOT MATCHED THEN INSERT VALUES ({values})"
    )


def _build_select_existing_created_sql(spec: ScdTableSpec) -> str:
    return f"SELECT created_timestamp FROM {CATALOG_ALIAS}.{spec.current_table} WHERE {spec.merge_key} = ?"


def _write_params(spec: ScdTableSpec, record: dict[str, Any], identity: WriteIdentity, created_ts: datetime) -> list[Any]:
    """Bind the ordered-column values for the MERGE source row (derived minted, inputs from record)."""
    params: list[Any] = []
    for name, _ in spec.ordered_columns:
        if name == "ulid":
            params.append(identity.ulid)
        elif name == "created_timestamp":
            params.append(created_ts)
        elif name == "last_updated_timestamp":
            params.append(identity.timestamp)
        else:
            params.append(record.get(name))
    return params


# ---------------------------------------------------------------------------
# Schema gate -- loud-fail on unknown / derived / missing / mis-typed input fields
# ---------------------------------------------------------------------------


def schema_gate(record: dict[str, Any], semantics: dict[str, Any] | None = None, *, table: str | None = None) -> None:
    """Validate a caller-supplied write record against the contract. Loud-fail (Decision 55).

    `table=None` validates against the smoke `fields` map (T2.17 back-compat); a table name validates
    against that ops_tables entry's `columns` map (T2.19).

    Rejects (raises SchemaGateError):
      - any key not present in the contract (unknown field),
      - any key whose role is `derived` (the caller must not supply derived values),
      - any required (`nullable: false`) input field that is missing, null, or empty,
      - any input field whose value is not the contract's declared SQL type.
    """
    semantics = semantics if semantics is not None else load_field_semantics()
    fields: dict[str, Any] = semantics["fields"] if table is None else resolve_table_spec(table, semantics).fields

    for key in record:
        spec = fields.get(key)
        if spec is None:
            raise SchemaGateError(f"unknown field {key!r}: not in the field-semantics contract")
        if spec["role"] == "derived":
            raise SchemaGateError(f"field {key!r} is derived: the runtime mints it; the caller must not supply it")

    for name, spec in fields.items():
        if spec["role"] != "input":
            continue
        nullable = bool(spec.get("nullable", True))
        present = name in record
        value = record.get(name)
        if not nullable and (not present or value is None):
            raise SchemaGateError(f"required input field {name!r} is missing or null")
        if present and value is not None:
            expected = _PY_TYPE_FOR_SQL.get(spec["sql_type"])
            if expected is not None and not isinstance(value, expected):
                raise SchemaGateError(f"field {name!r} expected {expected.__name__}, got {type(value).__name__}")
            if expected is str and not nullable and value == "":
                raise SchemaGateError(f"required input field {name!r} is empty")


# ---------------------------------------------------------------------------
# Table DDL -- CREATE + partition transforms BEFORE first write (post-ALTER-only, M-5)
# ---------------------------------------------------------------------------

_SCD2_COLUMNS = (
    "ulid VARCHAR NOT NULL, "
    "rec_id VARCHAR NOT NULL, "
    "payload VARCHAR, "
    "created_timestamp TIMESTAMP WITH TIME ZONE NOT NULL, "
    "last_updated_timestamp TIMESTAMP WITH TIME ZONE NOT NULL"
)


def create_scd2_tables(con: Any, *, table: str | None = None, force_recreate: bool = False) -> None:
    """Create the history + current tables for *table* and partition them BEFORE first write.

    `table=None` is the smoke pair (T2.17); a name selects an ops_tables entry (T2.19). The column
    list, the merge-key bucket, and the day(created_timestamp) history partition all come from the
    resolved spec, so the DDL never drifts from the gate.

    Partition transforms are post-ALTER-only (CD.33 M-5): they MUST be applied before any row lands.
    `force_recreate=True` drops both tables first -- the backfill's resurrection-loop guard: a
    re-run DROPs + recreates rather than appending onto a half-populated catalog. Re-ALTER on an
    already-partitioned table is idempotent in DuckLake 1.5.3, so the non-force path converges too.
    """
    spec = resolve_table_spec(table)
    history = f"{CATALOG_ALIAS}.{spec.history_table}"
    current = f"{CATALOG_ALIAS}.{spec.current_table}"
    columns = _column_ddl(spec)

    if force_recreate:
        con.execute(f"DROP TABLE IF EXISTS {history}")
        con.execute(f"DROP TABLE IF EXISTS {current}")

    con.execute(f"CREATE TABLE IF NOT EXISTS {history} ({columns})")
    con.execute(f"CREATE TABLE IF NOT EXISTS {current} ({columns})")

    # Partition transforms BEFORE first write: history by day(created_timestamp) for date-range
    # pruning; current by bucket(N, merge_key) to bound the single-key lookup/MERGE scan footprint.
    con.execute(f"ALTER TABLE {history} SET PARTITIONED BY ({spec.partition_history})")
    con.execute(f"ALTER TABLE {current} SET PARTITIONED BY ({spec.partition_current})")


# ---------------------------------------------------------------------------
# The shared write primitive -- history MERGE-on-ULID + current write-through, bounded OCC retry
# ---------------------------------------------------------------------------

_MERGE_HISTORY = (
    f"MERGE INTO {CATALOG_ALIAS}.{SMOKE_HISTORY_TABLE} AS t "
    "USING (SELECT ? AS ulid, ? AS rec_id, ? AS payload, ? AS created_timestamp, "
    "? AS last_updated_timestamp) AS s "
    "ON t.ulid = s.ulid "
    "WHEN NOT MATCHED THEN INSERT VALUES "
    "(s.ulid, s.rec_id, s.payload, s.created_timestamp, s.last_updated_timestamp)"
)

_MERGE_CURRENT = (
    f"MERGE INTO {CATALOG_ALIAS}.{SMOKE_CURRENT_TABLE} AS t "
    "USING (SELECT ? AS ulid, ? AS rec_id, ? AS payload, ? AS created_timestamp, "
    "? AS last_updated_timestamp) AS s "
    "ON t.rec_id = s.rec_id "
    "WHEN MATCHED THEN UPDATE SET ulid = s.ulid, payload = s.payload, "
    "last_updated_timestamp = s.last_updated_timestamp "
    "WHEN NOT MATCHED THEN INSERT VALUES "
    "(s.ulid, s.rec_id, s.payload, s.created_timestamp, s.last_updated_timestamp)"
)

_SELECT_EXISTING_CREATED = f"SELECT created_timestamp FROM {CATALOG_ALIAS}.{SMOKE_CURRENT_TABLE} WHERE rec_id = ?"


def is_occ_collision(exc: Exception) -> bool:
    """True if *exc* looks like an optimistic-concurrency / serialization collision (retryable)."""
    msg = str(exc).lower()
    return any(marker in msg for marker in _OCC_COLLISION_MARKERS)


def _occ_backoff(attempt: int, *, sleep: Callable[[float], None] = time.sleep) -> None:
    """Sleep with exponential backoff + full jitter before the next OCC retry."""
    ceiling = min(OCC_MAX_BACKOFF_S, OCC_BASE_BACKOFF_S * (2 ** (attempt - 1)))
    sleep(random.uniform(0.0, ceiling))


def write_scd2(
    con: Any,
    record: dict[str, Any],
    *,
    table: str | None = None,
    identity: WriteIdentity | None = None,
    semantics: dict[str, Any] | None = None,
    require_exists: bool = False,
    max_attempts: int = OCC_MAX_ATTEMPTS,
    metric_sink: Optional[Callable[[str, float], None]] = None,
    sleep: Callable[[float], None] = time.sleep,
) -> WriteResult:
    """Write one SCD2 record: history MERGE-on-ULID append + current write-through, one transaction.

    `table=None` writes the smoke pair (T2.17); a name selects an ops_tables entry (T2.19). The
    merge key, column order, and MERGE SQL are resolved from the spec, so this single primitive
    drives every governance table.

    Idempotency (CD.33 D-2): the ULID + timestamp are minted ONCE here, OUTSIDE the retry loop, and
    reused on every attempt. MERGE-on-ULID de-duplicates the history append, so a retried write
    never double-appends. `created_timestamp` is carried unchanged from the existing current row on
    update, and minted (= identity.timestamp) on first insert -- never re-stamped.

    Referential gate (CD.33 cl.8 / D-5): with `require_exists=True` (the update path), the
    in-transaction existing-row lookup must be non-empty -- an absent merge key raises ReferentialError
    BEFORE any MERGE, replacing the prior permissive upsert-on-absent.

    Concurrency (CD.33): a serialization collision is retried with bounded backoff+jitter up to
    `max_attempts`; exhaustion raises OCCRetryExhaustedError (loud-fail, Decision 55). A non-OCC
    error propagates immediately -- never swallowed.

    Emits OccRetryCount + CommitLatencyMs via `metric_sink` (EC9) when provided.
    """
    semantics = semantics if semantics is not None else load_field_semantics()
    schema_gate(record, semantics, table=table)  # loud-fail before any catalog work

    spec = resolve_table_spec(table, semantics)
    merge_history_sql = _build_merge_history_sql(spec)
    merge_current_sql = _build_merge_current_sql(spec)
    select_existing_sql = _build_select_existing_created_sql(spec)

    identity = identity if identity is not None else mint_write_identity()
    key = record[spec.merge_key]

    occ_retries = 0
    start = time.perf_counter()
    attempt = 0
    created_ts: datetime = identity.timestamp

    while True:
        attempt += 1
        try:
            con.execute("BEGIN TRANSACTION")
            existing = con.execute(select_existing_sql, [key]).fetchall()
            if require_exists and not existing:
                raise ReferentialError(
                    f"update of absent {spec.merge_key}={key!r} in {spec.current_table}: the record does "
                    "not exist (CD.33 cl.8 / D-5). An absent rec loud-fails -- it is not silently created."
                )
            created_ts = existing[0][0] if existing else identity.timestamp
            params = _write_params(spec, record, identity, created_ts)
            con.execute(merge_history_sql, params)
            con.execute(merge_current_sql, params)
            con.execute("COMMIT")
            break
        except ReferentialError:
            _safe_rollback(con)
            raise  # referential failure is terminal, never retried
        except Exception as exc:  # noqa: BLE001 -- classify, then retry-or-raise
            _safe_rollback(con)
            if is_occ_collision(exc):
                if attempt < max_attempts:
                    occ_retries += 1
                    _occ_backoff(attempt, sleep=sleep)
                    continue
                commit_ms = (time.perf_counter() - start) * 1000.0
                _emit_write_metrics(metric_sink, occ_retries, commit_ms)
                raise OCCRetryExhaustedError(
                    f"OCC retry budget exhausted after {attempt} attempts for {spec.merge_key}={key!r} "
                    f"(ulid={identity.ulid}). Stop and RCA the contention (Decision 55) -- do NOT "
                    "relax the budget."
                ) from exc
            raise  # non-OCC hard failure: loud-fail immediately

    commit_ms = (time.perf_counter() - start) * 1000.0
    _emit_write_metrics(metric_sink, occ_retries, commit_ms)
    return WriteResult(
        ulid=identity.ulid,
        rec_id=key,
        occ_retries=occ_retries,
        commit_ms=commit_ms,
        created_timestamp=created_ts,
        last_updated_timestamp=identity.timestamp,
    )


def _safe_rollback(con: Any) -> None:
    """Roll back the current transaction, swallowing a 'no active transaction' error only."""
    try:
        con.execute("ROLLBACK")
    except Exception:  # noqa: BLE001 -- rollback failure must not mask the original error
        pass


def _emit_write_metrics(metric_sink: Optional[Callable[[str, float], None]], occ_retries: int, commit_ms: float) -> None:
    """Emit the OccRetryCount + CommitLatencyMs metrics through the sink, if provided."""
    if metric_sink is None:
        return
    metric_sink("OccRetryCount", float(occ_retries))
    metric_sink("CommitLatencyMs", commit_ms)


# ---------------------------------------------------------------------------
# Read primitive
# ---------------------------------------------------------------------------


def read_current(
    con: Any, *, table: str | None = None, rec_id: str | None = None, key: str | None = None, limit: int | None = None
) -> list[dict[str, Any]]:
    """Return rows from the current write-through projection (latest version per merge key).

    `table=None` reads the smoke current table (T2.17); a name selects an ops_tables entry (T2.19).
    `key` (or the back-compat `rec_id` alias) filters to a single record (the bucket-partitioned
    single-key lookup). `limit` bounds the row count. Returns a list of column-keyed dicts.
    """
    spec = resolve_table_spec(table)
    cols = ", ".join(c for c, _ in spec.ordered_columns)
    sql = f"SELECT {cols} FROM {CATALOG_ALIAS}.{spec.current_table}"
    filter_value = key if key is not None else rec_id
    params: list[Any] = []
    if filter_value is not None:
        sql += f" WHERE {spec.merge_key} = ?"
        params.append(filter_value)
    sql += f" ORDER BY {spec.merge_key}"
    if limit is not None:
        sql += f" LIMIT {int(limit)}"
    cursor = con.execute(sql, params) if params else con.execute(sql)
    col_names = [desc[0] for desc in cursor.description]
    return [dict(zip(col_names, row)) for row in cursor.fetchall()]


def read_history(
    con: Any, *, table: str | None = None, key: str | None = None, limit: int | None = None
) -> list[dict[str, Any]]:
    """Return append-history rows for *table* (optionally a single merge key), newest-first."""
    spec = resolve_table_spec(table)
    cols = ", ".join(c for c, _ in spec.ordered_columns)
    sql = f"SELECT {cols} FROM {CATALOG_ALIAS}.{spec.history_table}"
    params: list[Any] = []
    if key is not None:
        sql += f" WHERE {spec.merge_key} = ?"
        params.append(key)
    sql += " ORDER BY last_updated_timestamp DESC, ulid DESC"
    if limit is not None:
        sql += f" LIMIT {int(limit)}"
    cursor = con.execute(sql, params) if params else con.execute(sql)
    col_names = [desc[0] for desc in cursor.description]
    return [dict(zip(col_names, row)) for row in cursor.fetchall()]


def query_current(con: Any, *, table: str, sql: str, params: list[Any] | tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    """Run a read-only *sql* over the current projection of *table*. Use `{tbl}` for the table ref.

    Mirrors the Reader.query semantics: the caller supplies a SELECT referencing `{tbl}`; `?` binds
    params. The reader Lambda exposes this so the portal/sync read paths can push predicates down.
    """
    spec = resolve_table_spec(table)
    final_sql = sql.replace("{tbl}", f"{CATALOG_ALIAS}.{spec.current_table}")
    cursor = con.execute(final_sql, list(params)) if params else con.execute(final_sql)
    col_names = [desc[0] for desc in cursor.description]
    return [dict(zip(col_names, row)) for row in cursor.fetchall()]


# ---------------------------------------------------------------------------
# CloudWatch metric emission (EC9)
# ---------------------------------------------------------------------------


def emit_metric(
    name: str,
    value: float,
    *,
    namespace: str = CLOUDWATCH_NAMESPACE,
    unit: str = "None",
    profile: str | None = None,
    client: Any = None,
) -> None:
    """Emit a single CloudWatch metric datum. Best-effort: a metrics failure must not fail a write.

    Pass `client` to inject a CloudWatch client (tests / a shared client). In the Lambda the ambient
    execution-role credentials are used (no profile).
    """
    try:
        if client is None:
            import boto3  # noqa: PLC0415

            from scripts.aws_profile import resolve_aws_profile  # noqa: PLC0415

            session = boto3.Session(profile_name=resolve_aws_profile(profile))
            client = session.client("cloudwatch")
        client.put_metric_data(
            Namespace=namespace,
            MetricData=[{"MetricName": name, "Value": float(value), "Unit": unit}],
        )
    except Exception:  # noqa: BLE001 -- metrics are observability, never a write-blocking failure
        pass


def make_metric_sink(
    *, namespace: str = CLOUDWATCH_NAMESPACE, client: Any = None, profile: str | None = None
) -> Callable[[str, float], None]:
    """Build a metric_sink(name, value) closure for write_scd2 that emits to CloudWatch."""

    def _sink(name: str, value: float) -> None:
        unit = "Milliseconds" if name.endswith("Ms") else "Count"
        emit_metric(name, value, namespace=namespace, unit=unit, client=client, profile=profile)

    return _sink
