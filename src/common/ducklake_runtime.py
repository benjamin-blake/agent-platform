# complexity-waiver: decision-43
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
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from src.common import ducklake_spike
from src.common.ducklake_scd2_schema import (
    _DEFAULT_FIELD_SEMANTICS_PATH,  # noqa: F401 -- re-exported for backward compat
    _FIELD_SEMANTICS_ENV,  # noqa: F401 -- re-exported for backward compat
    _PY_TYPE_FOR_SQL,  # noqa: F401 -- re-exported for backward compat
    CATALOG_ALIAS,
    NAMED_READS,
    NAMED_READS_VERSION,  # noqa: F401 -- re-exported for the reader handler response envelope
    SMOKE_CURRENT_TABLE,  # noqa: F401 -- re-exported for backward compat
    SMOKE_HISTORY_TABLE,  # noqa: F401 -- re-exported for backward compat
    DuckLakeRuntimeError,
    NamedRead,  # noqa: F401 -- re-exported for tests/clients introspecting the registry
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
    connect_timeout is bounded (default 10s, overridable via DUCKLAKE_CONNECT_TIMEOUT_S) so a
    stale/unreachable endpoint fails fast with a precise libpq error instead of hanging to the
    120s Lambda wall.
    """
    import os  # noqa: PLC0415

    sslmode = dsn.get("sslmode") or "require"
    timeout = int(os.environ.get("DUCKLAKE_CONNECT_TIMEOUT_S", "10"))
    base = f"dbname={dsn['dbname']} host={dsn['host']} user={dsn['username']} password={dsn['password']}"
    return f"{base} sslmode={sslmode} connect_timeout={timeout}"


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
# Warm-connection cache (neon-egress-reduction D2).
#
# A fresh ATTACH per Lambda invocation is the dominant Neon catalog-egress driver: DuckDB's postgres
# scanner sequential-COPYs ducklake_file_column_stats per query (ducklake #859), and re-ATTACHing
# every request pays that metadata transfer again and again. Reusing ONE connection across sequential
# warm invocations on the same container eliminates the repeated ATTACH (and its metadata egress).
#
# This is a per-container module global for SEQUENTIAL request handling (a Lambda container serves one
# invocation at a time). The 8-thread churn harness MUST NOT use it -- it opens an independent
# connection per thread via open_connection (constraint: never share the cached connection across
# threads). A dead session (Neon scale-to-zero) is handled as the ONE expected reopen condition
# (Decision 55: any other error still raises).
# ---------------------------------------------------------------------------

_WARM_CONNECTION_LOCK = threading.Lock()
_warm_connection: dict[str, Any] = {}

# Connection-failure signatures treated as the expected dead-catalog-session condition (Neon
# scale-to-zero suspended the underlying Postgres session, or the cached DuckDB connection was closed).
# DELIBERATELY SPECIFIC PHRASES, not the bare word "connection": a capacity error ("too many
# connections for role", "remaining connection slots are reserved") or an auth failure ("password
# authentication failed") must FAIL LOUD, not be silently reopened+retried (Decision 55 -- the one
# expected transient is a dropped/closed session, never pool-exhaustion or auth). See
# test_non_dead_errors_do_not_match for the excluded false-positives.
_DEAD_CONNECTION_SIGNATURES = (
    "connection refused",
    "connection reset",
    "connection already closed",  # DuckDB closed-connection
    "connection timed out",
    "the connection is closed",
    "server closed",  # "server closed the connection unexpectedly"
    "terminating connection",
    "could not connect",
    "no connection to the server",
    "ssl connection has been closed",
    "database has been invalidated",
)


def is_dead_connection_error(exc: BaseException) -> bool:
    """True iff *exc* matches the expected dead-catalog-session signature (Neon scale-to-zero / closed).

    The narrow allow-list keeps the warm-connection reopen scoped to the ONE expected transient
    (Decision 55: no catch-and-relax) -- any other failure still propagates at the call site.
    """
    msg = str(exc).lower()
    return any(sig in msg for sig in _DEAD_CONNECTION_SIGNATURES)


def _probe_connection_alive(con: Any, probe_sql: str) -> bool:
    """Cheap liveness probe. Returns False when the probe raises (closed/dead connection)."""
    try:
        con.execute(probe_sql).fetchall()
        return True
    except Exception:  # noqa: BLE001 -- any probe failure means reopen; the reopen itself loud-fails
        return False


def reset_warm_connection() -> None:
    """Close + clear the per-container warm connection (test teardown / explicit drop)."""
    with _WARM_CONNECTION_LOCK:
        con = _warm_connection.pop("con", None)
        _warm_connection.pop("key", None)
    if con is not None:
        try:
            con.close()
        except Exception:  # noqa: BLE001
            pass


def get_warm_connection(
    *,
    dsn: dict[str, str] | None = None,
    dsn_factory: Callable[[], dict[str, str]] | None = None,
    opener: Callable[[], Any] | None = None,
    data_path: str = SMOKE_DATA_PATH,
    meta_schema: str = META_SCHEMA,
    extension_directory: str | None = None,
    profile: str | None = None,
    _creds: tuple[str, str, str | None, str] | None = None,
    probe_sql: str = "SELECT 1",
    force_reopen: bool = False,
) -> tuple[Any, dict[str, Any]]:
    """Return a per-container cached DuckLake connection, reusing the ATTACH across SEQUENTIAL warm
    invocations (neon-egress-reduction D2).

    The first call in a container opens + ATTACHes and caches the connection; subsequent invocations
    on the same warm container reuse it -- no re-ATTACH, so no per-invocation re-COPY of
    ducklake_file_column_stats (ducklake #859) and therefore no repeated Neon metadata egress. The
    cached connection is validated by a cheap liveness probe; a dead session (Neon scale-to-zero) or a
    cross-catalog key change triggers a transparent reopen.

    *dsn* / *dsn_factory* / *opener*: supply the catalog DSN directly, a DSN factory, or a full
    connection opener (zero-arg). All are invoked ONLY when (re)opening, so the warm-reuse path does
    not re-fetch Secrets Manager or re-ATTACH. *opener* takes precedence (the reader/writer handlers
    pass their existing _open_*_connection so the open seam stays single).

    Returns (connection, meta) where meta = {"reused": bool, "reopened": bool, "connect_ms": float}.
    connect_ms is 0.0 on reuse (no ATTACH) and the real open cost on a (re)open -- so warm reuse is
    observable in the handler response.

    CONCURRENCY: per-container module global for SEQUENTIAL handling only. The churn harness opens its
    own per-thread connections via open_connection and MUST NOT call this.
    """
    key = (data_path, meta_schema, extension_directory)
    with _WARM_CONNECTION_LOCK:
        cached = _warm_connection.get("con")
        cached_key = _warm_connection.get("key")
        had_cached = cached is not None
        if not force_reopen and cached is not None and cached_key == key and _probe_connection_alive(cached, probe_sql):
            return cached, {"reused": True, "reopened": False, "connect_ms": 0.0}

        # (Re)open: discard a stale / dead / cross-catalog cached connection first.
        if cached is not None:
            try:
                cached.close()
            except Exception:  # noqa: BLE001
                pass
            _warm_connection.pop("con", None)
            _warm_connection.pop("key", None)

        t0 = time.perf_counter()
        if opener is not None:
            con = opener()
        else:
            resolved_dsn = dsn if dsn is not None else (dsn_factory() if dsn_factory is not None else None)
            if resolved_dsn is None:
                raise DuckLakeRuntimeError("get_warm_connection requires a dsn, dsn_factory, or opener")
            con = open_connection(
                dsn=resolved_dsn,
                data_path=data_path,
                meta_schema=meta_schema,
                extension_directory=extension_directory,
                profile=profile,
                _creds=_creds,
            )
        connect_ms = (time.perf_counter() - t0) * 1000.0
        _warm_connection["con"] = con
        _warm_connection["key"] = key
        # reopened=True means a previously-cached (dead/stale) connection was replaced (not a cold start).
        return con, {"reused": False, "reopened": had_cached, "connect_ms": round(connect_ms, 2)}


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


def reconcile_table_columns(con: Any, *, table: str) -> dict[str, list[str]]:
    """Add any spec columns missing from the physical history+current tables (idempotent via introspection).

    Reads the column spec from the field_semantics.yaml contract via resolve_table_spec, introspects
    the physical tables using DuckDB information_schema, and issues ALTER TABLE ADD COLUMN for each
    spec column absent from the live table. Idempotency is guaranteed by the pre-check (not SQL IF NOT
    EXISTS -- there is no ADD COLUMN IF NOT EXISTS precedent in DuckLake 1.5.3). Never DROPs.

    Args:
        con: Open DuckDB connection with the production catalog attached.
        table: ops_* table logical name (e.g. 'ops_recommendations').

    Returns:
        Dict with 'added_history' and 'added_current' lists of column names added per table.
    """
    spec = resolve_table_spec(table)
    history_fq = f"{CATALOG_ALIAS}.{spec.history_table}"
    current_fq = f"{CATALOG_ALIAS}.{spec.current_table}"

    def _physical_columns(table_fq: str) -> set[str]:
        rows = con.execute(
            f"SELECT column_name FROM information_schema.columns "
            f"WHERE table_catalog = '{CATALOG_ALIAS}' "
            f"AND table_name = '{table_fq.split('.')[-1]}' "
            f"ORDER BY ordinal_position"
        ).fetchall()
        if not rows:
            rows = con.execute(f"PRAGMA table_info('{table_fq}')").fetchall()
            return {r[1] for r in rows}
        return {r[0] for r in rows}

    added_history: list[str] = []
    added_current: list[str] = []

    for table_fq, added_list in [(history_fq, added_history), (current_fq, added_current)]:
        existing = _physical_columns(table_fq)
        for col_name, col_spec in spec.fields.items():
            if col_name in existing:
                continue
            sql_type = col_spec.get("sql_type", "VARCHAR")
            nullable = col_spec.get("nullable", True)
            null_clause = "" if nullable else " NOT NULL"
            con.execute(f"ALTER TABLE {table_fq} ADD COLUMN {col_name} {sql_type}{null_clause}")
            added_list.append(col_name)

    return {"added_history": added_history, "added_current": added_current}


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

    `created_override` (operational backfill/re-seed path ONLY): when set AND the row is a fresh
    insert, it supplies the historical `created_timestamp` instead of `identity.timestamp`, so a
    migration/re-seed preserves each rec's ORIGINAL created time (Decision-64 anchor) while
    `identity.timestamp` carries the original last_updated. It has NO effect on the agent write path
    (always None there). The maintenance `seed_ops_recommendations` action that used this was removed
    at the 2026-06-09 recs sign-off; the parameter is retained for any future break-glass re-seed.

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
            _advance_entity_counter(con, spec, key)
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


# ---------------------------------------------------------------------------
# Writer-owned entity-id allocation (Decision 84 I-2)
# ---------------------------------------------------------------------------

# Plain (non-SCD2) DuckLake bookkeeping table. The counter row is the keyspace serialization
# point: a concurrent file_scd2 pair both UPDATE the same row, which is a guaranteed write-write
# catalog conflict -- one commits, the other OCC-retries and re-allocates. Internal to the writer;
# never exposed through the read boundary.
ENTITY_COUNTERS_TABLE = "ops_entity_counters"


def ensure_entity_counters_table(con: Any) -> None:
    """Idempotently create the entity-counters bookkeeping table."""
    con.execute(
        f"CREATE TABLE IF NOT EXISTS {CATALOG_ALIAS}.{ENTITY_COUNTERS_TABLE} "
        "(counter_name VARCHAR NOT NULL, current_value BIGINT NOT NULL)"
    )


def bootstrap_entity_counter(con: Any, spec: Any) -> int:
    """Serially (re)seed the counter row for *spec* from the history-table numeric max.

    MUST run as a one-time serial bootstrap (create_ops_tables), never on the allocation hot
    path: a concurrent self-seed INSERT race under snapshot isolation creates duplicate counter
    rows that each transaction increments privately -- observed live 2026-06-11 as four
    concurrent file_ops all allocating the same id. DELETE + single INSERT here is idempotent
    and also repairs that duplicate-row state. Returns the seeded value.
    """
    if not spec.entity_id_prefix or spec.id_keyspace != "writer":
        raise DuckLakeRuntimeError(
            f"table {spec.table!r} has no writer-owned keyspace (id_keyspace={spec.id_keyspace!r}): "
            "it has no allocation counter to seed"
        )
    prefix = spec.entity_id_prefix
    ensure_entity_counters_table(con)
    con.execute("BEGIN TRANSACTION")
    try:
        seed_row = con.execute(
            f"SELECT coalesce(max(CAST(regexp_extract({spec.merge_key}, '^{prefix}([0-9]+)$', 1) AS BIGINT)), 0) "
            f"FROM {CATALOG_ALIAS}.{spec.history_table} "
            f"WHERE {spec.merge_key} LIKE '{prefix}%' AND regexp_matches({spec.merge_key}, '^{prefix}[0-9]+$')"
        ).fetchone()
        seed = int(seed_row[0]) if seed_row and seed_row[0] is not None else 0
        con.execute(f"DELETE FROM {CATALOG_ALIAS}.{ENTITY_COUNTERS_TABLE} WHERE counter_name = ?", [spec.table])
        con.execute(f"INSERT INTO {CATALOG_ALIAS}.{ENTITY_COUNTERS_TABLE} VALUES (?, ?)", [spec.table, seed])
        con.execute("COMMIT")
    except Exception:
        _safe_rollback(con)
        raise
    return seed


def _allocate_entity_id(con: Any, spec: Any) -> str:
    """Allocate the next <prefix>NNN id for *spec* INSIDE the caller's open transaction.

    Requires the counter row to exist (bootstrap_entity_counter): every allocating transaction
    then UPDATEs the SAME shared row, which is the write-write conflict DuckLake's OCC detects --
    one committer wins, the rest retry and re-read. A missing or duplicated counter row is a
    terminal loud-fail (never self-seeded here; see bootstrap_entity_counter for why).
    """
    prefix = spec.entity_id_prefix
    if not prefix or spec.id_keyspace != "writer":
        raise DuckLakeRuntimeError(
            f"table {spec.table!r} has no writer-owned keyspace (id_keyspace={spec.id_keyspace!r}): "
            "file_ops allocation is not enabled for it (Decision 84 I-2)"
        )
    counter = f"{spec.table}"
    rows = con.execute(
        f"SELECT current_value FROM {CATALOG_ALIAS}.{ENTITY_COUNTERS_TABLE} WHERE counter_name = ?", [counter]
    ).fetchall()
    if len(rows) != 1:
        raise DuckLakeRuntimeError(
            f"entity counter for {counter!r} has {len(rows)} rows (expected exactly 1): "
            "run create_ops_tables to bootstrap/repair the counter (Decision 84 I-2). "
            "Allocation never self-seeds -- the concurrent-seed race mints duplicate ids."
        )
    # DuckLake does not support UPDATE ... RETURNING; the UPDATE is the write-write conflict
    # point and the follow-up SELECT reads our own uncommitted increment inside the transaction.
    con.execute(
        f"UPDATE {CATALOG_ALIAS}.{ENTITY_COUNTERS_TABLE} SET current_value = current_value + 1 WHERE counter_name = ?",
        [counter],
    )
    allocated = con.execute(
        f"SELECT current_value FROM {CATALOG_ALIAS}.{ENTITY_COUNTERS_TABLE} WHERE counter_name = ?",
        [counter],
    ).fetchone()
    n = int(allocated[0])
    return f"{prefix}{n:03d}"


def _advance_entity_counter(con: Any, spec: Any, key: Any) -> None:
    """Advance the allocation counter to cover a caller-keyed canonical id, in the open transaction.

    write_ops accepts caller-keyed <prefix>NNN ids (backfill; pre-merge main clients on the old
    allocator). Without this, any such id above the counter strands file_ops on the terminal
    "counter behind table max" guard until an operator re-bootstraps. No-op when the table has no
    writer-owned keyspace, the key is non-canonical, or the counter row is absent (not bootstrapped).
    """
    if spec.id_keyspace != "writer" or not spec.entity_id_prefix:
        return
    m = re.fullmatch(re.escape(spec.entity_id_prefix) + r"([0-9]+)", str(key))
    if not m:
        return
    con.execute(
        f"UPDATE {CATALOG_ALIAS}.{ENTITY_COUNTERS_TABLE} SET current_value = GREATEST(current_value, ?) "
        "WHERE counter_name = ?",
        [int(m.group(1)), spec.table],
    )


def file_scd2(
    con: Any,
    record: dict[str, Any],
    *,
    table: str,
    identity: WriteIdentity | None = None,
    semantics: dict[str, Any] | None = None,
    max_attempts: int = OCC_MAX_ATTEMPTS,
    metric_sink: Optional[Callable[[str, float], None]] = None,
    sleep: Callable[[float], None] = time.sleep,
) -> WriteResult:
    """Create one record, allocating its merge key INSIDE the write transaction (Decision 84 I-2).

    The record arrives WITHOUT the merge key; allocation, the require-absent check, and both MERGEs
    commit atomically. An OCC retry re-runs the whole transaction including allocation, so the
    retried attempt picks up a fresh max -- the counter-row UPDATE is the serialization point.

    Invocation idempotency (response-lost retry): `identity` is minted by the CALLER per logical
    file operation and replayed unchanged on retry. The in-transaction replay check (history ULID
    lookup) returns the originally allocated id instead of allocating anew, so a client retry after
    a lost response never double-files.
    """
    semantics = semantics if semantics is not None else load_field_semantics()
    spec = resolve_table_spec(table, semantics)
    if not spec.entity_id_prefix or spec.id_keyspace != "writer":
        raise DuckLakeRuntimeError(
            f"table {table!r} has no writer-owned keyspace (id_keyspace={spec.id_keyspace!r}): "
            "file_ops allocation is not enabled for it (Decision 84 I-2)"
        )
    if spec.merge_key in record:
        raise SchemaGateError(f"file operation must not supply {spec.merge_key!r}: the writer allocates it (Decision 84 I-2)")
    # Fail fast on every OTHER contract violation before touching the catalog: gate a copy with a
    # syntactically-valid placeholder key (the real key does not exist yet).
    schema_gate({**record, spec.merge_key: f"{spec.entity_id_prefix or 'x-'}0"}, semantics, table=table)

    merge_history_sql = _build_merge_history_sql(spec)
    merge_current_sql = _build_merge_current_sql(spec)
    select_existing_sql = _build_select_existing_created_sql(spec)
    identity = identity if identity is not None else mint_write_identity()

    occ_retries = 0
    start = time.perf_counter()
    attempt = 0

    while True:
        attempt += 1
        try:
            con.execute("BEGIN TRANSACTION")
            # Replay check: a retried invocation carries the same ULID; return the original allocation.
            replay = con.execute(
                f"SELECT {spec.merge_key}, created_timestamp FROM {CATALOG_ALIAS}.{spec.history_table} WHERE ulid = ?",
                [identity.ulid],
            ).fetchall()
            if replay:
                con.execute("COMMIT")
                commit_ms = (time.perf_counter() - start) * 1000.0
                _emit_write_metrics(metric_sink, occ_retries, commit_ms)
                return WriteResult(
                    ulid=identity.ulid,
                    rec_id=replay[0][0],
                    occ_retries=occ_retries,
                    commit_ms=commit_ms,
                    created_timestamp=replay[0][1],
                    last_updated_timestamp=identity.timestamp,
                )
            key = _allocate_entity_id(con, spec)
            existing = con.execute(select_existing_sql, [key]).fetchall()
            if existing:
                raise DuckLakeRuntimeError(
                    f"allocated {spec.merge_key}={key!r} already exists in {spec.current_table}: "
                    "counter behind table max -- stop and RCA (Decision 55), do not retry past it"
                )
            params = _write_params(spec, {**record, spec.merge_key: key}, identity, identity.timestamp)
            con.execute(merge_history_sql, params)
            con.execute(merge_current_sql, params)
            con.execute("COMMIT")
            commit_ms = (time.perf_counter() - start) * 1000.0
            _emit_write_metrics(metric_sink, occ_retries, commit_ms)
            return WriteResult(
                ulid=identity.ulid,
                rec_id=key,
                occ_retries=occ_retries,
                commit_ms=commit_ms,
                created_timestamp=identity.timestamp,
                last_updated_timestamp=identity.timestamp,
            )
        except DuckLakeRuntimeError:
            _safe_rollback(con)
            raise  # contract/keyspace failures are terminal, never retried
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
                    f"OCC retry budget exhausted after {attempt} attempts for file_ops on {table} "
                    f"(ulid={identity.ulid}). Stop and RCA the contention (Decision 55)."
                ) from exc
            raise


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
    con: Any,
    *,
    table: str | None = None,
    rec_id: str | None = None,
    key: str | None = None,
    key_column: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Return rows from the current write-through projection (latest version per merge key).

    `table=None` reads the smoke current table (T2.17); a name selects an ops_tables entry (T2.19).
    `key` (or the back-compat `rec_id` alias) filters to a single value; `key_column` names the
    filtered column and is VALIDATED against the spec (defaults to the merge key). The structural
    (column, value) pair replaces SQL-fragment filters at this boundary (rec-2170: a value bound
    against the wrong column returned a silent false zero). `limit` bounds the row count.
    """
    spec = resolve_table_spec(table)
    cols = ", ".join(c for c, _ in spec.ordered_columns)
    sql = f"SELECT {cols} FROM {CATALOG_ALIAS}.{spec.current_table}"
    filter_value = key if key is not None else rec_id
    filter_column = key_column if key_column is not None else spec.merge_key
    if filter_column not in spec.fields:
        raise DuckLakeRuntimeError(
            f"unknown filter column {filter_column!r} for {spec.current_table}: not in the field-semantics contract"
        )
    params: list[Any] = []
    if filter_value is not None:
        sql += f" WHERE {filter_column} = ?"
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


def named_read(con: Any, *, verb: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Execute a pre-established read verb from the NAMED_READS registry (Decision 84 I-3).

    The SQL is server-side registry content; the caller supplies only the verb name and named
    bind params. Param presence is validated against the verb's declared param list; `{tbl}` and
    `{hist}` resolve to the verb's table current/history pair. Loud-fail on an unknown verb or a
    missing/extra param.
    """
    entry = NAMED_READS.get(verb)
    if entry is None:
        raise DuckLakeRuntimeError(f"unknown read verb {verb!r}: expected one of {sorted(NAMED_READS)}")
    supplied = dict(params or {})
    if set(supplied) != set(entry.params):
        raise DuckLakeRuntimeError(f"read verb {verb!r} requires params {list(entry.params)}; got {sorted(supplied)}")
    spec = resolve_table_spec(entry.table)
    final_sql = entry.sql.replace("{tbl}", f"{CATALOG_ALIAS}.{spec.current_table}").replace(
        "{hist}", f"{CATALOG_ALIAS}.{spec.history_table}"
    )
    bound = [supplied[name] for name in entry.params]
    cursor = con.execute(final_sql, bound) if bound else con.execute(final_sql)
    col_names = [desc[0] for desc in cursor.description]
    return [dict(zip(col_names, row)) for row in cursor.fetchall()]


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
