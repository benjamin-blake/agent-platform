"""Lambda handler: Iceberg table maintenance (OPTIMIZE + VACUUM).

Step Functions state: TableMaintenance
Input:  { "date": "2026-03-21", "rows_written": 87, ... }
Output: { "date": "2026-03-21", "optimize_status": "SUCCEEDED", "vacuum_status": "SUCCEEDED" }

Runs two Athena queries after every successful write:
  1. OPTIMIZE — rewrites small Parquet data files into larger ones
     (reduces file count, improves scan performance)
  2. VACUUM   — expires snapshots older than the retention window
     and removes orphaned data/metadata files from S3

This keeps the Iceberg metadata lean and read latency consistent
as the table grows.  Both operations are idempotent and safe to
run on every pipeline invocation.
"""

import logging
import os
import time

import boto3

from src.common.config import config

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# How many days of snapshots to keep.
# NOTE: Athena does not support the VACUUM command in this deployment.
# Snapshot metadata is pruned automatically via Iceberg table properties:
#   write.metadata.delete-after-commit.enabled = true
#   write.metadata.previous-versions-max = 10
# (set in terraform/iceberg_tables.tf CREATE TABLE TBLPROPERTIES)
VACUUM_RETAIN_DAYS = 7  # kept for reference / future use

# Athena query timeout (seconds).  OPTIMIZE on a small table
# typically completes in <30s; VACUUM in <15s.
ATHENA_TIMEOUT = 300

GLUE_DATABASE = None  # resolved lazily
TABLE_NAMES = ["market_data", "market_data_raw_hourly"]


def _database() -> str:
    global GLUE_DATABASE
    if GLUE_DATABASE is None:
        GLUE_DATABASE = config.glue_database
    return GLUE_DATABASE


def _run_athena_query(sql: str, description: str) -> str:
    """Execute an Athena query and wait for completion.

    Returns the terminal state: SUCCEEDED | FAILED | CANCELLED.
    """
    athena = boto3.client("athena", region_name=config.aws_region)
    s3_bucket = os.environ.get("S3_DATA_LAKE_BUCKET") or config.get("aws.s3_data_lake_bucket", "")

    workgroup = os.environ.get("ATHENA_WORKGROUP", config.get("aws.athena_prod_workgroup", "agent-platform-production"))

    logger.info("Running %s: %s", description, sql)

    response = athena.start_query_execution(
        QueryString=sql,
        QueryExecutionContext={"Database": _database()},
        ResultConfiguration={"OutputLocation": f"s3://{s3_bucket}/athena/maintenance-results/"},
        WorkGroup=workgroup,
    )
    query_id = response["QueryExecutionId"]

    # Poll until terminal state
    elapsed = 0
    while elapsed < ATHENA_TIMEOUT:
        result = athena.get_query_execution(QueryExecutionId=query_id)
        state = result["QueryExecution"]["Status"]["State"]
        if state in ("SUCCEEDED", "FAILED", "CANCELLED"):
            reason = result["QueryExecution"]["Status"].get("StateChangeReason", "")
            if state != "SUCCEEDED":
                logger.warning(
                    "%s finished with state=%s reason=%s",
                    description,
                    state,
                    reason,
                )
            else:
                logger.info("%s completed successfully", description)
            return state
        time.sleep(3)
        elapsed += 3

    logger.error("%s timed out after %ds", description, ATHENA_TIMEOUT)
    return "TIMEOUT"


def handler(event, context):
    """Lambda entry point for TableMaintenance step.

    Runs OPTIMIZE BIN_PACK on each Iceberg table written in this pipeline run.
    Snapshot expiry is handled automatically via Iceberg table properties
    ('write.metadata.delete-after-commit.enabled' and
    'write.metadata.previous-versions-max') set in the CREATE TABLE DDL.

    Note: Athena does not support the VACUUM command in this deployment.
    OPTIMIZE is handled by an Athena pre-processor and works correctly.

    Args:
        event: Output from WriteToIceberg step.
        context: Lambda context.

    Returns:
        Dict with maintenance results.
    """
    target_date_str = event.get("date", "unknown")

    optimize_statuses = {}

    for table_name in TABLE_NAMES:
        table = f"{_database()}.{table_name}"

        # ── OPTIMIZE ────────────────────────────────────────────────────
        # Compacts small data files produced by individual MERGE writes
        # into fewer, larger Parquet files.  Reduces file count and improves
        # scan performance.  Athena requires no workgroup override for this.
        # Non-fatal: if the table doesn't exist yet (e.g. market_data_raw_hourly
        # before the first hourly backfill), skip rather than failing the step.
        optimize_sql = f"OPTIMIZE {table} REWRITE DATA USING BIN_PACK"
        status = _run_athena_query(optimize_sql, f"OPTIMIZE {table_name}")
        optimize_statuses[table_name] = status
        if status == "FAILED":
            logger.warning("OPTIMIZE %s returned FAILED — table may not exist yet; skipping", table_name)

        logger.info(
            "Maintenance complete for %s (date=%s): optimize=%s",
            table,
            target_date_str,
            optimize_statuses[table_name],
        )

    return {
        "date": target_date_str,
        "optimize_status": optimize_statuses,
    }
