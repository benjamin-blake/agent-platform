"""
Purge known orphan rows from ops_recommendations and assert post-purge state.

Root cause analysis (RCA):
- PR #304 deleted local S3 outbox files for rec-608 and rec-633. Those rows had
  already been drained to Athena before the plan ran, so no Athena DML was ever
  issued. The PR only removed the local outbox artefact, not the warehouse row.
- PLAN-dq-write-enforcement-unification VP Step 7 prescribed an inline DELETE
  one-liner for id IS NULL; the implementation commit (b6ba53b) contains no
  evidence it was executed. The ghost row (id=NULL) persists in the warehouse.
- Root cause class: Class E -- post-deploy cleanup step not executed or not
  asserted. See docs/dq/DQ_REMEDIATION_METHODOLOGY.md.

This script closes the gap by treating DELETE + assertion as one atomic unit,
preventing a recurrence where cleanup appears complete but the warehouse row
persists.
"""

from __future__ import annotations

import argparse
import time
from typing import Any

import boto3

KNOWN_ORPHAN_IDS: list[str] = ["rec-608", "rec-633"]

_WORKGROUP = "agent-platform-production"
_DATABASE = "trading_formulas_db"
_AWS_REGION = "eu-west-2"
_SSO_PROFILE = "company-aws-profile"
_S3_SCRATCH = "s3://bblake-platform-agent-logs/athena-scratch/"


def _run_athena_query(client: Any, sql: str) -> str:
    """Submit an Athena query, poll until terminal state, and return QueryExecutionId."""
    response = client.start_query_execution(
        QueryString=sql,
        WorkGroup=_WORKGROUP,
        ResultConfiguration={"OutputLocation": _S3_SCRATCH},
    )
    qid: str = response["QueryExecutionId"]
    for _ in range(30):
        status = client.get_query_execution(QueryExecutionId=qid)["QueryExecution"]["Status"]
        state: str = status["State"]
        if state in ("SUCCEEDED", "FAILED", "CANCELLED"):
            if state != "SUCCEEDED":
                reason = status.get("StateChangeReason", "")
                raise RuntimeError(f"Athena query {state}: {reason}")
            return qid
        time.sleep(2)
    raise RuntimeError(f"Athena query timed out after 60s: {qid}")


def _row_count(client: Any, query_id: str) -> int:
    """Return the integer from the first data row of a COUNT(*) query result."""
    rows = client.get_query_results(QueryExecutionId=query_id)["ResultSet"]["Rows"]
    if len(rows) < 2:
        return 0
    return int(rows[1]["Data"][0]["VarCharValue"])


def purge_orphans(dry_run: bool = False) -> None:
    """Delete known orphan rows from ops_recommendations and assert absence post-purge."""
    session = boto3.Session(profile_name=_SSO_PROFILE)
    client = session.client("athena", region_name=_AWS_REGION)

    id_list = ", ".join(f"'{i}'" for i in KNOWN_ORPHAN_IDS)

    # (a) Pre-check: identify current violators in the view
    pre_sql = f"SELECT id FROM {_DATABASE}.ops_recommendations_current WHERE id IN ({id_list}) OR id IS NULL"
    pre_qid = _run_athena_query(client, pre_sql)
    rows = client.get_query_results(QueryExecutionId=pre_qid)["ResultSet"]["Rows"]
    found = [r["Data"][0].get("VarCharValue", "NULL") for r in rows[1:]]
    print(f"Target rows found: {found}")

    if dry_run:
        return

    # (c) DELETE known IDs from base table
    _run_athena_query(client, f"DELETE FROM {_DATABASE}.ops_recommendations WHERE id IN ({id_list})")

    # (d) DELETE NULL-id ghost row from base table
    _run_athena_query(client, f"DELETE FROM {_DATABASE}.ops_recommendations WHERE id IS NULL")

    # (e) VACUUM to expire deleted snapshots (requires engine v3 workgroup)
    _run_athena_query(client, f"VACUUM {_DATABASE}.ops_recommendations")

    # (f) Post-assert: confirm zero orphans remain in the current view
    post_sql = f"SELECT count(*) FROM {_DATABASE}.ops_recommendations_current WHERE id IN ({id_list}) OR id IS NULL"
    post_qid = _run_athena_query(client, post_sql)
    remaining = _row_count(client, post_qid)
    if remaining != 0:
        raise AssertionError(f"Purge incomplete: {remaining} orphan rows remain in ops_recommendations_current")
    print("PURGE_COMPLETE: 0 orphan rows remain")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Purge orphan rows from ops_recommendations.")
    parser.add_argument("--dry-run", action="store_true", help="Print target rows without deleting.")
    args = parser.parse_args()
    purge_orphans(dry_run=args.dry_run)
