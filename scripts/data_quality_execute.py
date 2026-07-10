"""Data quality execution + aggregation: Athena/DuckLake backend dispatch and check runner."""

from __future__ import annotations

import logging
import os
import re
import time
from typing import Any

import yaml

from scripts.data_quality_compile import build_clause8_checks, to_ducklake_sql
from scripts.data_quality_models import _DQ_DIR, Check, CheckResult, RunResult

logger = logging.getLogger(__name__)

_POLL_INTERVAL = 2  # seconds between Athena status checks
_MAX_POLL = 60  # max seconds to wait for a single query
_TRANSIENT_HTTP_RE = re.compile(r"failed \(HTTP (?:502|503|504)\)")

# Ops governance tables (the full set; telemetry_* stays on Athena per Decision 78 cl.2).
_OPS_TABLES: frozenset[str] = frozenset(
    {"ops_recommendations", "ops_decisions", "ops_priority_queue", "ops_session_log", "ops_execution_plans"}
)
# RECS-FIRST SLICE: only ops_recommendations is migrated to DuckLake. Every other ops table stays on
# Athena/Iceberg until their T2.26 disposition (Decision 84), so only this set routes to
# the DuckLake reader when the flag is set.
# Tables on the DuckLake closed boundary (Decision 84 I-1): their checks route to the reader.
# ops_session_log / ops_execution_plans stay on the Athena views until their T2.26 disposition.
_DUCKLAKE_OPS_TABLES: frozenset[str] = frozenset({"ops_recommendations", "ops_decisions", "ops_priority_queue"})


def _ops_backend() -> str:
    """DuckLake is the sole ops backend (Decision 84 I-1; the rollback flag is retired)."""
    return "ducklake"


# ---------------------------------------------------------------------------
# Athena execution
# ---------------------------------------------------------------------------


def _verdict_for(check: Check, violation_count: int, duration: float) -> CheckResult:
    """Map a violation count to a verdict (shared by the Athena + DuckLake execution paths)."""
    if violation_count == 0:
        return CheckResult(check=check, verdict="PASS", violation_count=0, duration_seconds=duration)
    # Tombstone resurrection is always HARD_GATE regardless of severity.
    if check.test_type == "tombstone_resurrection":
        return CheckResult(
            check=check,
            verdict="HARD_GATE",
            violation_count=violation_count,
            detail=f"resurrected tombstoned record ({violation_count} row(s))",
            duration_seconds=duration,
        )
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


def _query_ops_rows(reader: Any, table: str, sql: str) -> list[dict]:
    """Call the reader's raising _invoke surface and return the rows list."""
    body = reader._invoke({"action": "query_ops", "table": table, "sql": sql, "params": []})
    return list(body.get("rows", []))


def _is_reader_unavailable(exc: BaseException) -> bool:
    """True when exc indicates a transient DuckLake reader infra outage.

    Transient: requests ConnectionError/Timeout, or a RuntimeError whose message
    matches the reader's own transient set {502,503,504} with no structured error_type marker.
    Structured handler errors (HTTP 500 + error_type, 4xx) are not transient -- they gate.
    """
    try:
        import requests as _req  # noqa: PLC0415

        if isinstance(exc, (_req.ConnectionError, _req.Timeout)):
            return True
    except ImportError:
        pass
    if isinstance(exc, RuntimeError):
        msg = str(exc)
        if _TRANSIENT_HTTP_RE.search(msg) and "error_type" not in msg:
            return True
    return False


def _execute_check_ducklake(check: Check, reader: Any) -> CheckResult:
    """Execute a single ops-table check against DuckLake via the closed reader. DuckDB dialect.

    `ulid_history_unique` runs over the history table (read_ops_history surface); the other checks run
    over the current projection via query_ops. A cross-table relationships check cannot be expressed
    through the single-`{tbl}` reader surface and is SKIPPED on this backend (priority_queue FK is
    dormant + unenforced).
    """
    start = time.time()
    if check.test_type == "relationships":
        return CheckResult(
            check=check,
            verdict="SKIP",
            detail="cross-table FK not run on ducklake backend (dormant/unenforced)",
            duration_seconds=0.0,
        )
    table = check.table
    is_history = check.test_type == "ulid_history_unique"
    sql = check.sql if check.backend == "ducklake" else to_ducklake_sql(check.sql, table, "agent_platform")
    try:
        if is_history:
            from src.common.ducklake_runtime import resolve_table_spec  # noqa: PLC0415

            hist = resolve_table_spec(table).history_table
            rows = _query_ops_rows(reader, table, sql.replace("{tbl}", f"ops_catalog.{hist}"))
        else:
            rows = _query_ops_rows(reader, table, sql)
        if rows is None:
            return CheckResult(
                check=check, verdict="ERROR", detail="ducklake reader returned None", duration_seconds=time.time() - start
            )
        violation_count = int(next(iter(rows[0].values()))) if rows else 0
    except Exception as exc:  # noqa: BLE001
        verdict = "UNAVAILABLE" if _is_reader_unavailable(exc) else "ERROR"
        return CheckResult(
            check=check, verdict=verdict, detail=f"ducklake query failed: {exc}", duration_seconds=time.time() - start
        )
    return _verdict_for(check, violation_count, time.time() - start)


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

    return _verdict_for(check, violation_count, time.time() - start)


def apply_backend_routing(all_checks: list[Check], database: str, *, table_filter: str | None = None) -> list[Check]:
    """Route the migrated-table checks to the DuckLake reader (sole backend, Decision 84 I-1).

    Rewrite every check on a migrated
    recs table to the DuckLake closed reader (DuckDB dialect over the `current` TABLE) and append
    the CD.33 clause-8 checks. iceberg (rollback) leaves all checks on the Athena views.

    Shared by main() AND DataQualityVerifier so the verifier harness routes recs through the
    reader -- NOT the dropped ops_recommendations_current Athena view (which would TABLE_NOT_FOUND).
    Mutates and returns *all_checks*.
    """
    for c in all_checks:
        if c.table in _DUCKLAKE_OPS_TABLES:
            c.sql = to_ducklake_sql(c.sql, c.table, database)
            c.backend = "ducklake"
    ops_spec_yaml = yaml.safe_load((_DQ_DIR / "ops.yaml").read_text(encoding="utf-8")) or {}
    all_checks.extend(build_clause8_checks(ops_spec_yaml, database, table_filter=table_filter))
    return all_checks


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

    # DuckLake checks route through the closed reader; Athena checks need the boto3 client. Build
    # each lazily so a pure-DuckLake run does not require boto3 and vice versa.
    needs_athena = any(c.backend != "ducklake" for c in checks)
    needs_ducklake = any(c.backend == "ducklake" for c in checks)

    athena = None
    if needs_athena:
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
        athena = boto3.Session(profile_name=_profile).client("athena", region_name="eu-west-2")

    reader = None
    if needs_ducklake:
        from src.common.iceberg_reader import DuckLakeReader  # noqa: PLC0415

        reader = DuckLakeReader(profile=profile_name)

    results: list[CheckResult] = []
    for check in checks:
        if check.backend == "ducklake":
            result = _execute_check_ducklake(check, reader)
        else:
            result = _execute_check(check, athena, workgroup, database)
        results.append(result)
        # Log as we go
        symbol = {
            "PASS": ".",
            "FAIL": "F",
            "UNENFORCED_FAIL": "U",
            "WARN": "W",
            "ERROR": "E",
            "SKIP": "S",
            "HARD_GATE": "G",
            "UNAVAILABLE": "A",
        }
        print(symbol.get(result.verdict, "?"), end="", flush=True)

    print()  # newline after progress dots

    # Aggregate verdict
    if not results:
        verdict = "ERROR"
    else:
        has_hard_gate = any(r.verdict == "HARD_GATE" for r in results)
        has_fail = any(r.verdict == "FAIL" and r.check.enforced for r in results)
        has_error = any(r.verdict == "ERROR" for r in results)
        has_unavailable = any(r.verdict == "UNAVAILABLE" for r in results)
        verdict = (
            "HARD_GATE" if has_hard_gate else "FAIL" if (has_fail or has_error) else "DEGRADED" if has_unavailable else "PASS"
        )

    return RunResult(
        results=results,
        verdict=verdict,
        duration_seconds=time.time() - run_start,
    )
