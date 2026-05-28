# complexity-waiver: decision-43
"""OpsWriter -- best-effort write gateway for operational Iceberg tables.

Stages entries to S3 as JSONL batches, then compacts them into Iceberg via
awswrangler.athena.to_iceberg at session close (session_postflight.compact_all).

Follows the same PYTEST_CURRENT_TEST guard and graceful-degradation contract as
scripts/s3_log_store.py. Never raises exceptions to callers.

See docs/contracts/ops-data-store.md for table schemas and S3 prefix layout.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import re
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from scripts.aws_profile import resolve_aws_profile

ROOT = Path(__file__).resolve().parent.parent

try:
    import boto3 as _boto3

    _BOTO3_AVAILABLE = True
except ImportError:  # pragma: no cover
    _boto3 = None  # type: ignore[assignment]
    _BOTO3_AVAILABLE = False

try:
    import awswrangler as wr

    _AWR_AVAILABLE = True
except ImportError:  # pragma: no cover
    wr = None  # type: ignore[assignment]
    _AWR_AVAILABLE = False

if TYPE_CHECKING:
    import pandas  # noqa: F401

logger = logging.getLogger(__name__)

try:
    from scripts.telemetry_schemas import (  # noqa: F401
        TELEMETRY_TABLE_DTYPES as _TELEMETRY_TABLE_DTYPES,
    )
    from scripts.telemetry_schemas import (
        TELEMETRY_TABLE_NAMES as _TELEMETRY_TABLE_NAMES,
    )
    from scripts.telemetry_schemas import (
        TELEMETRY_TABLE_TIMESTAMP_COLS as _TELEMETRY_TIMESTAMP_COLS,
    )
    from scripts.telemetry_schemas import (
        validate_record as _validate_record,
    )

    _TELEMETRY_SCHEMAS_AVAILABLE = True
except ImportError:  # pragma: no cover
    _TELEMETRY_TABLE_DTYPES = {}  # type: ignore[assignment]
    _TELEMETRY_TABLE_NAMES = []  # type: ignore[assignment]
    _TELEMETRY_TIMESTAMP_COLS: dict[str, list[str]] = {}

    def _validate_record(table: str, record: dict) -> dict:  # type: ignore[misc]
        return record

    _TELEMETRY_SCHEMAS_AVAILABLE = False

# Recognised table names (ops data store) -- see docs/contracts/ops-data-store.md
_OPS_TABLE_NAMES: list[str] = [
    "ops_recommendations",
    "ops_execution_plans",
    "ops_session_log",
    "ops_decisions",
    "ops_priority_queue",
]
TABLE_NAMES: list[str] = _OPS_TABLE_NAMES + _TELEMETRY_TABLE_NAMES

STAGING_PREFIX = "staging"
DATABASE = "agent_platform"
ATHENA_WORKGROUP = "agent-platform-production"
_BUCKET_ENV_VAR = "S3_LOG_BUCKET"

# Per-table explicit Athena dtype overrides for columns whose type cannot be
# inferred from null values alone (array<string>, array<int>, specific int sizes).
# awswrangler fill_missing_columns_in_df=True (the default) re-adds every column
# in the Iceberg table schema that is absent from the staged DataFrame, filling
# it with null object dtype.  awswrangler cannot infer Athena types for null
# object columns when the target type is an array<> variant -- these overrides
# supply the schema explicitly so compaction succeeds even for all-null batches.
_OPS_TABLE_DTYPES: dict[str, dict[str, str]] = {
    "ops_recommendations": {
        "dependencies": "array<string>",
        "tags": "array<string>",
    },
    "ops_execution_plans": {},
    "ops_session_log": {
        "recs_attempted": "array<string>",
        "recs_closed": "array<string>",
        "duration_minutes": "int",
    },
    "ops_decisions": {
        "decision_id": "int",
        "related_decisions": "array<int>",
        "related_decisions_v2": "array<string>",
    },
    "ops_priority_queue": {
        "rank": "int",
        "compound_with": "array<string>",
        "gates": "array<string>",
    },
}
_TABLE_DTYPES: dict[str, dict[str, str]] = {**_OPS_TABLE_DTYPES, **_TELEMETRY_TABLE_DTYPES}

_SSO_PROFILE = "agent_platform"


class OpsWriter:
    """Best-effort write gateway for operational Iceberg tables.

    Usage:
        writer = OpsWriter()
        writer.write("ops_recommendations", {"id": "rec-001", ...})

        # At session close (session_postflight.py):
        counts = writer.compact_all()
    """

    def __init__(self) -> None:
        self._client = None  # lazy-init on first S3 call

    def _get_client(self):  # type: ignore[return]
        """Lazy-init boto3 S3 client."""
        if self._client is None:
            if not _BOTO3_AVAILABLE:
                return None
            profile = resolve_aws_profile(default=_SSO_PROFILE)
            if profile:
                session = _boto3.Session(profile_name=profile)
                self._client = session.client("s3", region_name="eu-west-2")
            else:
                self._client = _boto3.client("s3", region_name="eu-west-2")
        return self._client

    def _get_boto3_session(self):
        """Return a boto3.Session using the same profile resolution as _get_client()."""
        if not _BOTO3_AVAILABLE:
            return None
        profile = resolve_aws_profile(default=_SSO_PROFILE)
        if profile:
            return _boto3.Session(profile_name=profile)
        return _boto3.Session()

    def _bucket(self) -> str:
        bucket = os.environ.get(_BUCKET_ENV_VAR, "").strip()
        if bucket:
            return bucket

        # Fallback 1: resolve from config (company VM without env var set).
        try:
            import sys

            if str(ROOT) not in sys.path:
                sys.path.insert(0, str(ROOT))
            from src.common.config import Config  # noqa: PLC0415

            resolved = Config().get("aws.s3_agent_logs_bucket", "")
            if resolved:
                return resolved
        except Exception:  # noqa: BLE001
            pass

        # Fallback 2: direct parse of config/config.personal.yaml (last resort).
        # Personal-account config is now canonical; the legacy config.company.yaml fallback
        # would resolve the OLD work bucket in any steady-state process where S3_LOG_BUCKET
        # is unset (Step 19, Finding 4).
        try:
            personal_cfg = ROOT / "config" / "config.personal.yaml"  # canonical post-migration
            if personal_cfg.exists():
                # Avoid heavy yaml import if possible, but for config it's usually okay
                import yaml  # noqa: PLC0415

                with personal_cfg.open("r", encoding="utf-8") as f:
                    cfg = yaml.safe_load(f)
                    return cfg.get("aws", {}).get("s3_agent_logs_bucket", "")
        except Exception:  # noqa: BLE001
            pass

        return ""

    def _is_test_env(self) -> bool:
        return bool(os.environ.get("PYTEST_CURRENT_TEST"))

    def _prepare_record(self, table: str, record: dict) -> dict:
        """Inject metadata and timestamps into the record."""
        now = datetime.datetime.now(datetime.timezone.utc)
        dt = datetime.date.today().isoformat()
        now_iso = now.isoformat()

        staged = dict(record)
        if table in _OPS_TABLE_NAMES:
            # Ops tables: map caller's "date" field to created_timestamp (SCD2 semantics)
            # Prioritise existing created_timestamp from record (Decision 56)
            date_val = staged.pop("date", None)
            raw_created = staged.get("created_timestamp")

            # Robustly handle empty/whitespace strings which would otherwise become NULL in Athena
            has_created = raw_created and str(raw_created).strip()
            has_date = date_val and str(date_val).strip()

            created_ts = (raw_created if has_created else None) or (date_val if has_date else None) or now_iso
            staged["created_timestamp"] = created_ts

            # Always ensure last_updated_timestamp is fresh for SCD2 ordering
            staged["last_updated_timestamp"] = now_iso
        else:
            # Telemetry tables: retain legacy ingested_at / trade_date columns unchanged
            staged.setdefault("ingested_at", now_iso)
            staged.setdefault("trade_date", dt)
        return staged

    def write(self, table: str, entry: dict) -> None:
        """Stage a single entry to S3 for later Iceberg compaction.

        Adds ingested_at and trade_date to the entry if not already present.
        No-op if S3_LOG_BUCKET is unset or PYTEST_CURRENT_TEST is set.
        Never raises -- logs warnings on failure.

        Args:
            table: One of TABLE_NAMES (e.g., "ops_recommendations").
            entry: Dict to serialise. Must be JSON-serialisable.
        """
        if table not in TABLE_NAMES:
            logger.warning("ops_writer.write: unknown table %r -- skipping (valid: %s)", table, TABLE_NAMES)
            return

        bucket = self._bucket()
        if not bucket or self._is_test_env():
            return

        if not _BOTO3_AVAILABLE:
            logger.warning("ops_writer.write: boto3 unavailable -- staging skipped for %s", table)
            return

        if table == "ops_recommendations":
            # Backstop guard: last-resort check that fires only when an S3 write is imminent.
            # The portal (ops_data_portal.file_rec/update_rec) is the primary gate; this catches
            # any bypasses that reach OpsWriter directly with hollow data.
            _REQUIRED_REC_FIELDS = ["title", "source", "effort", "priority", "file", "context", "acceptance"]
            for _req in _REQUIRED_REC_FIELDS:
                _val = entry.get(_req)
                if not _val or not str(_val).strip():
                    raise ValueError(f"ops_writer: ops_recommendations requires non-empty '{_req}' field")
            rec_id = str(entry.get("id") or "")
            if not re.match(r"^rec-\d+$", rec_id):
                logger.error("ops_writer: refusing to stage ops_recommendations record with invalid id %r", rec_id)
                return

        staged = self._prepare_record(table, entry)
        dt = datetime.date.today().isoformat()

        key = f"{STAGING_PREFIX}/{table}/dt={dt}/batch-{uuid.uuid4()}.jsonl"
        body = json.dumps(staged, ensure_ascii=False).encode("utf-8")

        try:
            client = self._get_client()
            if client is None:
                self._write_to_outbox(table, staged)
                return
            client.put_object(
                Bucket=bucket,
                Key=key,
                Body=body,
                ContentType="application/x-ndjson",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("ops_writer.write: S3 upload failed for %s/%s: %s", bucket, key, exc)
            self._write_to_outbox(table, staged)

    def _write_to_outbox(self, table: str, entry: dict) -> None:
        """Write a failed S3 entry to the local outbox for later drain."""
        try:
            outbox_dir = Path(__file__).parent.parent / "logs" / ".ops-outbox" / table
            outbox_dir.mkdir(parents=True, exist_ok=True)
            outbox_file = outbox_dir / f"{uuid.uuid4()}.jsonl"
            outbox_file.write_text(
                json.dumps(entry, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("ops_writer: outbox write failed for %s: %s", table, exc)

    def compact(self, table: str, trade_date: str | None = None) -> int:
        """Read staging files for *table* and compact them into the Iceberg table.

        Args:
            table: One of TABLE_NAMES.
            trade_date: ISO date string (YYYY-MM-DD). Defaults to today.

        Returns:
            Number of rows compacted. 0 if awswrangler unavailable or no staging files.
        """
        if table not in TABLE_NAMES:
            logger.warning("ops_writer.compact: unknown table %r -- skipping", table)
            return 0

        if not _AWR_AVAILABLE:
            logger.warning("ops_writer.compact: awswrangler unavailable -- compaction skipped for %s", table)
            return 0

        if not _BOTO3_AVAILABLE:
            logger.warning("ops_writer.compact: boto3 unavailable -- compaction skipped for %s", table)
            return 0

        bucket = self._bucket()
        if not bucket or self._is_test_env():
            return 0

        if trade_date is None:
            trade_date = datetime.date.today().isoformat()

        if table in _OPS_TABLE_NAMES:
            prefix = f"{STAGING_PREFIX}/{table}/dt={trade_date}/"
        else:
            prefix = f"{STAGING_PREFIX}/{table}/trade_date={trade_date}/"
        try:
            client = self._get_client()
            if client is None:
                return 0

            # List staging files for this date partition
            paginator = client.get_paginator("list_objects_v2")
            keys: list[str] = []
            for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
                for obj in page.get("Contents", []):
                    keys.append(obj["Key"])

            if not keys:
                return 0

            # Read all JSONL entries
            rows: list[dict] = []
            for key in keys:
                try:
                    response = client.get_object(Bucket=bucket, Key=key)
                    body = response["Body"].read().decode("utf-8")
                    for line in body.splitlines():
                        line = line.strip()
                        if line:
                            rows.append(json.loads(line))
                except Exception as exc:  # noqa: BLE001
                    logger.warning("ops_writer.compact: failed to read s3://%s/%s: %s", bucket, key, exc)

            if not rows:
                return 0

            import pandas as pd  # noqa: PLC0415  # Lambda-only dep -- import inside try

            df = pd.DataFrame(rows)

            # Coerce NaN → None in object-dtype columns.
            # JSON null values deserialise as np.nan (float) in columns that also contain
            # string values.  pyarrow rejects float NaN in string arrays with
            # "Expected bytes, got a 'float' object".  Python None is treated as NULL.
            for _col in (c for c in df.columns if df[c].dtype == object and df[c].isna().any()):
                df.loc[df[_col].isna(), _col] = None

            # Drop all-null columns: awswrangler cannot infer types for object columns
            # that contain only null values.  Iceberg will materialise them as null
            # for this batch, which is correct for append-only semantics.
            null_cols = [c for c in df.columns if df[c].isnull().all()]
            if null_cols:
                df = df.drop(columns=null_cols)

            # Drop view-only SCD2 deduplication columns if present (view artifacts must not re-enter base tables)
            for _scd2_col in ("row_num", "_rn"):
                if _scd2_col in df.columns:
                    df = df.drop(columns=[_scd2_col])

            df = df.dropna(how="all")

            # Cast float64 columns whose Iceberg contract type is int.
            # JSON deserialisation turns integer fields into float/string when any value is null/empty.
            _INT_COLUMNS = {
                "execution_steps",
                "execution_steps_total",
                "execution_steps_attempted",
                "failure_step",
                "revision",
                "files_changed",
            }
            for col in _INT_COLUMNS:
                if col in df.columns:
                    # Coerce to numeric (handles floats and string-serialized numbers/empties)
                    df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")

            # Coerce boolean columns
            _BOOL_COLUMNS = {"automatable"}
            for col in _BOOL_COLUMNS:
                if col in df.columns:
                    # Handle both actual booleans and string-serialized booleans from legacy logs
                    df[col] = df[col].astype(str).str.lower().map({"true": True, "false": False, "1": True, "0": False})

            # Coerce list columns (string-serialized lists like "[rec-123]")
            _LIST_COLUMNS = {"dependencies", "tags"}
            for col in _LIST_COLUMNS:
                if col in df.columns:
                    import ast

                    def _parse_list(v: object) -> list[str]:
                        if isinstance(v, list):
                            return v
                        if not isinstance(v, str) or not v.strip():
                            return []
                        v_strip = v.strip()
                        if v_strip.startswith("[") and v_strip.endswith("]"):
                            try:
                                val = ast.literal_eval(v_strip)
                                if isinstance(val, list):
                                    return [str(x) for x in val]
                            except Exception:  # noqa: BLE001
                                pass
                        # Fallback for comma-separated strings without brackets
                        return [x.strip() for x in v_strip.split(",") if x.strip()]

                    df[col] = df[col].apply(_parse_list)

            # Convert all known timestamp columns from ISO strings to datetime64[ns]
            # (tz-naive), and pre-fill any missing ones with NaT.  Must run AFTER the
            # null-col drop so that pre-filled NaT columns are not immediately dropped.
            # Motivation: JSON deserialisation leaves timestamps as object/string;
            # Iceberg rejects string->timestamp type changes.  Pre-filling ensures
            # awswrangler's fill_missing_columns_in_df never calls
            # df[col].astype(athena2pandas("timestamp")), which returns bare "datetime64"
            # that pandas 2.x rejects with a ValueError (requires "datetime64[ns]").
            _extra_ts = _TELEMETRY_TIMESTAMP_COLS.get(table, [])
            if table in _OPS_TABLE_NAMES:
                _ts_cols_for_table = ["created_timestamp", "last_updated_timestamp"] + _extra_ts
            else:
                _ts_cols_for_table = ["ingested_at"] + _extra_ts
            for ts_col in _ts_cols_for_table:
                if ts_col in df.columns:
                    df[ts_col] = pd.to_datetime(df[ts_col], utc=True, errors="coerce").dt.tz_convert(None)
                else:
                    df[ts_col] = pd.NaT

            if table not in _OPS_TABLE_NAMES and "trade_date" in df.columns:
                df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce").dt.date

            temp_path = f"s3://{bucket}/tmp/compact-{table}-{uuid.uuid4()}/"

            dtype_override = _TABLE_DTYPES.get(table) or None

            # Pre-fill array-typed columns that are absent from the DataFrame.
            # fill_missing_columns_in_df=True would add them as float64 NaN, then
            # awswrangler's dtype cast tries to convert float64 NaN to array<X>,
            # resulting in "Expected bytes, got a 'float' object".  Inserting None
            # (Python null) beforehand keeps them as null without triggering the cast.
            if dtype_override:
                for _acol, _atype in dtype_override.items():
                    if _atype.startswith("array<") and _acol not in df.columns:
                        df[_acol] = None

            # Detect schema evolution before write
            schema_evolved = False
            try:
                existing_cols = wr.catalog.get_table_types(database=DATABASE, table=table)
                existing_col_names = set(existing_cols.keys())
                new_cols = set(df.columns) - existing_col_names
                if new_cols:
                    schema_evolved = True
                    logger.info("ops_writer.compact: schema evolution detected for %s (new columns: %s)", table, new_cols)
            except Exception:  # noqa: BLE001
                # If table doesn't exist yet, it's not evolution but initial creation
                pass

            wr.athena.to_iceberg(
                df=df,
                database=DATABASE,
                table=table,
                temp_path=temp_path,
                workgroup=ATHENA_WORKGROUP,
                mode="append",
                schema_evolution=True,
                dtype=dtype_override,
                boto3_session=self._get_boto3_session(),
            )

            if schema_evolved:
                self._refresh_view(table)

            row_count = len(rows)

            # Delete processed staging files
            for key in keys:
                try:
                    client.delete_object(Bucket=bucket, Key=key)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("ops_writer.compact: could not delete staging file s3://%s/%s: %s", bucket, key, exc)

            return row_count

        except Exception as exc:
            raise RuntimeError(f"ops_writer.compact: infrastructure failure for {table}: {exc}") from exc

    def emit(self, table: str, record: dict) -> None:
        """Write a telemetry record through schema validation to local outbox + S3.

        Follows the same dual-write pattern as ops_data_portal: always persist
        to the local outbox (guaranteed durability), then additionally attempt
        S3 write-through when bucket is configured.

        - Validates and filters *record* against the telemetry schema.
        - Auto-injects ``ingested_at`` and ``trade_date`` via setdefault.
        - Always writes to outbox (local-first guarantee per Decision 51).
        - Additionally writes to S3 staging when S3_LOG_BUCKET is set.
        - Never raises -- catches all exceptions and logs warnings.

        Args:
            table: A telemetry table name (e.g., "telemetry_sessions").
            record: Dict to write. Unknown fields are dropped; missing required
                    fields are passed through with nulls (forward-compatibility).
        """
        try:
            if table not in TABLE_NAMES:
                logger.warning("ops_writer.emit: unknown table %r -- skipping", table)
                return
            if self._is_test_env():
                return
            cleaned = _validate_record(table, record)
            cleaned = self._prepare_record(table, cleaned)

            # Local-first: always write to outbox (matches ops_data_portal pattern)
            self._write_to_outbox(table, cleaned)

            # Write-through: additionally attempt S3 staging when configured
            bucket = self._bucket()
            if bucket and _BOTO3_AVAILABLE:
                trade_date = cleaned["trade_date"]
                key = f"{STAGING_PREFIX}/{table}/trade_date={trade_date}/batch-{uuid.uuid4()}.jsonl"
                body = json.dumps(cleaned, ensure_ascii=False).encode("utf-8")
                try:
                    client = self._get_client()
                    if client is not None:
                        client.put_object(
                            Bucket=bucket,
                            Key=key,
                            Body=body,
                            ContentType="application/x-ndjson",
                        )
                except Exception as s3_exc:  # noqa: BLE001
                    logger.warning("ops_writer.emit: S3 write-through failed for %s: %s", table, s3_exc)
        except Exception as exc:  # noqa: BLE001
            logger.warning("ops_writer.emit: unexpected error for %s: %s", table, exc)

    def _refresh_view(self, table: str) -> None:
        """Trigger CREATE OR REPLACE VIEW for the associated current-state view."""
        if not _BOTO3_AVAILABLE:
            return

        # Map tables to their current-state view SQL (from terraform/iceberg_tables.tf)
        view_sqls = {
            "ops_recommendations": f"""
                CREATE OR REPLACE VIEW {DATABASE}.ops_recommendations_current AS
                SELECT *
                FROM (
                  SELECT *,
                    ROW_NUMBER() OVER (PARTITION BY id ORDER BY last_updated_timestamp DESC) AS row_num
                  FROM {DATABASE}.ops_recommendations
                )
                WHERE row_num = 1
            """,
            "ops_decisions": f"""
                CREATE OR REPLACE VIEW {DATABASE}.ops_decisions_current AS
                SELECT *
                FROM (
                  SELECT *,
                    ROW_NUMBER() OVER (PARTITION BY id ORDER BY last_updated_timestamp DESC) AS row_num
                  FROM {DATABASE}.ops_decisions
                )
                WHERE row_num = 1
            """,
            "ops_priority_queue": f"""
                CREATE OR REPLACE VIEW {DATABASE}.ops_priority_queue_current AS
                SELECT * FROM {DATABASE}.ops_priority_queue
                WHERE queue_run_id = (
                  SELECT queue_run_id
                  FROM {DATABASE}.ops_priority_queue
                  ORDER BY last_updated_timestamp DESC
                  LIMIT 1
                )
            """,
            "telemetry_sessions": f"""
                CREATE OR REPLACE VIEW {DATABASE}.telemetry_sessions_current AS
                SELECT *
                FROM (
                  SELECT *,
                    ROW_NUMBER() OVER (PARTITION BY session_id ORDER BY ingested_at DESC) AS row_num
                  FROM {DATABASE}.telemetry_sessions
                )
                WHERE row_num = 1
            """,
            "telemetry_phases": f"""
                CREATE OR REPLACE VIEW {DATABASE}.telemetry_phases_current AS
                SELECT *
                FROM (
                  SELECT *,
                    ROW_NUMBER() OVER (PARTITION BY phase_id ORDER BY ingested_at DESC) AS row_num
                  FROM {DATABASE}.telemetry_phases
                )
                WHERE row_num = 1
            """,
            "telemetry_steps": f"""
                CREATE OR REPLACE VIEW {DATABASE}.telemetry_steps_current AS
                SELECT *
                FROM (
                  SELECT *,
                    ROW_NUMBER() OVER (PARTITION BY step_id ORDER BY ingested_at DESC) AS row_num
                  FROM {DATABASE}.telemetry_steps
                )
                WHERE row_num = 1
            """,
            "telemetry_agent_invocations": f"""
                CREATE OR REPLACE VIEW {DATABASE}.telemetry_agent_invocations_current AS
                SELECT *
                FROM (
                  SELECT *,
                    ROW_NUMBER() OVER (PARTITION BY invocation_id ORDER BY ingested_at DESC) AS row_num
                  FROM {DATABASE}.telemetry_agent_invocations
                )
                WHERE row_num = 1
            """,
        }

        sql = view_sqls.get(table)
        if not sql:
            return

        try:
            profile = resolve_aws_profile(default=_SSO_PROFILE)
            if profile:
                session = _boto3.Session(profile_name=profile)
                athena = session.client("athena", region_name="eu-west-2")
            else:
                athena = _boto3.client("athena", region_name="eu-west-2")

            athena.start_query_execution(
                QueryString=sql,
                QueryExecutionContext={"Database": DATABASE},
                WorkGroup=ATHENA_WORKGROUP,
            )
            logger.info("ops_writer: triggered view refresh for %s_current", table)
        except Exception as exc:  # noqa: BLE001
            logger.warning("ops_writer: failed to refresh view for %s: %s", table, exc)

    def compact_all(self) -> dict[str, int]:
        """Compact all ops and telemetry tables for today's date.

        Returns:
            Dict mapping table name to rows compacted.
        """
        today = datetime.date.today().isoformat()
        results: dict[str, int] = {}
        for table in TABLE_NAMES:
            results[table] = self.compact(table, today)
        return results

    def drain(self) -> dict[str, int]:
        """Attempt to upload all records in the local outbox to S3.

        Returns:
            Dict mapping table name to number of records drained.
        """
        results: dict[str, int] = {t: 0 for t in TABLE_NAMES}
        outbox_base = ROOT / "logs" / ".ops-outbox"
        if not outbox_base.exists():
            return results

        client = self._get_client()
        if client is None:
            logger.warning("ops_writer.drain: could not get S3 client (still offline?)")
            return results

        bucket = self._bucket()
        if not bucket:
            return results

        for table in TABLE_NAMES:
            table_dir = outbox_base / table
            if not table_dir.exists():
                continue

            for outbox_file in sorted(table_dir.glob("*.jsonl")):
                try:
                    entry = json.loads(outbox_file.read_text(encoding="utf-8"))
                    # Logic matches write() but preserves original timestamps from outbox
                    dt = datetime.date.today().isoformat()
                    # Telemetry tables use trade_date in path; Ops tables use dt= partition
                    if table in _OPS_TABLE_NAMES:
                        key = f"{STAGING_PREFIX}/{table}/dt={dt}/batch-drain-{uuid.uuid4()}.jsonl"
                    else:
                        trade_date = entry.get("trade_date", dt)
                        key = f"{STAGING_PREFIX}/{table}/trade_date={trade_date}/batch-drain-{uuid.uuid4()}.jsonl"

                    body = json.dumps(entry, ensure_ascii=False).encode("utf-8")

                    client.put_object(
                        Bucket=bucket,
                        Key=key,
                        Body=body,
                        ContentType="application/x-ndjson",
                    )
                    outbox_file.unlink(missing_ok=True)
                    results[table] += 1
                except Exception as exc:  # noqa: BLE001
                    logger.warning("ops_writer.drain: failed to drain %s: %s", outbox_file, exc)

        return results


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--test-bucket", action="store_true", help="Print the resolved S3 bucket and exit")
    parser.add_argument("--compact", metavar="TABLE", help="Compact a specific table")
    parser.add_argument("--compact-all", action="store_true", help="Compact all tables for today")
    parser.add_argument("--drain", action="store_true", help="Drain local outbox to S3")
    parser.add_argument("--refresh-views", action="store_true", help="Manually refresh all current-state views")
    args = parser.parse_args()

    if args.test_bucket:
        print(OpsWriter()._bucket())
    elif args.drain:
        results = OpsWriter().drain()
        for table, count in results.items():
            if count > 0:
                print(f"Drained {count} records for {table}")
    elif args.refresh_views:
        writer = OpsWriter()
        for table in TABLE_NAMES:
            writer._refresh_view(table)
        print("Triggered refresh for all views.")
    elif args.compact:
        rows = OpsWriter().compact(args.compact)
        print(f"Compacted {rows} rows for {args.compact}")
    elif args.compact_all:
        results = OpsWriter().compact_all()
        for table, rows in results.items():
            if rows > 0:
                print(f"{table}: {rows} rows")
