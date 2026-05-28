# complexity-waiver: decision-43
"""Data quality runner: compiles YAML check definitions to Athena SQL.

Modelled after dbt test semantics. Each check produces a SQL query that returns
VIOLATION rows. Zero violations = PASS. Any violations = FAIL (or WARN).

Usage:
    # Run all checks for all tables
    AWS_PROFILE=agent_platform python -m scripts.data_quality_runner

    # Run checks for a single table
    AWS_PROFILE=agent_platform python -m scripts.data_quality_runner --table telemetry_sessions

    # Run checks from a specific YAML file
    AWS_PROFILE=agent_platform python -m scripts.data_quality_runner --file config/agent/data_quality/telemetry.yaml

    # Dry-run: print compiled SQL without executing
    python -m scripts.data_quality_runner --dry-run

    # JSON output for programmatic consumption
    AWS_PROFILE=agent_platform python -m scripts.data_quality_runner --json
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent.parent
_DQ_DIR = _ROOT / "config" / "agent" / "data_quality"
_TOMBSTONES_PATH = _DQ_DIR / "dq_tombstones.yaml"
_POLL_INTERVAL = 2  # seconds between Athena status checks
_MAX_POLL = 60  # max seconds to wait for a single query


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class Check:
    """A single compiled data quality check."""

    table: str
    column: str | None
    test_type: str
    sql: str
    description: str
    severity: str = "error"
    enforced: bool = True
    exclude_before: str | None = None


@dataclass
class CheckResult:
    """Result of executing a single check."""

    check: Check
    verdict: str  # PASS | FAIL | WARN | ERROR | SKIP
    violation_count: int = 0
    detail: str = ""
    duration_seconds: float = 0.0


@dataclass
class RunResult:
    """Aggregate result of a full run."""

    results: list[CheckResult] = field(default_factory=list)
    verdict: str = "PASS"
    duration_seconds: float = 0.0

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.verdict == "PASS")

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if r.verdict == "FAIL")

    @property
    def unenforced_fail(self) -> int:
        return sum(1 for r in self.results if r.verdict == "UNENFORCED_FAIL")

    @property
    def warned(self) -> int:
        return sum(1 for r in self.results if r.verdict == "WARN")

    @property
    def skipped(self) -> int:
        return sum(1 for r in self.results if r.verdict == "SKIP")

    @property
    def errored(self) -> int:
        return sum(1 for r in self.results if r.verdict == "ERROR")

    @property
    def hard_gated(self) -> int:
        return sum(1 for r in self.results if r.verdict == "HARD_GATE")


# ---------------------------------------------------------------------------
# Tombstone resurrection checks
# ---------------------------------------------------------------------------


def load_tombstones(path: Path = _TOMBSTONES_PATH) -> list[dict]:
    """Load the list of hard-deleted record IDs from dq_tombstones.yaml."""
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        spec = yaml.safe_load(f)
    return spec.get("tombstones", []) if spec else []


def build_tombstone_checks(
    tombstones: list[dict],
    table_filter: str | None = None,
    database: str = "agent_platform",
) -> list[Check]:
    """Generate tombstone_resurrection Check objects from the tombstones manifest."""
    checks: list[Check] = []
    for entry in tombstones:
        table = entry.get("table", "")
        rec_id = entry.get("id", "")
        if not table or not rec_id:
            continue
        if table_filter and table != table_filter:
            continue
        view_name = f"{table}_current" if table == "ops_recommendations" else table
        query_table = f"{database}.{view_name}"
        checks.append(
            Check(
                table=table,
                column="id",
                test_type="tombstone_resurrection",
                sql=(f"SELECT COUNT(*) AS violation FROM {query_table} WHERE id = '{rec_id}'"),
                description=f"{table}: tombstoned record {rec_id} must not exist in {view_name}",
                severity="error",
                enforced=True,
            )
        )
    return checks


# ---------------------------------------------------------------------------
# YAML loading
# ---------------------------------------------------------------------------


def load_checks(
    yaml_path: Path,
    table_filter: str | None = None,
) -> tuple[list[Check], dict[str, Any]]:
    """Load and compile checks from a YAML file.

    Returns (checks, metadata) where metadata has database/workgroup info.
    """
    with open(yaml_path, encoding="utf-8") as f:
        spec = yaml.safe_load(f)

    database = spec.get("database", "agent_platform")
    workgroup = spec.get("athena_workgroup", "agent-platform-production")
    metadata = {"database": database, "athena_workgroup": workgroup}

    checks: list[Check] = []
    tables = spec.get("tables", {})

    for table_name, table_def in tables.items():
        if table_filter and table_name != table_filter:
            continue

        view_suffix = table_def.get("view_suffix", "")
        query_table = f"{database}.{table_name}{view_suffix}"

        # Table-level checks
        if "row_count" in table_def:
            rc = table_def["row_count"]
            min_rows = rc.get("min", 1)
            severity = rc.get("severity", "error")
            enforced = rc.get("enforced", True)
            exclude_before = rc.get("exclude_before")
            checks.append(
                Check(
                    table=table_name,
                    column=None,
                    test_type="row_count",
                    sql=(
                        f"SELECT CASE WHEN cnt < {min_rows} THEN 1 ELSE 0 END "
                        f"AS violation FROM "
                        f"(SELECT COUNT(*) AS cnt FROM {query_table})"
                    ),
                    description=f"{table_name}: must have >= {min_rows} rows",
                    severity=severity,
                    enforced=enforced,
                    exclude_before=exclude_before,
                )
            )

        if "recency" in table_def:
            rec = table_def["recency"]
            col = rec["column"]
            error_h = rec.get("error_after_hours", 168)
            enforced = rec.get("enforced", True)
            exclude_before = rec.get("exclude_before")
            # Use error threshold for the check; runner can distinguish warn vs error
            checks.append(
                Check(
                    table=table_name,
                    column=col,
                    test_type="recency",
                    sql=(
                        f"SELECT CASE WHEN "
                        f"date_diff('hour', MAX({col}), CURRENT_TIMESTAMP) > {error_h} "
                        f"THEN 1 ELSE 0 END AS violation "
                        f"FROM {query_table}"
                    ),
                    description=(f"{table_name}.{col}: most recent value must be within {error_h}h of now"),
                    severity="error",
                    enforced=enforced,
                    exclude_before=exclude_before,
                )
            )

        # Column-level checks
        columns = table_def.get("columns", {})
        for col_name, col_def in columns.items():
            tests = col_def.get("tests", [])
            for test in tests:
                compiled = _compile_column_test(
                    query_table,
                    table_name,
                    col_name,
                    test,
                )
                if compiled:
                    checks.append(compiled)

    return checks, metadata


def _compile_column_test(
    query_table: str,
    table_name: str,
    col_name: str,
    test: str | dict,
) -> Check | None:
    """Compile a single column test definition to a Check."""
    # Simple string tests: not_null, unique
    if isinstance(test, str):
        if test == "not_null":
            return Check(
                table=table_name,
                column=col_name,
                test_type="not_null",
                sql=(f"SELECT COUNT(*) AS violation FROM {query_table} WHERE {col_name} IS NULL"),
                description=f"{table_name}.{col_name}: must not be NULL",
            )
        if test == "unique":
            return Check(
                table=table_name,
                column=col_name,
                test_type="unique",
                sql=(
                    f"SELECT COUNT(*) AS violation FROM ("
                    f"SELECT {col_name}, COUNT(*) AS n "
                    f"FROM {query_table} "
                    f"GROUP BY {col_name} HAVING COUNT(*) > 1"
                    f")"
                ),
                description=f"{table_name}.{col_name}: must be unique",
            )
        return None

    # Dict tests: accepted_values, relationships, expression
    if isinstance(test, dict):
        test_type = next(iter(test))
        params = test[test_type]

        if test_type == "accepted_values":
            if isinstance(params, list):
                values = params
                severity = "error"
                enforced = True
                eb = None
            else:
                values = params.get("values", [])
                severity = params.get("severity", "error")
                enforced = params.get("enforced", True)
                eb = params.get("exclude_before")
            quoted = ", ".join(f"'{v}'" for v in values)
            temporal = f" AND created_timestamp >= DATE('{eb}')" if eb else ""
            return Check(
                table=table_name,
                column=col_name,
                test_type="accepted_values",
                sql=(
                    f"SELECT COUNT(*) AS violation "
                    f"FROM {query_table} "
                    f"WHERE {col_name} IS NOT NULL "
                    f"AND {col_name} NOT IN ({quoted})"
                    f"{temporal}"
                ),
                description=(f"{table_name}.{col_name}: values must be in [{', '.join(values)}]"),
                severity=severity,
                enforced=enforced,
                exclude_before=eb,
            )

        if test_type == "relationships":
            if not isinstance(params, dict):
                return None
            to_table = params.get("to_table", "")
            to_column = params.get("to_column", "")
            severity = params.get("severity", "error")
            enforced = params.get("enforced", True)
            eb = params.get("exclude_before")
            # Resolve the target table in the same database
            db = query_table.split(".")[0]
            # For SCD tables, check against _current view if it exists
            target = f"{db}.{to_table}"
            temporal = f" AND child.created_timestamp >= DATE('{eb}')" if eb else ""
            return Check(
                table=table_name,
                column=col_name,
                test_type="relationships",
                sql=(
                    f"SELECT COUNT(*) AS violation "
                    f"FROM {query_table} child "
                    f"LEFT JOIN {target} parent "
                    f"ON child.{col_name} = parent.{to_column} "
                    f"WHERE child.{col_name} IS NOT NULL "
                    f"AND parent.{to_column} IS NULL"
                    f"{temporal}"
                ),
                description=(f"{table_name}.{col_name} -> {to_table}.{to_column}: FK must resolve"),
                severity=severity,
                enforced=enforced,
                exclude_before=eb,
            )

        if test_type == "expression":
            if not isinstance(params, dict):
                return None
            sql_expr = params.get("sql", "")
            desc = params.get("description", f"expression: {sql_expr}")
            severity = params.get("severity", "error")
            enforced = params.get("enforced", True)
            eb = params.get("exclude_before")
            temporal = f" AND created_timestamp >= DATE('{eb}')" if eb else ""
            return Check(
                table=table_name,
                column=col_name,
                test_type="expression",
                sql=(f"SELECT COUNT(*) AS violation FROM {query_table} WHERE NOT ({sql_expr}){temporal}"),
                description=f"{table_name}.{col_name}: {desc}",
                severity=severity,
                enforced=enforced,
                exclude_before=eb,
            )

        # not_null / unique can also appear as dict for severity override
        if test_type == "not_null":
            severity = params.get("severity", "error") if isinstance(params, dict) else "error"
            enforced = params.get("enforced", True) if isinstance(params, dict) else True
            eb = params.get("exclude_before") if isinstance(params, dict) else None
            temporal = f" AND created_timestamp >= DATE('{eb}')" if eb else ""
            return Check(
                table=table_name,
                column=col_name,
                test_type="not_null",
                sql=(f"SELECT COUNT(*) AS violation FROM {query_table} WHERE {col_name} IS NULL{temporal}"),
                description=f"{table_name}.{col_name}: must not be NULL",
                severity=severity,
                enforced=enforced,
                exclude_before=eb,
            )

        if test_type == "unique":
            severity = params.get("severity", "error") if isinstance(params, dict) else "error"
            enforced = params.get("enforced", True) if isinstance(params, dict) else True
            eb = params.get("exclude_before") if isinstance(params, dict) else None
            where_clause = f"WHERE created_timestamp >= DATE('{eb}') " if eb else ""
            return Check(
                table=table_name,
                column=col_name,
                test_type="unique",
                sql=(
                    f"SELECT COUNT(*) AS violation FROM ("
                    f"SELECT {col_name}, COUNT(*) AS n "
                    f"FROM {query_table} "
                    f"{where_clause}"
                    f"GROUP BY {col_name} HAVING COUNT(*) > 1"
                    f")"
                ),
                description=f"{table_name}.{col_name}: must be unique",
                severity=severity,
                enforced=enforced,
                exclude_before=eb,
            )

    return None


# ---------------------------------------------------------------------------
# Athena execution
# ---------------------------------------------------------------------------


def _execute_check(
    check: Check,
    athena_client: Any,
    workgroup: str,
    database: str,
) -> CheckResult:
    """Execute a single check against Athena and return the result."""
    start = time.time()
    try:
        response = athena_client.start_query_execution(
            QueryString=check.sql,
            WorkGroup=workgroup,
            QueryExecutionContext={"Database": database},
        )
        query_id = response["QueryExecutionId"]
    except Exception as e:
        return CheckResult(
            check=check,
            verdict="ERROR",
            detail=f"Failed to start query: {e}",
            duration_seconds=time.time() - start,
        )

    # Poll for completion
    elapsed = 0.0
    while elapsed < _MAX_POLL:
        time.sleep(_POLL_INTERVAL)
        elapsed = time.time() - start
        try:
            status = athena_client.get_query_execution(
                QueryExecutionId=query_id,
            )["QueryExecution"]["Status"]
            state = status["State"]
            if state == "SUCCEEDED":
                break
            if state in ("FAILED", "CANCELLED"):
                reason = status.get("StateChangeReason", "unknown")
                return CheckResult(
                    check=check,
                    verdict="ERROR",
                    detail=f"Query {state}: {reason}",
                    duration_seconds=time.time() - start,
                )
        except Exception as e:
            return CheckResult(
                check=check,
                verdict="ERROR",
                detail=f"Poll error: {e}",
                duration_seconds=time.time() - start,
            )
    else:
        return CheckResult(
            check=check,
            verdict="ERROR",
            detail=f"Query timed out after {_MAX_POLL}s",
            duration_seconds=time.time() - start,
        )

    # Read result
    try:
        result = athena_client.get_query_results(QueryExecutionId=query_id)
        rows = result["ResultSet"]["Rows"]
        # First row is header, second row is data
        if len(rows) >= 2:
            violation_count = int(rows[1]["Data"][0]["VarCharValue"])
        else:
            violation_count = 0
    except Exception as e:
        return CheckResult(
            check=check,
            verdict="ERROR",
            detail=f"Failed to read results: {e}",
            duration_seconds=time.time() - start,
        )

    duration = time.time() - start

    if violation_count == 0:
        return CheckResult(
            check=check,
            verdict="PASS",
            violation_count=0,
            duration_seconds=duration,
        )

    # Tombstone resurrection is always HARD_GATE regardless of severity
    if check.test_type == "tombstone_resurrection":
        return CheckResult(
            check=check,
            verdict="HARD_GATE",
            violation_count=violation_count,
            detail=f"resurrected tombstoned record ({violation_count} row(s))",
            duration_seconds=duration,
        )

    # Non-zero violations: enforce-aware labelling.
    # enforced=False + error severity -> UNENFORCED_FAIL (tracked but non-blocking).
    # enforced=False + warn severity -> WARN (purely informational).
    # enforced=True -> FAIL (error) or WARN (warn).
    if not check.enforced:
        verdict = "UNENFORCED_FAIL" if check.severity == "error" else "WARN"
    else:
        verdict = "FAIL" if check.severity == "error" else "WARN"
    return CheckResult(
        check=check,
        verdict=verdict,
        violation_count=violation_count,
        detail=f"{violation_count} violation(s)",
        duration_seconds=duration,
    )


def run_checks(
    checks: list[Check],
    workgroup: str,
    database: str,
    dry_run: bool = False,
    profile_name: str | None = None,
) -> RunResult:
    """Execute all checks and return aggregate result."""
    run_start = time.time()

    if dry_run:
        results = [CheckResult(check=c, verdict="SKIP", detail="dry-run") for c in checks]
        return RunResult(
            results=results,
            verdict="SKIP",
            duration_seconds=time.time() - run_start,
        )

    try:
        import boto3
    except ImportError:
        logger.error("boto3 not available")
        return RunResult(
            results=[CheckResult(check=c, verdict="SKIP", detail="boto3 unavailable") for c in checks],
            verdict="SKIP",
            duration_seconds=0.0,
        )

    from scripts.aws_profile import resolve_aws_profile

    _profile = resolve_aws_profile(profile_name, default=os.environ.get("AWS_DEFAULT_PROFILE") or "agent_platform")
    session = boto3.Session(profile_name=_profile)
    athena = session.client("athena", region_name="eu-west-2")

    results: list[CheckResult] = []
    for check in checks:
        result = _execute_check(check, athena, workgroup, database)
        results.append(result)
        # Log as we go
        symbol = {"PASS": ".", "FAIL": "F", "UNENFORCED_FAIL": "U", "WARN": "W", "ERROR": "E", "SKIP": "S"}
        print(symbol.get(result.verdict, "?"), end="", flush=True)

    print()  # newline after progress dots

    # Aggregate verdict
    if not results:
        verdict = "ERROR"
    else:
        has_hard_gate = any(r.verdict == "HARD_GATE" for r in results)
        has_fail = any(r.verdict == "FAIL" and r.check.enforced for r in results)
        has_error = any(r.verdict == "ERROR" for r in results)
        verdict = "HARD_GATE" if has_hard_gate else ("FAIL" if (has_fail or has_error) else "PASS")

    return RunResult(
        results=results,
        verdict=verdict,
        duration_seconds=time.time() - run_start,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _print_results(run_result: RunResult, as_json: bool = False) -> None:
    """Print results to stdout."""
    if as_json:
        output = {
            "verdict": run_result.verdict,
            "total": len(run_result.results),
            "passed": run_result.passed,
            "failed": run_result.failed,
            "unenforced_fail": run_result.unenforced_fail,
            "warned": run_result.warned,
            "errored": run_result.errored,
            "skipped": run_result.skipped,
            "duration_seconds": round(run_result.duration_seconds, 1),
            "checks": [
                {
                    "table": r.check.table,
                    "column": r.check.column,
                    "test": r.check.test_type,
                    "verdict": r.verdict,
                    "violations": r.violation_count,
                    "detail": r.detail,
                    "description": r.check.description,
                }
                for r in run_result.results
            ],
        }
        print(json.dumps(output, indent=2))
        return

    # Human-readable summary
    print(f"\n{'=' * 60}")
    print(f"Data Quality: {run_result.verdict}")
    print(f"{'=' * 60}")
    print(
        f"  Passed: {run_result.passed}  "
        f"Failed: {run_result.failed}  "
        f"Unenforced: {run_result.unenforced_fail}  "
        f"Warned: {run_result.warned}  "
        f"Errors: {run_result.errored}  "
        f"Skipped: {run_result.skipped}"
    )
    print(f"  Duration: {run_result.duration_seconds:.1f}s")
    print()

    # Show failures and warnings
    issues = [r for r in run_result.results if r.verdict in ("FAIL", "UNENFORCED_FAIL", "WARN", "ERROR", "HARD_GATE")]
    if issues:
        print("Issues:")
        for r in issues:
            prefix = {
                "FAIL": "FAIL",
                "UNENFORCED_FAIL": "UENF",
                "WARN": "WARN",
                "ERROR": "ERR ",
                "HARD_GATE": "GATE",
            }[r.verdict]
            print(f"  [{prefix}] {r.check.description}")
            if r.detail:
                print(f"         {r.detail}")
        print()


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Run data quality checks against Athena tables",
    )
    parser.add_argument(
        "--file",
        "-f",
        help="Specific YAML file to load (default: all files in config/agent/data_quality/)",
    )
    parser.add_argument(
        "--table",
        "-t",
        help="Run checks for a specific table only",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print compiled SQL without executing",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON",
    )
    parser.add_argument(
        "--severity",
        choices=["error", "warn", "all"],
        default="all",
        help="Filter checks by severity (default: all)",
    )
    parser.add_argument(
        "--checks",
        metavar="TYPE",
        help="Run only checks of this test type (e.g. tombstone_resurrection)",
    )
    parser.add_argument(
        "--profile",
        default=None,
        metavar="PROFILE",
        help="AWS SSO profile name (default: AWS_PROFILE env, then agent_platform)",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    # Load YAML files
    if args.file:
        yaml_files = [Path(args.file)]
    else:
        yaml_files = sorted(_DQ_DIR.glob("*.yaml"))

    if not yaml_files:
        logger.error("No YAML files found in %s", _DQ_DIR)
        return 1

    all_checks: list[Check] = []
    workgroup: str | None = None
    database: str | None = None

    for yf in yaml_files:
        checks, metadata = load_checks(yf, table_filter=args.table)
        file_wg = metadata.get("athena_workgroup", "agent-platform-production")
        file_db = metadata.get("database", "agent_platform")
        if workgroup is None:
            workgroup, database = file_wg, file_db
        elif file_wg != workgroup or file_db != database:
            logger.error(
                "Conflicting database/workgroup in %s (%s/%s) vs previous files (%s/%s). "
                "Use --file to run each YAML separately.",
                yf,
                file_db,
                file_wg,
                database,
                workgroup,
            )
            return 1
        all_checks.extend(checks)

    workgroup = workgroup or "agent-platform-production"
    database = database or "agent_platform"

    # Add tombstone resurrection checks
    tombstones = load_tombstones()
    all_checks.extend(build_tombstone_checks(tombstones, table_filter=args.table, database=database))

    # Filter by check type (e.g. --checks tombstone_resurrection)
    if args.checks:
        all_checks = [c for c in all_checks if c.test_type == args.checks]

    # Filter by severity
    if args.severity == "error":
        all_checks = [c for c in all_checks if c.severity == "error"]
    elif args.severity == "warn":
        all_checks = [c for c in all_checks if c.severity == "warn"]

    if not all_checks:
        logger.info("No checks match filters")
        return 0

    logger.info(
        "Running %d checks against %s (workgroup: %s)",
        len(all_checks),
        database,
        workgroup,
    )

    if args.dry_run:
        result = run_checks(all_checks, workgroup, database, dry_run=True, profile_name=args.profile)
        if args.json:
            _print_results(result, as_json=True)
            _save_latest_result(result)
        else:
            for r in result.results:
                print(f"\n-- [{r.check.severity.upper()}] {r.check.description}")
                print(f"{r.check.sql};")
        return 0

    # Execute
    result = run_checks(all_checks, workgroup, database, dry_run=False, profile_name=args.profile)
    _print_results(result, as_json=args.json)

    # Save latest result for preflight consumption
    _save_latest_result(result)

    return 0 if result.verdict == "PASS" else 1


def _save_latest_result(result: RunResult) -> None:
    """Write a summary to logs/debug/dq-latest.json for preflight pickup."""
    from datetime import datetime, timezone  # noqa: PLC0415

    if not result.results:
        return

    out_dir = _ROOT / "logs" / "debug"
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "verdict": result.verdict,
        "total": len(result.results),
        "passed": result.passed,
        "failed": result.failed,
        "unenforced_fail": result.unenforced_fail,
        "warned": result.warned,
        "errored": result.errored,
        "hard_gated": result.hard_gated,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "duration_seconds": round(result.duration_seconds, 1),
        "checks": [
            {"table": r.check.table, "column": r.check.column, "test": r.check.test_type, "verdict": r.verdict}
            for r in result.results
        ],
    }
    if summary["total"] == 0:
        summary["verdict"] = "ERROR"
    (out_dir / "dq-latest.json").write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    sys.exit(main())
