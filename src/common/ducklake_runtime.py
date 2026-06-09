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

The pure schema layer (spec/SQL builders/gate) lives in ducklake_scd2_schema; this module
owns the execution layer (connection, OCC transaction, reads, metrics). Dependency is strictly
one-directional: runtime imports schema, never the reverse.
"""

from __future__ import annotations

import random
import re
import time
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from src.common import ducklake_spike
from src.common.ducklake_scd2_schema import (
    _DEFAULT_FIELD_SEMANTICS_PATH,  # noqa: F401 -- re-exported for backward compat
    _FIELD_SEMANTICS_ENV,  # noqa: F401 -- re-exported for backward compat
    _PY_TYPE_FOR_SQL,  # noqa: F401 -- re-exported for backward compat
    CATALOG_ALIAS,
    SMOKE_CURRENT_TABLE,  # noqa: F401 -- re-exported for backward compat
    SMOKE_HISTORY_TABLE,  # noqa: F401 -- re-exported for backward compat
    DuckLakeRuntimeError,
    ReferentialError,
    ScdTableSpec,  # noqa: F401 -- re-exported for backward compat
    SchemaGateError,
    WriteIdentity,
    WriteResult,
    _build_merge_current_sql,
    _build_merge_history_sql,
    _build_select_existing_created_sql,
    _column_ddl,
    _field_semantics_path,  # noqa: F401 -- re-exported for backward compat
    _load_field_semantics_cached,  # noqa: F401 -- re-exported for backward compat
    _order_columns,  # noqa: F401 -- re-exported for backward compat
    _write_params,
    load_field_semantics,
    ops_table_names,  # noqa: F401 -- re-exported for backward compat
    resolve_table_spec,
    schema_gate,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PINNED_DUCKDB_VERSION = "1.5.3"  # lockstep with DuckLake v1.0 (OQ.12); Lambda layer pins ==1.5.3

DSN_SECRET_ID = "ducklake-neon-catalog-dsn"
META_SCHEMA = "ducklake_ops"

# Smoke uses a DEDICATED meta-schema so it can never collide with the production catalog. rec-2099
# root cause: T2.17 smoke initialized `ducklake_ops` at the smoke DATA_PATH, and DATA_PATH is pinned
# per meta-schema, so a later production ATTACH at `ducklake/` fails. Each meta-schema is an
# independent DuckLake catalog in the same Neon Postgres -- production attaches `ducklake_ops`, smoke
# attaches `ducklake_smoke` -- so their DATA_PATH pins never conflict.
SMOKE_META_SCHEMA = "ducklake_smoke"

# Representative SCD2 smoke-table pair (real ops_* business schema is T2.19).
SMOKE_DATA_PATH = "s3://agent-platform-data-lake/ducklake-neon-smoke/"

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


# ---------------------------------------------------------------------------
# Exceptions -- loud-fail conditions specific to the execution layer
# ---------------------------------------------------------------------------


class VersionMismatchError(DuckLakeRuntimeError):
    """Raised when the live DuckDB version differs from the pinned lockstep version (OQ.12)."""


class OCCRetryExhaustedError(DuckLakeRuntimeError):
    """Raised when the bounded OCC-retry budget is exhausted (CD.33). Stop-and-RCA, never relax."""


# ---------------------------------------------------------------------------
# Write identity (minted once, outside the OCC-retry loop)
# ---------------------------------------------------------------------------


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
    meta_schema: str = META_SCHEMA,
    extension_directory: str | None = None,
    profile: str | None = None,
    _creds: tuple[str, str, str | None, str] | None = None,
) -> Any:
    """Open a DuckDB connection with ducklake/httpfs/postgres loaded and the Neon catalog ATTACHed.

    extension_directory:
      - None  -> dev/smoke mode: network INSTALL + LOAD of each extension.
      - set   -> Lambda baked mode: LOAD from the directory with autoload/autoinstall DISABLED and
                 custom_extension_repository EMPTY (fail-closed: no network INSTALL at runtime).

    meta_schema selects the DuckLake catalog: production attaches `ducklake_ops` (the default
    META_SCHEMA), smoke attaches `SMOKE_META_SCHEMA` (`ducklake_smoke`). Each meta-schema is an
    independent catalog in the same Neon Postgres, so their pinned DATA_PATHs never collide (rec-2099).

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
        f"ATTACH 'ducklake:postgres:{conninfo}' AS {CATALOG_ALIAS} (DATA_PATH '{data_path}', META_SCHEMA '{meta_schema}')"
    )
    return con


# ---------------------------------------------------------------------------
# Table DDL -- CREATE + partition transforms BEFORE first write (post-ALTER-only, M-5)
# ---------------------------------------------------------------------------


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
    created_override: datetime | None = None,
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

    `created_override` (operational seed path ONLY -- the maintenance `seed_ops_recommendations`
    bootstrap): when set AND the row is a fresh insert, it supplies the historical `created_timestamp`
    instead of `identity.timestamp`, so a one-time migration preserves each rec's ORIGINAL created time
    (Decision-64 anchor) while `identity.timestamp` carries the original last_updated. It has NO effect
    on the agent write path (always None there).

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
            created_ts = (
                existing[0][0] if existing else (created_override if created_override is not None else identity.timestamp)
            )
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


def assert_read_only_sql(sql: str) -> None:
    """Loud-fail unless *sql* is a read-only statement (SELECT/WITH only).

    The reader holds the full Neon catalog credential; S3-read-only IAM blocks Parquet writes but NOT
    Postgres catalog DDL (DROP/ALTER TABLE on the DuckLake metadata). This verb guard is the
    application-layer half of the closed read boundary (OQ.7): a non-SELECT statement never reaches
    the catalog. Reject anything whose first keyword is not SELECT or WITH (CTE) -- this also blocks
    a multi-statement payload (the leading verb of a `SELECT 1; DROP TABLE x` is SELECT, but DuckDB
    rejects multi-statement in one execute; the guard plus single-statement execution close it).
    """
    if not re.match(r"^\s*(?:SELECT|WITH)\b", sql, re.IGNORECASE):
        raise SchemaGateError(
            "read-only boundary: only SELECT/WITH statements may execute on the reader path "
            f"(got {sql.strip()[:60]!r}). Catalog DDL/DML is denied at the closed boundary (OQ.7)."
        )
    if ";" in sql.rstrip().rstrip(";"):
        raise SchemaGateError("read-only boundary: multi-statement SQL is rejected on the reader path (OQ.7).")


def query_current(con: Any, *, table: str, sql: str, params: list[Any] | tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    """Run a read-only *sql* over the current projection of *table*. Use `{tbl}` for the table ref.

    Mirrors the Reader.query semantics: the caller supplies a SELECT referencing `{tbl}`; `?` binds
    params. The reader Lambda exposes this so the portal/sync read paths can push predicates down.
    A read-only verb guard (assert_read_only_sql) rejects any non-SELECT/WITH statement BEFORE it
    reaches the catalog -- catalog DDL is not blocked by the S3-read-only IAM, so the guard is the
    application-layer half of the closed read boundary (OQ.7 / CD.33 clause 6).
    """
    assert_read_only_sql(sql)
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
