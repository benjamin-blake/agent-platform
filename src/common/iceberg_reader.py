"""Engine-agnostic reader protocol and DuckDB-on-Iceberg implementation.

The Reader protocol defines the minimal verb surface so an Athena-backed
sibling can satisfy it without changing call sites (CD.8 engine-interchangeability).
DuckDBIcebergReader is the default implementation: pyiceberg GlueCatalog -> Arrow
-> DuckDB in-process, with predicate/projection pushdown into pyiceberg .scan()
and SCD2 dedup applied in DuckDB SQL.

Current state qualification:
- ops_recommendations, ops_decisions: ROW_NUMBER() OVER (PARTITION BY id
  ORDER BY last_updated_timestamp DESC) = 1  (Decision 56)
- ops_priority_queue: correlated subquery returning all entries from the
  latest curator run identified by queue_run_id  (Decision 70)

Credential resolution: resolve_aws_profile() returns the named agent_platform
profile when present (local / Claude-Code-on-the-web) and None when running
under CI OIDC (AWS_ACCESS_KEY_ID in environment), letting boto3 fall through
to ambient credentials.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any, Protocol

logger = logging.getLogger(__name__)

_DEFAULT_DATABASE = "agent_platform"
_DEFAULT_REGION = "eu-west-2"
_DEFAULT_CATALOG_NAME = "agent_platform"

# DuckLake is the SOLE ops-store backend (Decision 84 I-1; the OPS_STORAGE_BACKEND rollback flag
# was retired -- the frozen Iceberg copy stopped being a coherent rollback target the day writes
# moved to DuckLake). DuckDBIcebergReader remains importable for non-ops Iceberg surfaces
# (schema-integrity drift checks against the retained estate) until the demolition apply lands.
_DUCKLAKE_READER_URL_ENV = "DUCKLAKE_READER_URL"
_DUCKLAKE_READER_FUNCTION_NAME = "agent-platform-ducklake-reader"

# SSM parameter paths declared in Lambda manifests' runtime_config[] (Decision 79 SSOT).
# Resolution order: env -> SSM -> terraform output -> GetFunctionUrlConfig.
_DUCKLAKE_READER_SSM_PATH = "/agent-platform/ducklake/reader_url"
_DUCKLAKE_WRITER_SSM_PATH = "/agent-platform/ducklake/writer_url"

# Transient reader-invoke resilience: the Neon free-tier catalog scales to zero, so the first
# read after idle can return a 5xx while the compute resumes (cold-resume). Reader ops are
# idempotent, so retry transient 5xx with backoff before loud-failing. (HTTP 502 is the observed
# cold-resume signature; 503/504 covered for completeness.)
_READER_MAX_ATTEMPTS = 3
_READER_TRANSIENT_STATUS = frozenset({502, 503, 504})
_READER_RETRY_BACKOFF_S = (2.0, 4.0)

# pk used for ROW_NUMBER() dedup (Decision 56)
_TABLE_PARTITION_KEYS: dict[str, str] = {
    "ops_recommendations": "id",
    "ops_decisions": "id",
}

# tables using correlated-subquery current-state pattern (Decision 70)
_CORRELATED_SUBQUERY_TABLES: frozenset[str] = frozenset({"ops_priority_queue"})

_ORDER_BY_DEFAULT = "last_updated_timestamp"

# Valid SQL identifier pattern -- used to guard column-name interpolation
_COL_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*$")

# Single-key equality row_filter: `<col> = '<value>'`. Both sides are extracted and sent as a
# STRUCTURAL {column, value} filter -- never interpolated into SQL.
_SINGLE_KEY_FILTER_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*'([^']*)'\s*$")


def _parse_single_key_filter(row_filter: str) -> tuple[str, str] | None:
    """Return the (column, value) pair of a `<col> = '<value>'` filter, or None if not that shape.

    rec-2170: the previous form returned only the value, discarding the column; the reader then
    bound it against the merge key (WHERE id = '<value>') -- a silent false zero for any
    non-merge-key filter. Keeping the pair makes the filter structural end to end.
    """
    m = _SINGLE_KEY_FILTER_RE.match(row_filter)
    return (m.group(1), m.group(2)) if m else None


def _resolve_function_url_via_ssm(ssm_path: str, *, profile: str | None, region: str) -> str | None:
    """Resolve a Function URL from an SSM parameter. None on any failure.

    Covers CC-web and CI environments where DUCKLAKE_*_URL is unset and there is no
    terraform binary: SSM is lighter than GetFunctionUrlConfig and requires no Lambda
    describe permission. The PlatformDev role carries ssm:GetParameter on the
    /agent-platform/ducklake/* path (Decision 81 endpoint-discovery grant).
    """
    try:
        import boto3  # noqa: PLC0415

        client = boto3.Session(profile_name=profile).client("ssm", region_name=region)
        resp = client.get_parameter(Name=ssm_path, WithDecryption=False)
        return resp["Parameter"]["Value"].rstrip("/") or None
    except Exception as exc:  # noqa: BLE001
        logger.warning("iceberg_reader: SSM resolution failed for %s: %s", ssm_path, exc)
        return None


def _resolve_function_url_via_api(function_name: str, *, profile: str | None, region: str) -> str | None:
    """Resolve a Lambda Function URL via lambda:GetFunctionUrlConfig. None on any failure.

    Last-resort fallback for environments with neither the DUCKLAKE_*_URL env nor a terraform-init'd
    checkout -- principally the CI runner (T2.19 cutover), where the github_ci OIDC role carries the
    GetFunctionUrlConfig grant. Best-effort: any error (missing grant, throttle, boto3 absent) returns
    None so the caller can raise a single actionable error.
    """
    try:
        import boto3  # noqa: PLC0415

        client = boto3.Session(profile_name=profile).client("lambda", region_name=region)
        return client.get_function_url_config(FunctionName=function_name).get("FunctionUrl")
    except Exception as exc:  # noqa: BLE001 -- best-effort fallback; caller raises if this returns None
        logger.warning("iceberg_reader: GetFunctionUrlConfig fallback failed for %s: %s", function_name, exc)
        return None


class Reader(Protocol):
    """Minimal engine-agnostic read interface.

    Both DuckDBIcebergReader and any future Athena-backed implementation must
    satisfy this protocol without changing call sites (CD.8).
    """

    def current_state(
        self,
        table: str,
        *,
        partition_by: str = "id",
        order_by: str = _ORDER_BY_DEFAULT,
        row_filter: str | None = None,
        selected_fields: tuple[str, ...] | None = None,
        snapshot_id: int | None = None,
    ) -> list[dict]: ...

    def latest_snapshot(self, table: str) -> int | None: ...


class DuckDBIcebergReader:
    """DuckDB-on-Iceberg read layer.

    pyiceberg GlueCatalog resolves the table location; .scan() applies predicate
    and projection pushdown before Arrow materialization; DuckDB executes the
    current-state SQL (SCD2 ROW_NUMBER or priority-queue correlated subquery).

    Engine is exposed directly here as a pre-Lambda bridge (CD.8 note: hiding
    behind T0.7c/T0.8 verbs is deferred until those verbs land).
    """

    def __init__(
        self,
        profile: str | None = None,
        catalog_name: str = _DEFAULT_CATALOG_NAME,
        database: str = _DEFAULT_DATABASE,
        region: str = _DEFAULT_REGION,
    ) -> None:
        self._profile = profile
        self._catalog_name = catalog_name
        self._database = database
        self._region = region
        self._catalog_instance: Any = None

    def _catalog(self) -> Any:
        if self._catalog_instance is None:
            from pyiceberg.catalog.glue import GlueCatalog  # noqa: PLC0415

            from scripts.aws_profile import resolve_aws_profile  # noqa: PLC0415

            resolved = resolve_aws_profile(self._profile)
            props: dict[str, str] = {
                "client.region": self._region,
                "s3.region": self._region,
            }
            if resolved is not None:
                props["client.profile-name"] = resolved
                props["s3.profile-name"] = resolved
            self._catalog_instance = GlueCatalog(self._catalog_name, **props)
        return self._catalog_instance

    def _load_arrow(
        self,
        table: str,
        *,
        row_filter: str | None = None,
        selected_fields: tuple[str, ...] | None = None,
        snapshot_id: int | None = None,
    ) -> Any:
        """Scan Iceberg table to a PyArrow Table with optional pushdown.

        row_filter and selected_fields are passed into pyiceberg .scan() so that
        partition pruning and column projection happen before materialisation --
        not as a post-filter on a full Arrow table.
        """
        catalog = self._catalog()
        iceberg_table = catalog.load_table(f"{self._database}.{table}")

        scan_kwargs: dict[str, Any] = {}
        if row_filter is not None:
            scan_kwargs["row_filter"] = row_filter
        if selected_fields is not None:
            scan_kwargs["selected_fields"] = selected_fields
        if snapshot_id is not None:
            scan_kwargs["snapshot_id"] = snapshot_id

        scan = iceberg_table.scan(**scan_kwargs)
        return scan.to_arrow()

    def latest_snapshot(self, table: str) -> int | None:
        """Return the id of the current snapshot for *table*, or None if the table is empty."""
        try:
            catalog = self._catalog()
            iceberg_table = catalog.load_table(f"{self._database}.{table}")
            snap = iceberg_table.current_snapshot()
            return snap.snapshot_id if snap is not None else None
        except Exception as exc:  # noqa: BLE001
            logger.warning("DuckDBIcebergReader.latest_snapshot: %s: %s", table, exc)
            return None

    def current_state(
        self,
        table: str,
        *,
        partition_by: str = "id",
        order_by: str = _ORDER_BY_DEFAULT,
        row_filter: str | None = None,
        selected_fields: tuple[str, ...] | None = None,
        snapshot_id: int | None = None,
    ) -> list[dict]:
        """Return current-state rows for *table* with SCD2 dedup applied in DuckDB.

        For ops_priority_queue: correlated subquery selecting all entries from
        the latest curator run (Decision 70).
        For all other tables: ROW_NUMBER() OVER (PARTITION BY {pk} ORDER BY
        last_updated_timestamp DESC) = 1 (Decision 56).

        Pushdown: row_filter and selected_fields are forwarded into pyiceberg
        .scan() before Arrow materialisation.

        Returns [] when the table is empty or unreachable (signals the caller
        to degrade gracefully when used from session_preflight).  Call sites
        that must raise on unreachable (Decision 69: ops_data_portal) should
        catch the exception themselves -- this method re-raises from _load_arrow.
        """
        import duckdb  # noqa: PLC0415

        for col, label in ((partition_by, "partition_by"), (order_by, "order_by")):
            if not _COL_NAME_RE.match(col):
                raise ValueError(f"DuckDBIcebergReader.current_state: invalid {label} column name: {col!r}")

        pk = _TABLE_PARTITION_KEYS.get(table, partition_by)

        arrow_table = self._load_arrow(
            table,
            row_filter=row_filter,
            selected_fields=selected_fields,
            snapshot_id=snapshot_id,
        )

        if arrow_table.num_rows == 0:
            return []

        with duckdb.connect() as con:
            con.register("_tbl", arrow_table)

            if table in _CORRELATED_SUBQUERY_TABLES:
                dedup_sql = (
                    "SELECT * FROM _tbl "
                    "WHERE queue_run_id = ("
                    "  SELECT queue_run_id FROM _tbl "
                    "  ORDER BY last_updated_timestamp DESC LIMIT 1"
                    ")"
                )
            else:
                dedup_sql = (
                    "SELECT * EXCLUDE(row_num) FROM ("
                    f"  SELECT *, ROW_NUMBER() OVER (PARTITION BY {pk} ORDER BY {order_by} DESC) AS row_num"
                    "  FROM _tbl"
                    ") WHERE row_num = 1"
                )

            cursor = con.execute(dedup_sql)
            col_names = [desc[0] for desc in cursor.description]
            return [dict(zip(col_names, row)) for row in cursor.fetchall()]

    def query(
        self,
        table: str,
        sql: str,
        *,
        params: tuple[Any, ...] = (),
        snapshot_id: int | None = None,
    ) -> list[dict] | None:
        """Execute *sql* against the current-state Arrow table for *table*.

        Builds the current-state view internally (same SCD2/correlated-subquery
        logic as current_state) then runs *sql* on top of it. Use ``{tbl}`` in
        *sql* as the table reference and ``?`` for bound params.

        Returns None on any exception so callers can degrade gracefully.

        This method exposes the engine directly as a pre-Lambda bridge.
        Engine-hiding is restored when T0.7c/T0.8 verbs land (CD.8).
        """
        import duckdb  # noqa: PLC0415

        try:
            arrow_table = self._load_arrow(table, snapshot_id=snapshot_id)

            if arrow_table.num_rows == 0:
                return []

            with duckdb.connect() as con:
                con.register("_tbl", arrow_table)

                if table in _CORRELATED_SUBQUERY_TABLES:
                    current_sql = (
                        "SELECT * FROM _tbl "
                        "WHERE queue_run_id = ("
                        "  SELECT queue_run_id FROM _tbl "
                        "  ORDER BY last_updated_timestamp DESC LIMIT 1"
                        ")"
                    )
                else:
                    pk = _TABLE_PARTITION_KEYS.get(table, "id")
                    current_sql = (
                        "SELECT * EXCLUDE(row_num) FROM ("
                        f"  SELECT *, ROW_NUMBER() OVER (PARTITION BY {pk} ORDER BY last_updated_timestamp DESC) AS row_num"
                        "  FROM _tbl"
                        ") WHERE row_num = 1"
                    )

                con.execute(f"CREATE TEMP VIEW _current AS {current_sql}")
                final_sql = sql.replace("{tbl}", "_current")
                cursor = con.execute(final_sql, list(params))
                col_names = [desc[0] for desc in cursor.description]
                return [dict(zip(col_names, row)) for row in cursor.fetchall()]

        except Exception as exc:  # noqa: BLE001
            logger.warning("DuckDBIcebergReader.query: %s: %s", table, exc)
            return None


class DuckLakeReader:
    """DuckLake closed-boundary read layer (T2.19 / Decision 81): reads transit ducklake_reader.

    Satisfies the Reader protocol over the AWS_IAM Function URL (SigV4-signed). `current_state`
    returns the `current` write-through projection (the SCD2 latest-per-merge-key is materialised in
    DuckLake itself, so there is no client-side ROW_NUMBER dedup). There is no Athena escape hatch:
    a reader failure raises (the portal's closed-boundary callers surface it; sync_ops/preflight
    catch to degrade gracefully, same as the Iceberg reader).
    """

    def __init__(self, profile: str | None = None, region: str = _DEFAULT_REGION) -> None:
        self._profile = profile
        self._region = region

    def _reader_url(self) -> str:
        """Resolve the ducklake_reader Function URL.

        Resolution order (Decision 79 SSOT):
          1. env DUCKLAKE_READER_URL -- CI / explicit override
          2. SSM /agent-platform/ducklake/reader_url -- CC-web (no terraform binary)
          3. terraform output ducklake_reader_function_url -- local dev with initialized checkout
          4. lambda:GetFunctionUrlConfig -- last resort (CI runner, github_ci OIDC role)

        Loud-fail if all four are unavailable.
        """
        url = os.environ.get(_DUCKLAKE_READER_URL_ENV)
        if url:
            return url.rstrip("/")
        ssm_url = _resolve_function_url_via_ssm(_DUCKLAKE_READER_SSM_PATH, profile=self._profile, region=self._region)
        if ssm_url:
            return ssm_url
        import subprocess  # noqa: PLC0415

        try:
            proc = subprocess.run(
                ["terraform", "-chdir=terraform/personal", "output", "-raw", "ducklake_reader_function_url"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if proc.returncode == 0 and proc.stdout.strip():
                return proc.stdout.strip().rstrip("/")
        except FileNotFoundError:
            pass
        api_url = _resolve_function_url_via_api(_DUCKLAKE_READER_FUNCTION_NAME, profile=self._profile, region=self._region)
        if api_url:
            return api_url.rstrip("/")
        raise RuntimeError(
            f"{_DUCKLAKE_READER_URL_ENV} not set, SSM {_DUCKLAKE_READER_SSM_PATH!r} unavailable, "
            "terraform output 'ducklake_reader_function_url' unavailable, and "
            "lambda:GetFunctionUrlConfig fallback failed -- cannot reach the DuckLake reader "
            "(Decision 84: DuckLake is the sole ops backend)."
        )

    def _invoke(self, payload: dict[str, Any]) -> dict[str, Any]:
        """SigV4-POST *payload* to the reader Function URL; return the parsed JSON body. Loud-fail on non-200."""
        import boto3  # noqa: PLC0415
        import requests  # noqa: PLC0415
        from botocore.auth import SigV4Auth  # noqa: PLC0415
        from botocore.awsrequest import AWSRequest  # noqa: PLC0415

        from scripts.aws_profile import resolve_aws_profile  # noqa: PLC0415

        url = self._reader_url()
        body = json.dumps(payload)
        session = boto3.Session(profile_name=resolve_aws_profile(self._profile, default="agent_platform"))
        creds = session.get_credentials().get_frozen_credentials()

        last_status: int | None = None
        last_text = ""
        for attempt in range(_READER_MAX_ATTEMPTS):
            # Re-sign per attempt: SigV4 carries a timestamp, so a fresh request avoids skew on retry.
            aws_req = AWSRequest(method="POST", url=url, data=body, headers={"Content-Type": "application/json"})
            SigV4Auth(creds, "lambda", self._region).add_auth(aws_req)
            resp = requests.post(url, data=body, headers=dict(aws_req.headers), timeout=180)
            if resp.status_code == 200:
                return resp.json()
            last_status, last_text = resp.status_code, resp.text[:300]
            if resp.status_code in _READER_TRANSIENT_STATUS and attempt < _READER_MAX_ATTEMPTS - 1:
                # Cold-resume: give Neon time to wake, then re-invoke (reads are idempotent).
                logger.warning(
                    "ducklake_reader %r HTTP %d (attempt %d/%d) -- retrying after cold-resume backoff",
                    payload.get("action"),
                    resp.status_code,
                    attempt + 1,
                    _READER_MAX_ATTEMPTS,
                )
                time.sleep(_READER_RETRY_BACKOFF_S[attempt])
                continue
            break
        raise RuntimeError(f"ducklake_reader {payload.get('action')!r} failed (HTTP {last_status}): {last_text}")

    def current_state(
        self,
        table: str,
        *,
        partition_by: str = "id",
        order_by: str = _ORDER_BY_DEFAULT,
        row_filter: str | None = None,
        selected_fields: tuple[str, ...] | None = None,
        snapshot_id: int | None = None,
    ) -> list[dict]:
        """Return current-projection rows for *table*. `row_filter` pushes a WHERE down to the reader.

        partition_by/order_by/selected_fields/snapshot_id are part of the Reader protocol but are
        no-ops here: DuckLake materialises the current projection, so no client-side dedup or
        snapshot pinning is applied.
        """
        if row_filter is None:
            body = self._invoke({"action": "read_ops_current", "table": table})
            return list(body.get("rows", []))
        # Parameterize the single-key equality form (`<col> = '<value>'`) into the structural
        # {column, value} filter (rec-2170: the column travels with the value, and the reader
        # validates it against the table contract). Never interpolated into SQL.
        parsed = _parse_single_key_filter(row_filter)
        if parsed is None:
            raise ValueError(
                f"DuckLakeReader.current_state: row_filter must be a single-key equality "
                f"(\"<col> = '<value>'\"); got {row_filter!r}. Use named() for pre-established reads."
            )
        column, value = parsed
        body = self._invoke({"action": "read_ops_current", "table": table, "filter": {"column": column, "value": value}})
        return list(body.get("rows", []))

    def latest_snapshot(self, table: str) -> int | None:
        """DuckLake current is a live projection (no Iceberg snapshot id). Returns None by contract."""
        return None

    def named(self, verb: str, **params: Any) -> list[dict]:
        """Execute a pre-established read verb on the reader (Decision 84 I-3).

        The SQL lives server-side in the reader's registry; the caller names the verb and binds
        params. Loud-fail on an unknown verb, a param mismatch, or an unreachable reader -- a
        failure is never a silent empty result (Decision 55).
        """
        body = self._invoke({"action": "named_read", "verb": verb, "params": params})
        return list(body.get("rows", []))

    def query(
        self,
        table: str,
        sql: str,
        *,
        params: tuple[Any, ...] = (),
        snapshot_id: int | None = None,
    ) -> list[dict] | None:
        """Execute *sql* (using `{tbl}`) over the current projection via the reader. None on error."""
        try:
            body = self._invoke({"action": "query_ops", "table": table, "sql": sql, "params": list(params)})
            return list(body.get("rows", []))
        except Exception as exc:  # noqa: BLE001
            logger.warning("DuckLakeReader.query: %s: %s", table, exc)
            return None


def make_reader(profile: str | None = None, table: str | None = None) -> Reader:
    """Return the operational Reader: DuckLakeReader for every ops table (Decision 84 I-1).

    The *table* parameter is retained for call-site compatibility; all ops_* tables transit the
    closed DuckLake boundary. DuckDBIcebergReader is no longer reachable from here -- it survives
    as an importable class for non-ops Iceberg surfaces until the estate demolition lands.
    """
    return DuckLakeReader(profile=profile)
