"""validate_telemetry -- Three-layer validation for the telemetry Iceberg tables.

Layer 1: Schema Integrity -- compare Python dataclass fields to Athena DDL.
Layer 2: Column Population Coverage -- check non-null rates for each column.
Layer 3: FK Referential Integrity -- detect orphan rows across relationships.

Usage:
    python -m scripts.validate_telemetry --dry-run       # schema-only, no Athena
    python -m scripts.validate_telemetry                 # full validation
    python -m scripts.validate_telemetry --table telemetry_sessions  # single table
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import pathlib
import sys
import time
from typing import Any

logger = logging.getLogger(__name__)

# Deferred imports for AWS -- must not fail at import time without credentials
_boto3 = None
_ATHENA_DATABASE = "trading_formulas_db"
_ATHENA_WORKGROUP = "agent-platform-production"
_ATHENA_OUTPUT = "s3://bblake-platform-data-lake/athena-results/"

# FK relationships to validate: (child_table, fk_col, parent_table, pk_col)
_FK_RELATIONSHIPS: list[tuple[str, str, str, str]] = [
    ("telemetry_phases", "session_id", "telemetry_sessions", "session_id"),
    ("telemetry_steps", "phase_id", "telemetry_phases", "phase_id"),
    ("telemetry_steps", "session_id", "telemetry_sessions", "session_id"),
    (
        "telemetry_model_calls",
        "session_id",
        "telemetry_sessions",
        "session_id",
    ),
    (
        "telemetry_transcripts",
        "session_id",
        "telemetry_sessions",
        "session_id",
    ),
    (
        "telemetry_model_calls",
        "invocation_id",
        "telemetry_agent_invocations",
        "invocation_id",
    ),
]

# Views to validate row counts
_VIEWS: list[str] = [
    "telemetry_sessions_current",
    "telemetry_phases_current",
    "telemetry_steps_current",
    "telemetry_agent_invocations_current",
    "telemetry_session_summary_30d",
    "telemetry_phase_time_distribution",
    "telemetry_event_frequency_30d",
]


def _get_boto3():
    """Lazy import boto3 to allow import without credentials."""
    global _boto3
    if _boto3 is None:
        import boto3  # noqa: F811

        _boto3 = boto3
    return _boto3


def _get_athena_client(profile: str | None = None):
    """Return an Athena client using the specified profile or default."""
    boto3 = _get_boto3()
    session = boto3.Session(profile_name=profile)
    return session.client("athena", region_name="eu-west-2")


def _run_athena_query(client: Any, sql: str, max_wait: int = 60) -> list[dict[str, str]]:
    """Execute an Athena query and return rows as list of dicts.

    Polls with exponential backoff up to max_wait seconds.
    Returns empty list on query failure (logs the error).
    """
    try:
        response = client.start_query_execution(
            QueryString=sql,
            QueryExecutionContext={"Database": _ATHENA_DATABASE},
            WorkGroup=_ATHENA_WORKGROUP,
            ResultConfiguration={"OutputLocation": _ATHENA_OUTPUT},
        )
    except Exception:
        logger.exception("Failed to start Athena query: %s", sql[:100])
        return []

    query_id = response["QueryExecutionId"]
    wait = 1.0
    elapsed = 0.0

    while elapsed < max_wait:
        time.sleep(wait)
        elapsed += wait
        try:
            status_resp = client.get_query_execution(QueryExecutionId=query_id)
        except Exception:
            logger.exception("Failed to get query status for %s", query_id)
            return []

        state = status_resp["QueryExecution"]["Status"]["State"]
        if state == "SUCCEEDED":
            break
        if state in ("FAILED", "CANCELLED"):
            reason = status_resp["QueryExecution"]["Status"].get("StateChangeReason", "unknown")
            logger.error("Athena query %s: %s -- %s", state, reason, sql[:100])
            return []
        wait = min(wait * 2, 10.0)
    else:
        logger.error("Athena query timed out after %ds: %s", max_wait, sql[:100])
        return []

    # Fetch results
    try:
        result = client.get_query_results(QueryExecutionId=query_id)
    except Exception:
        logger.exception("Failed to get query results for %s", query_id)
        return []

    rows = result["ResultSet"]["Rows"]
    if len(rows) < 2:
        return []

    headers = [col["VarCharValue"] for col in rows[0]["Data"]]
    results = []
    for row in rows[1:]:
        values = [col.get("VarCharValue", "") for col in row["Data"]]
        results.append(dict(zip(headers, values)))

    return results


# ---------------------------------------------------------------------------
# Layer 1: Schema Integrity
# ---------------------------------------------------------------------------


def check_schema_integrity(
    client: Any | None = None,
    tables: list[str] | None = None,
) -> dict[str, Any]:
    """Compare Python schema fields against Athena SHOW COLUMNS.

    If client is None (dry-run), only reports expected columns per table.
    """
    from scripts.telemetry_schemas import (
        TELEMETRY_TABLE_NAMES,
        get_all_columns,
    )

    target_tables = tables or TELEMETRY_TABLE_NAMES
    schema_drift: dict[str, Any] = {}

    for table in target_tables:
        python_cols = set(get_all_columns(table))
        entry: dict[str, Any] = {
            "python_columns": sorted(python_cols),
            "python_count": len(python_cols),
        }

        if client is not None:
            athena_cols_raw = _run_athena_query(client, f"SHOW COLUMNS IN {_ATHENA_DATABASE}.{table}")
            # SHOW COLUMNS returns rows with a single 'column' key
            athena_cols = set()
            for row in athena_cols_raw:
                # Different Athena versions return different key names
                col_name = row.get("column") or row.get("Column Name") or row.get("col_name") or next(iter(row.values()), "")
                if col_name:
                    athena_cols.add(col_name.strip().lower())

            missing_in_athena = python_cols - athena_cols
            extra_in_athena = athena_cols - python_cols

            entry["athena_columns"] = sorted(athena_cols)
            entry["athena_count"] = len(athena_cols)
            entry["missing_in_athena"] = sorted(missing_in_athena)
            entry["extra_in_athena"] = sorted(extra_in_athena)
            entry["match"] = len(missing_in_athena) == 0 and len(extra_in_athena) == 0
        else:
            entry["athena_columns"] = None
            entry["missing_in_athena"] = []
            entry["extra_in_athena"] = []
            entry["match"] = None  # Cannot determine without Athena

        schema_drift[table] = entry

    return schema_drift


# ---------------------------------------------------------------------------
# Layer 2: Column Population Coverage
# ---------------------------------------------------------------------------


def check_population_coverage(
    client: Any,
    tables: list[str] | None = None,
) -> dict[str, Any]:
    """Check non-null population rate for each column in each table."""
    from scripts.telemetry_schemas import (
        TELEMETRY_TABLE_NAMES,
        get_all_columns,
        get_required_columns,
    )

    target_tables = tables or TELEMETRY_TABLE_NAMES
    results: dict[str, Any] = {}

    for table in target_tables:
        all_cols = get_all_columns(table)
        required_cols = set(get_required_columns(table))

        # Build population query - count non-null for each column
        count_exprs = ["COUNT(*) AS total_rows"]
        for col in all_cols:
            count_exprs.append(f"SUM(CASE WHEN {col} IS NOT NULL THEN 1 ELSE 0 END) AS {col}_count")

        sql = (
            f"SELECT {', '.join(count_exprs)} "
            f"FROM {_ATHENA_DATABASE}.{table} "
            f"WHERE trade_date >= CURRENT_DATE - INTERVAL '30' DAY"
        )

        query_results = _run_athena_query(client, sql)

        table_result: dict[str, Any] = {"columns": {}}
        if not query_results:
            table_result["total_rows"] = 0
            table_result["verdict"] = "FAIL"
            for col in all_cols:
                is_required = col in required_cols
                table_result["columns"][col] = {
                    "non_null_count": 0,
                    "population_pct": 0.0,
                    "required": is_required,
                    "status": "FAIL" if is_required else "WARN",
                }
        else:
            row = query_results[0]
            total_rows = int(row.get("total_rows", "0") or "0")
            table_result["total_rows"] = total_rows

            has_failure = False
            for col in all_cols:
                non_null = int(row.get(f"{col}_count", "0") or "0")
                pct = (non_null / total_rows * 100) if total_rows > 0 else 0.0
                is_required = col in required_cols

                if total_rows == 0:
                    status = "FAIL" if is_required else "WARN"
                elif non_null == 0:
                    status = "FAIL" if is_required else "WARN"
                else:
                    status = "PASS" if is_required else "OK"

                if status == "FAIL":
                    has_failure = True

                table_result["columns"][col] = {
                    "non_null_count": non_null,
                    "population_pct": round(pct, 1),
                    "required": is_required,
                    "status": status,
                }

            table_result["verdict"] = "FAIL" if has_failure else "PASS"

        results[table] = table_result

    return results


# ---------------------------------------------------------------------------
# Layer 3: FK Referential Integrity
# ---------------------------------------------------------------------------


def check_fk_integrity(
    client: Any,
    tables: list[str] | None = None,
) -> dict[str, Any]:
    """Check FK referential integrity across telemetry tables."""
    results: dict[str, Any] = {}

    for child_table, fk_col, parent_table, pk_col in _FK_RELATIONSHIPS:
        # Skip if filtering and neither table is in the filter
        if tables and child_table not in tables and parent_table not in tables:
            continue

        relationship_key = f"{child_table}.{fk_col} -> {parent_table}.{pk_col}"

        sql = (
            f"SELECT COUNT(*) AS orphan_count "
            f"FROM {_ATHENA_DATABASE}.{child_table} c "
            f"LEFT JOIN {_ATHENA_DATABASE}.{parent_table} p "
            f"ON c.{fk_col} = p.{pk_col} "
            f"WHERE c.{fk_col} IS NOT NULL AND p.{pk_col} IS NULL "
            f"AND c.trade_date >= CURRENT_DATE - INTERVAL '30' DAY"
        )

        query_results = _run_athena_query(client, sql)
        orphan_count = 0
        if query_results:
            orphan_count = int(query_results[0].get("orphan_count", "0"))

        results[relationship_key] = {
            "child_table": child_table,
            "fk_col": fk_col,
            "parent_table": parent_table,
            "pk_col": pk_col,
            "orphan_count": orphan_count,
            "status": "WARN" if orphan_count > 0 else "PASS",
        }

    return results


def check_views(client: Any) -> dict[str, Any]:
    """Check that all telemetry views return at least 1 row."""
    results: dict[str, Any] = {}

    for view in _VIEWS:
        sql = f"SELECT COUNT(*) AS row_count FROM {_ATHENA_DATABASE}.{view}"
        query_results = _run_athena_query(client, sql)
        row_count = 0
        if query_results:
            row_count = int(query_results[0].get("row_count", "0"))

        results[view] = {
            "row_count": row_count,
            "status": "PASS" if row_count > 0 else "WARN",
        }

    return results


# ---------------------------------------------------------------------------
# Report generation and main()
# ---------------------------------------------------------------------------


def _determine_exit_code(population: dict[str, Any]) -> int:
    """Return 0 if all required columns in all tables have >0 population, else 1."""
    for table_name, table_data in population.items():
        for col_name, col_data in table_data.get("columns", {}).items():
            if col_data.get("required") and col_data.get("status") == "FAIL":
                return 1
    return 0


def _print_summary(report: dict[str, Any]) -> None:
    """Print human-readable summary table to stdout."""
    print("\n" + "=" * 80)
    print("TELEMETRY VALIDATION REPORT")
    print("=" * 80)

    # Schema drift summary
    schema = report.get("schema_drift", {})
    if schema:
        print("\n--- Schema Integrity ---")
        for table, data in schema.items():
            match_str = "MATCH" if data.get("match") is True else "DRIFT" if data.get("match") is False else "N/A"
            missing = len(data.get("missing_in_athena", []))
            extra = len(data.get("extra_in_athena", []))
            print(f"  {table}: {match_str} (python={data.get('python_count', '?')}, missing={missing}, extra={extra})")

    # Population summary
    tables = report.get("tables", {})
    if tables:
        print("\n--- Column Population (30d) ---")
        print(f"  {'Table':<40} {'Rows':>6} {'Req Pass':>9} {'Opt Pop':>8} {'Verdict':>8}")
        print("  " + "-" * 73)
        for table, data in tables.items():
            total = data.get("total_rows", 0)
            cols = data.get("columns", {})
            req_pass = sum(1 for c in cols.values() if c.get("required") and c.get("status") == "PASS")
            req_total = sum(1 for c in cols.values() if c.get("required"))
            opt_pop = sum(1 for c in cols.values() if not c.get("required") and c.get("status") == "OK")
            opt_total = sum(1 for c in cols.values() if not c.get("required"))
            verdict = data.get("verdict", "?")
            print(f"  {table:<40} {total:>6} {req_pass}/{req_total:>6} {opt_pop}/{opt_total:>5} {verdict:>8}")

    # FK integrity summary
    fk = report.get("fk_checks", {})
    if fk:
        print("\n--- FK Referential Integrity ---")
        for rel, data in fk.items():
            status = data.get("status", "?")
            orphans = data.get("orphan_count", 0)
            print(f"  {rel}: {status} (orphans={orphans})")

    # Views summary
    views = report.get("views", {})
    if views:
        print("\n--- View Row Counts ---")
        for view, data in views.items():
            status = data.get("status", "?")
            rows = data.get("row_count", 0)
            print(f"  {view}: {status} (rows={rows})")

    print("\n" + "=" * 80)


def main(argv: list[str] | None = None) -> int:
    """Entry point for telemetry validation."""
    parser = argparse.ArgumentParser(description="Validate telemetry Iceberg tables: schema, population, FK integrity.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Schema introspection only -- no Athena queries",
    )
    parser.add_argument(
        "--table",
        type=str,
        default=None,
        help="Filter to a single table name (e.g. telemetry_sessions)",
    )
    parser.add_argument(
        "--profile",
        type=str,
        default=None,
        help="AWS profile name (default: from AWS_PROFILE env var)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output JSON report path (default: logs/debug/telemetry-validation-{date}.json)",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    tables_filter = [args.table] if args.table else None

    # Determine output path
    if args.output:
        output_path = pathlib.Path(args.output)
    else:
        today = datetime.date.today().isoformat()
        output_path = pathlib.Path(f"logs/debug/telemetry-validation-{today}.json")

    report: dict[str, Any] = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "dry_run": args.dry_run,
        "table_filter": args.table,
    }

    if args.dry_run:
        # Dry-run: schema introspection only (no Athena)
        logger.info("Running in dry-run mode (schema introspection only)")
        schema_drift = check_schema_integrity(client=None, tables=tables_filter)
        report["schema_drift"] = schema_drift
        report["tables"] = {}
        report["fk_checks"] = {}
        report["views"] = {}
    else:
        # Full validation with Athena
        import os

        profile = args.profile or os.environ.get("AWS_PROFILE")
        if not profile:
            logger.error("No AWS profile specified. Use --profile or set AWS_PROFILE env var.")
            return 1

        logger.info("Connecting to Athena with profile: %s", profile)
        client = _get_athena_client(profile)

        logger.info("Layer 1: Checking schema integrity...")
        schema_drift = check_schema_integrity(client=client, tables=tables_filter)
        report["schema_drift"] = schema_drift

        logger.info("Layer 2: Checking column population coverage...")
        population = check_population_coverage(client=client, tables=tables_filter)
        report["tables"] = population

        logger.info("Layer 3: Checking FK referential integrity...")
        fk_results = check_fk_integrity(client=client, tables=tables_filter)
        report["fk_checks"] = fk_results

        logger.info("Checking view row counts...")
        view_results = check_views(client=client)
        report["views"] = view_results

    # Write report
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, default=str))
    logger.info("Report written to: %s", output_path)

    # Print summary
    _print_summary(report)

    # Determine exit code
    if args.dry_run:
        return 0

    exit_code = _determine_exit_code(report.get("tables", {}))
    if exit_code != 0:
        logger.error("VALIDATION FAILED: one or more required columns have 0%% population")
    else:
        logger.info("VALIDATION PASSED: all required columns have >0%% population")

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
