"""One-shot schema migration: flatten features map to native columns.

Run this script once against the existing market_data Iceberg table to:

  1. Add the new native feature columns via Iceberg schema evolution (the
     first awswrangler write with schema_evolution=True also does this, but
     running it here explicitly makes the migration auditable and re-runnable).

  2. Backfill the existing rows — copy values from the features map
     into the new native columns using Athena UPDATE statements.
     Delta / z-score columns (delta_*, zscore_*) are NOT backfilled here
     because they require a contiguous time-series to compute correctly;
     they will be populated by the daily pipeline once enough history exists,
     and by the Phase 1.5 backfill job.

Usage (company VM, SSO profile):
    aws sso login --profile company-aws-profile
    python -m scripts.migrate_schema

The script reads database / workgroup / bucket from config.company.yaml.
"""

import argparse
import logging
import os
import sys
import time

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration (loaded before heavy imports so errors surface quickly)
# ---------------------------------------------------------------------------

# Allow running from the repo root without installing the package.
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.common.config import config  # noqa: E402

DATABASE = config.get("aws.glue_database", "trading_formulas_db")
WORKGROUP = config.get("aws.athena_prod_workgroup", "agent-platform-production")
S3_BUCKET = config.get("aws.s3_data_lake_bucket", "bblake-platform-data-lake")
AWS_PROFILE = config.get("aws.profile", "company-aws-profile")
S3_OUTPUT = f"s3://{S3_BUCKET}/athena/query-results/"

# Map: new native column → key in the features map (they match, so this is 1:1)
FEATURE_COLUMNS = [
    "tech_rsi_14",
    "tech_macd",
    "tech_macd_signal",
    "tech_macd_histogram",
    "tech_bb_width",
    "tech_atr_14",
    "tech_sma_20",
    "tech_sma_50",
    "tech_sma_200",
    "tech_ema_12",
    "tech_ema_26",
    "tech_volume_ratio",
    "tech_momentum_5d",
    "tech_momentum_10d",
    "tech_momentum_20d",
    "tech_volatility_20d",
    "sentiment_fear_greed",
    "fundamental_pe",
    "fundamental_market_cap",
    "fundamental_div_yield",
]

# Columns derived from timestamp or stable values — string type, added separately
DERIVED_STRING_COLUMNS = [
    "interval",  # string: data granularity — backfill existing rows with '1d'
]

# Delta columns — kept separate; NOT backfilled from map (computed from time series)
DELTA_COLUMNS = [
    "delta_price_1d",
    "delta_price_5d",
    "delta_price_20d",
    "delta_volatility_10d",
    "zscore_close_30d",
    "zscore_volume_30d",
    "zscore_rsi_30d",
    "delta_sentiment_1d",
]


def run_athena_query(wr, sql: str, desc: str, ignore_already_exists: bool = False) -> bool:
    """Execute an Athena DDL/DML query and wait for completion.

    Args:
        wr: awswrangler module.
        sql: SQL to execute.
        desc: Human-readable description for logging.
        ignore_already_exists: If True, treat "name already exists" failures as
                               a success (idempotent re-run support).

    Returns:
        True if the query succeeded (or was ignored), False if ignored.
    """
    logger.info("Running: %s", desc)
    logger.debug("SQL:\n%s", sql)
    query_id = wr.athena.start_query_execution(
        sql=sql,
        database=DATABASE,
        s3_output=S3_OUTPUT,
        workgroup=WORKGROUP,
    )
    # Poll until the query completes
    while True:
        status = wr.athena.get_query_execution(query_execution_id=query_id)
        state = status["Status"]["State"]
        if state == "SUCCEEDED":
            logger.info("  ✓ %s", desc)
            return True
        if state in ("FAILED", "CANCELLED"):
            reason = status["Status"].get("StateChangeReason", "unknown")
            if ignore_already_exists and "already exists" in reason.lower():
                logger.info("  ~ %s (already exists — skipping)", desc)
                return False
            raise RuntimeError(f"Athena query failed ({state}): {reason}\nSQL: {sql}")
        time.sleep(2)


def main() -> None:
    os.environ["AWS_PROFILE"] = AWS_PROFILE

    import awswrangler as wr  # noqa: PLC0415  (late import — needs AWS_PROFILE set)

    logger.info("Migration target: %s.market_data (workgroup=%s)", DATABASE, WORKGROUP)

    all_new_columns = FEATURE_COLUMNS + DELTA_COLUMNS

    # ------------------------------------------------------------------
    # Step 1: Add new columns one at a time (idempotent — skips if exists).
    # Athena Iceberg does not support ADD COLUMN IF NOT EXISTS, so we issue
    # one statement per column and ignore "already exists" failures.
    # ------------------------------------------------------------------
    logger.info("Adding %d new columns (idempotent) ...", len(all_new_columns))
    for col in all_new_columns:
        col_sql = f"ALTER TABLE {DATABASE}.market_data ADD COLUMNS ({col} double)"
        run_athena_query(wr, col_sql, f"ADD COLUMN {col}", ignore_already_exists=True)

    # Add string-typed derived columns separately (not double)
    for col in DERIVED_STRING_COLUMNS:
        col_sql = f"ALTER TABLE {DATABASE}.market_data ADD COLUMNS ({col} string)"
        run_athena_query(wr, col_sql, f"ADD COLUMN {col}", ignore_already_exists=True)

    # ------------------------------------------------------------------
    # Step 2: Backfill feature columns from the features map.
    # One UPDATE per column — Athena Iceberg UPDATE is copy-on-write so
    # each statement touches only partitions with NULL values.
    # The WHERE clause limits rewrites to rows that haven't been migrated.
    # ------------------------------------------------------------------
    logger.info("Backfilling %d feature columns from features map ...", len(FEATURE_COLUMNS))
    for col in FEATURE_COLUMNS:
        update_sql = f"""
UPDATE {DATABASE}.market_data
SET {col} = try(element_at(features, '{col}'))
WHERE {col} IS NULL
  AND cardinality(features) > 0
"""
        run_athena_query(wr, update_sql.strip(), f"Backfill {col}")

    # ------------------------------------------------------------------
    # Step 3: Verify — count rows with at least one populated feature column.
    # ------------------------------------------------------------------
    logger.info("Verifying migration ...")
    result = wr.athena.read_sql_query(
        sql=f"""
            SELECT
                COUNT(*) AS total_rows,
                COUNT(tech_rsi_14) AS rows_with_rsi,
                COUNT(sentiment_fear_greed) AS rows_with_sentiment,
                COUNT(fundamental_market_cap) AS rows_with_fundamentals
            FROM {DATABASE}.market_data
        """,
        database=DATABASE,
        workgroup=WORKGROUP,
        s3_output=S3_OUTPUT,
    )
    logger.info("Verification results:\n%s", result.to_string(index=False))

    # ------------------------------------------------------------------
    # Step 3b: Backfill interval column.
    # All existing rows are daily bars, so set interval = '1d' universally.
    # ------------------------------------------------------------------
    logger.info("Backfilling interval column for existing rows ...")
    run_athena_query(
        wr,
        f"UPDATE {DATABASE}.market_data SET interval = '1d' WHERE interval IS NULL",
        "Backfill interval",
    )

    # ------------------------------------------------------------------
    # Step 4: Apply Iceberg table properties for automatic metadata cleanup.
    # These cannot be set via CREATE TABLE IF NOT EXISTS on an existing table;
    # they must be applied via ALTER TABLE SET TBLPROPERTIES.
    # - delete-after-commit: deletes old metadata JSON files after each commit
    # - previous-versions-max: caps the number of retained metadata versions
    # Together these replace the need for periodic VACUUM (which requires
    # Athena engine v3 and is therefore excluded from the pipeline).
    # ------------------------------------------------------------------
    logger.info("Applying Iceberg table properties for metadata cleanup ...")
    run_athena_query(
        wr,
        f"""
        ALTER TABLE {DATABASE}.market_data
        SET TBLPROPERTIES (
            'write.metadata.delete-after-commit.enabled'='true',
            'write.metadata.previous-versions-max'='10'
        )
        """.strip(),
        "SET TBLPROPERTIES market_data",
    )

    logger.info(
        "Migration complete. Delta columns (%s) will be populated by the "
        "daily pipeline once sufficient history exists (or by the Phase 1.5 "
        "backfill job).",
        ", ".join(DELTA_COLUMNS),
    )


# ---------------------------------------------------------------------------
# Ops timestamp migration (Decision 56)
# Repartitions all 5 ops tables from trade_date to day(last_updated_timestamp)
# and renames ingested_at -> last_updated_timestamp + created_timestamp.
# ---------------------------------------------------------------------------

_OPS_TABLES_MIGRATION: dict[str, dict] = {
    "ops_recommendations": {
        # Remove: date, trade_date; add: ingested_at AS created_timestamp + last_updated_timestamp
        "select_cols": (
            "id, title, source, effort, priority, status, automatable, risk, file, context, "
            "acceptance, dependencies, tags, resolution, execution_result, execution_date, "
            "execution_branch, execution_pr_url, execution_steps"
        ),
        "timestamp_select": "ingested_at AS created_timestamp, ingested_at AS last_updated_timestamp",
    },
    "ops_session_log": {
        # Remove: date, trade_date; add: ingested_at AS created_timestamp + last_updated_timestamp
        "select_cols": ("session_id, branch, session_type, recs_attempted, recs_closed, summary, duration_minutes"),
        "timestamp_select": "ingested_at AS created_timestamp, ingested_at AS last_updated_timestamp",
    },
    "ops_decisions": {
        # Remove: date (legacy string), id (legacy string), keywords, trade_date
        # Rename: ingested_at -> last_updated_timestamp + created_timestamp
        "select_cols": ("decision_id, title, status, problem, decision_text, context, decided_date, related_decisions"),
        "timestamp_select": "ingested_at AS created_timestamp, ingested_at AS last_updated_timestamp",
    },
    "ops_execution_plans": {
        # Remove: trade_date; rename: ingested_at -> last_updated_timestamp + created_timestamp
        "select_cols": (
            "plan_id, rec_id, branch, plan_type, verification_tier, steps_json, scope_json, model_used, critique_result"
        ),
        "timestamp_select": "ingested_at AS created_timestamp, ingested_at AS last_updated_timestamp",
    },
    "ops_priority_queue": {
        # Remove: trade_date; rename: ingested_at -> last_updated_timestamp + created_timestamp
        "select_cols": (
            "queue_run_id, rank, rec_id, mode, compound_with, rationale, gates, north_star_impact, decay_date, status"
        ),
        "timestamp_select": "ingested_at AS created_timestamp, ingested_at AS last_updated_timestamp",
    },
}

_OPS_TABLE_SCHEMAS: dict[str, str] = {
    "ops_recommendations": (
        "id string, title string, source string, effort string, priority string, "
        "status string, automatable boolean, risk string, file string, context string, "
        "acceptance string, dependencies array<string>, tags array<string>, "
        "resolution string, execution_result string, execution_date string, "
        "execution_branch string, execution_pr_url string, execution_steps int, "
        "created_timestamp timestamp, last_updated_timestamp timestamp"
    ),
    "ops_session_log": (
        "session_id string, branch string, session_type string, "
        "recs_attempted array<string>, recs_closed array<string>, "
        "summary string, duration_minutes int, "
        "created_timestamp timestamp, last_updated_timestamp timestamp"
    ),
    "ops_decisions": (
        "decision_id int, title string, status string, problem string, "
        "decision_text string, context string, decided_date string, "
        "related_decisions array<int>, "
        "created_timestamp timestamp, last_updated_timestamp timestamp"
    ),
    "ops_execution_plans": (
        "plan_id string, rec_id string, branch string, plan_type string, "
        "verification_tier string, steps_json string, scope_json string, "
        "model_used string, critique_result string, "
        "created_timestamp timestamp, last_updated_timestamp timestamp"
    ),
    "ops_priority_queue": (
        "queue_run_id string, rank int, rec_id string, mode string, "
        "compound_with array<string>, rationale string, gates array<string>, "
        "north_star_impact string, decay_date string, status string, "
        "created_timestamp timestamp, last_updated_timestamp timestamp"
    ),
}

_OPS_AGENT_LOGS_BUCKET = "bblake-platform-agent-logs"


def migrate_ops_timestamps(profile: str | None = None) -> None:
    """Migrate all 5 ops tables from trade_date partition to day(last_updated_timestamp).

    Performs the 5-step repartition dance for each table:
    (a) CTAS to {table}_tmp with remapped columns
    (b) DROP original table
    (c) CREATE with new schema + PARTITIONED BY (day(last_updated_timestamp))
    (d) INSERT INTO {table} SELECT ... FROM {table}_tmp
    (e) DROP {table}_tmp

    Requires Athena engine v3 (workgroup: agent-platform-production).
    """
    global WORKGROUP, S3_OUTPUT  # noqa: PLW0603
    if profile:
        os.environ["AWS_PROFILE"] = profile

    import awswrangler as wr  # noqa: PLC0415  (late import -- needs AWS_PROFILE set)

    # Override module-level constants: ops tables use the production workgroup
    # and agent-logs bucket, not the market_data config values.
    WORKGROUP = "agent-platform-production"
    S3_OUTPUT = f"s3://{_OPS_AGENT_LOGS_BUCKET}/athena-results/"

    logger.info("Starting ops timestamp migration (Decision 56) -- database=%s", DATABASE)

    for table, mapping in _OPS_TABLES_MIGRATION.items():
        tmp_table = f"{table}_tmp"
        logger.info("--- Migrating %s ---", table)

        select_cols = mapping["select_cols"]
        timestamp_select = mapping["timestamp_select"]
        location = f"s3://{_OPS_AGENT_LOGS_BUCKET}/iceberg/{table}/"
        tmp_location = f"s3://{_OPS_AGENT_LOGS_BUCKET}/iceberg/{tmp_table}/"
        schema_ddl = _OPS_TABLE_SCHEMAS[table]
        # Build explicit column list for INSERT (excluding AS aliases)
        dest_col_list = ", ".join(
            c.strip() for c in (select_cols.split(",") + ["created_timestamp", "last_updated_timestamp"])
        )

        # (a) CTAS to tmp
        ctas_sql = f"""
CREATE TABLE {DATABASE}.{tmp_table}
WITH (
  location = '{tmp_location}',
  table_type = 'ICEBERG',
  format = 'PARQUET',
  is_external = false
) AS
SELECT {select_cols}, {timestamp_select}
FROM {DATABASE}.{table}
""".strip()
        run_athena_query(wr, ctas_sql, f"CTAS {tmp_table}")

        # (b) DROP original
        run_athena_query(wr, f"DROP TABLE {DATABASE}.{table}", f"DROP {table}")

        # (c) CREATE with new schema
        create_sql = f"""
CREATE TABLE {DATABASE}.{table} (
  {schema_ddl}
)
PARTITIONED BY (day(last_updated_timestamp))
LOCATION '{location}'
TBLPROPERTIES (
  'table_type'='ICEBERG',
  'format'='parquet',
  'write_compression'='gzip'
)
""".strip()
        run_athena_query(wr, create_sql, f"CREATE {table} (new schema)")

        # (d) INSERT INTO {table} SELECT ... FROM {table}_tmp
        # Note: tmp table already has columns named created_timestamp/last_updated_timestamp
        # (from the CTAS aliases), so we select them directly without re-aliasing.
        insert_sql = f"""
INSERT INTO {DATABASE}.{table} ({dest_col_list})
SELECT {dest_col_list}
FROM {DATABASE}.{tmp_table}
""".strip()
        run_athena_query(wr, insert_sql, f"INSERT into {table} from {tmp_table}")

        # (e) DROP tmp
        run_athena_query(wr, f"DROP TABLE {DATABASE}.{tmp_table}", f"DROP {tmp_table}")

        logger.info("Completed migration for %s", table)

    logger.info("All ops tables migrated successfully.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Schema migration utilities")
    parser.add_argument(
        "--migrate-ops-timestamps",
        action="store_true",
        help="Migrate all 5 ops tables to created_timestamp/last_updated_timestamp schema (Decision 56)",
    )
    parser.add_argument(
        "--profile",
        default=None,
        help="AWS SSO profile to use (e.g. company-aws-profile)",
    )
    args = parser.parse_args()

    if args.migrate_ops_timestamps:
        migrate_ops_timestamps(profile=args.profile)
    else:
        main()
