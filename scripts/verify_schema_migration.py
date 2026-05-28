"""Verification script for the ops schema migration (Decision 56).

Provides two modes:
  --write-probe   Stage a test rec via ops_data_portal and compact it.
  --query-probe   Query Athena for the probe rec, assert schema correctness.

Usage:
    python -m scripts.verify_schema_migration --write-probe --profile company-aws-profile
    python -m scripts.verify_schema_migration --query-probe --profile company-aws-profile

The probe rec ID is "rec-schema-probe-001" and is idempotent (can be re-run).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_PROBE_REC_ID = "rec-schema-probe-001"
_DATABASE = "trading_formulas_db"
_WORKGROUP = "agent-platform-production"
_OUTPUT_LOCATION = "s3://bblake-platform-agent-logs/athena-results/"

_PROBE_REC = {
    "id": _PROBE_REC_ID,
    "date": "2026-04-30",
    "title": "Schema migration verification probe",
    "source": "planning",
    "effort": "XS",
    "priority": "Low",
    "status": "open",
    "automatable": False,
    "risk": "low",
    "file": "scripts/verify_schema_migration.py",
    "context": "Probe record written by verify_schema_migration.py to confirm new schema works end-to-end.",
    "acceptance": "python -m scripts.verify_schema_migration --query-probe --profile company-aws-profile",
    "dependencies": [],
    "tags": ["schema-probe"],
    "resolution": None,
    "execution_result": None,
    "execution_date": None,
    "execution_branch": None,
    "execution_pr_url": None,
    "execution_steps": None,
}


def _write_probe(profile: str | None) -> None:
    """Stage the probe rec via OpsWriter and compact it into Iceberg."""
    if profile:
        os.environ["AWS_PROFILE"] = profile

    bucket = os.environ.get("S3_LOG_BUCKET", "bblake-platform-agent-logs")
    os.environ.setdefault("S3_LOG_BUCKET", bucket)

    # Temporarily unset PYTEST_CURRENT_TEST so write() doesn't no-op
    prev_pytest = os.environ.pop("PYTEST_CURRENT_TEST", None)
    try:
        from scripts.ops_writer import OpsWriter  # noqa: PLC0415

        writer = OpsWriter()
        print(f"Writing probe rec {_PROBE_REC_ID} to ops_recommendations staging...")
        writer.write("ops_recommendations", dict(_PROBE_REC))
        print("Staged successfully. Compacting...")
        count = writer.compact("ops_recommendations")
        print(f"Compaction complete: {count} rows compacted.")
        if count == 0:
            print("WARNING: compact() returned 0 -- check S3 staging files and bucket config.")
        else:
            print("PASS: write-probe completed.")
    finally:
        if prev_pytest is not None:
            os.environ["PYTEST_CURRENT_TEST"] = prev_pytest


def _run_athena_query(query: str, profile: str | None) -> list[dict] | None:
    """Execute an Athena query and return rows as list of dicts."""
    import boto3  # noqa: PLC0415

    session_kwargs = {}
    if profile:
        session_kwargs["profile_name"] = profile
    session = boto3.Session(**session_kwargs)
    client = session.client("athena", region_name="eu-west-2")

    resp = client.start_query_execution(
        QueryString=query,
        QueryExecutionContext={"Database": _DATABASE},
        ResultConfiguration={"OutputLocation": _OUTPUT_LOCATION},
        WorkGroup=_WORKGROUP,
    )
    query_id = resp["QueryExecutionId"]
    print(f"  Query ID: {query_id}")

    for _ in range(60):
        time.sleep(2)
        status = client.get_query_execution(QueryExecutionId=query_id)
        state = status["QueryExecution"]["Status"]["State"]
        if state == "SUCCEEDED":
            break
        if state in ("FAILED", "CANCELLED"):
            reason = status["QueryExecution"]["Status"].get("StateChangeReason", "")
            print(f"  Query {state}: {reason}", file=sys.stderr)
            return None

    result = client.get_query_results(QueryExecutionId=query_id)
    col_names = [c["Label"] for c in result["ResultSet"]["ResultSetMetadata"]["ColumnInfo"]]
    rows = []
    for row in result["ResultSet"]["Rows"][1:]:
        values = [d.get("VarCharValue", "") for d in row["Data"]]
        rows.append(dict(zip(col_names, values)))
    return rows


def _query_probe(profile: str | None) -> None:
    """Query Athena for the probe rec and assert schema correctness."""
    if profile:
        os.environ["AWS_PROFILE"] = profile

    sql = (
        f"SELECT id, created_timestamp, last_updated_timestamp, status "
        f"FROM {_DATABASE}.ops_recommendations_current "
        f"WHERE id = '{_PROBE_REC_ID}'"
    )
    print(f"Querying Athena: {sql}")
    rows = _run_athena_query(sql, profile)

    if rows is None:
        print("FAIL: Athena query failed.", file=sys.stderr)
        sys.exit(1)

    if not rows:
        print(
            f"FAIL: No rows returned for probe rec {_PROBE_REC_ID}. Run --write-probe first, or check migration status.",
            file=sys.stderr,
        )
        sys.exit(1)

    row = rows[0]
    print(f"Row returned: {json.dumps(row, indent=2)}")

    failures = []
    if not row.get("created_timestamp"):
        failures.append("created_timestamp is empty or null")
    if not row.get("last_updated_timestamp"):
        failures.append("last_updated_timestamp is empty or null")
    if "trade_date" in row:
        failures.append("trade_date column still present (should have been removed)")
    if "date" in row and row.get("date"):
        failures.append(f"date column still present with value: {row['date']}")

    if failures:
        print("FAIL:", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        sys.exit(1)

    print(
        f"PASS: Probe rec found with created_timestamp={row['created_timestamp']!r} "
        f"and last_updated_timestamp={row['last_updated_timestamp']!r}"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Verify ops schema migration (Decision 56)")
    parser.add_argument("--write-probe", action="store_true", help="Stage and compact a probe rec")
    parser.add_argument("--query-probe", action="store_true", help="Query Athena to verify probe rec schema")
    parser.add_argument("--profile", default=None, help="AWS SSO profile")
    args = parser.parse_args()

    if args.write_probe:
        _write_probe(args.profile)
    elif args.query_probe:
        _query_probe(args.profile)
    else:
        parser.print_help()
        sys.exit(1)
