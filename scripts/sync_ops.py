# complexity-waiver: decision-43
"""sync_ops -- bidirectional sync between local JSONL files and Athena ops tables.

Provides one CLI subcommand:
  sync   -- drain outbox then pull all tables from Athena

Internal helpers (not for direct agent use):
  drain              -- flush outbox entries to S3 via OpsWriter
  _rebuild_local_cache -- query Athena views and overwrite local JSONL files
  _pull_single_table -- pull a single table from Athena

Never raises to callers. All functions catch and log exceptions internally.
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).parent.parent
_LOGS_DIR = _REPO_ROOT / "logs"
_OUTBOX_DIR = _LOGS_DIR / ".ops-outbox"

# Maps Iceberg table name -> local JSONL file (relative to _LOGS_DIR)
_TABLE_TO_LOCAL: dict[str, str] = {
    "ops_recommendations": ".recommendations-log.jsonl",
    "ops_execution_plans": ".execution-plans.jsonl",
    "ops_session_log": ".session-telemetry.jsonl",
    "ops_decisions": ".decisions-index.jsonl",
    "ops_priority_queue": "priority-queue/.priority-queue.jsonl",
    "telemetry_sessions": ".telemetry-sessions.jsonl",
    "telemetry_phases": ".telemetry-phases.jsonl",
    "telemetry_steps": ".telemetry-steps.jsonl",
    "telemetry_process_events": ".telemetry-process-events.jsonl",
    "telemetry_model_calls": ".telemetry-model-calls.jsonl",
    "telemetry_transcripts": ".telemetry-transcripts.jsonl",
    "telemetry_agent_invocations": ".telemetry-agent-invocations.jsonl",
}

# Maps Iceberg table name -> Athena view/table to query
_TABLE_TO_VIEW: dict[str, str] = {
    "ops_recommendations": "ops_recommendations_current",
    "ops_execution_plans": "ops_execution_plans",
    "ops_session_log": "ops_session_log",
    "ops_decisions": "ops_decisions_current",
    "ops_priority_queue": "ops_priority_queue_current",
    # telemetry current-state views (deduplication via ROW_NUMBER)
    "telemetry_sessions": "telemetry_sessions_current",
    "telemetry_phases": "telemetry_phases_current",
    "telemetry_steps": "telemetry_steps_current",
    # events/calls/transcripts are append-only with no _current view (never updated)
    "telemetry_process_events": "telemetry_process_events",
    "telemetry_model_calls": "telemetry_model_calls",
    "telemetry_transcripts": "telemetry_transcripts",
    # agent invocations have a _current view (findings processor may update same invocation_id)
    "telemetry_agent_invocations": "telemetry_agent_invocations_current",
}

_DATABASE = "trading_formulas_db"
_WORKGROUP = "agent-platform-production"
_SSO_PROFILE = "company-aws-profile"
_SYNC_REJECTS_LOG = _LOGS_DIR / "debug" / "dq-sync-rejects.jsonl"
_DECISIONS_SYNC_REJECTS_LOG = _LOGS_DIR / "debug" / "decisions-sync-rejects.jsonl"
_REQUIRED_REC_FIELDS = ["title", "source", "effort", "priority"]


def _write_sync_reject(row: dict, reason: str) -> None:
    """Append a rejected ops_recommendations row to the sync-rejects debug log."""
    try:
        _SYNC_REJECTS_LOG.parent.mkdir(parents=True, exist_ok=True)
        entry = {"rejected_at": datetime.now(timezone.utc).isoformat(), "reason": reason, "row": row}
        with _SYNC_REJECTS_LOG.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as exc:  # noqa: BLE001
        logger.warning("sync_ops._write_sync_reject: could not write reject log: %s", exc)


def _coerce_athena_array(val: object, *, elem_type: type = str) -> list:
    """Parse an Athena VarChar-serialised array into a typed Python list.

    Athena represents array<string> and array<int> columns as "[elem1, elem2]"
    with unquoted, comma-separated elements. ast.literal_eval is not suitable
    here because elements are not quoted Python string literals.
    Returns [] for null/empty values.
    """
    raw = str(val).strip() if val is not None else ""
    if not raw:
        return []
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        if not inner:
            return []
        result = []
        for part in inner.split(","):
            part = part.strip()
            if part:
                try:
                    result.append(elem_type(part))
                except (ValueError, TypeError):
                    pass
        return result
    try:
        return [elem_type(raw)]
    except (ValueError, TypeError):
        return []


def _coerce_ops_rec_row(row: dict) -> dict | None:
    """Coerce Athena VarChar string values in an ops_recommendations row to proper Python types.

    Athena get_query_results returns every column as a VarCharValue string.
    array<string> columns arrive as "[elem1, elem2]"; null scalars arrive as "".

    Returns None and writes a reject log entry if the row has an invalid id prefix.
    """
    rec_id = row.get("id", "")
    if not rec_id.startswith(("rec-", "agent-", "test-")):
        _write_sync_reject(row, f"invalid id prefix: {rec_id!r}")
        return None
    for field in ("dependencies", "tags"):
        row[field] = _coerce_athena_array(row.get(field))
    steps = row.get("execution_steps")
    if not isinstance(steps, int):
        try:
            row["execution_steps"] = int(steps) if steps else None
        except (ValueError, TypeError):
            row["execution_steps"] = None
    automatable = row.get("automatable")
    if not isinstance(automatable, bool):
        if automatable == "":
            row["automatable"] = None
        elif isinstance(automatable, str):
            row["automatable"] = {"true": True, "false": False}.get(automatable.lower())
    return row


def _coerce_ops_priority_queue_row(row: dict) -> dict:
    """Coerce Athena VarChar strings in an ops_priority_queue row to proper Python types."""
    for field in ("compound_with", "gates"):
        row[field] = _coerce_athena_array(row.get(field))
    rank = row.get("rank")
    if not isinstance(rank, int):
        try:
            row["rank"] = int(rank) if rank else None
        except (ValueError, TypeError):
            row["rank"] = None
    return row


def _write_decisions_sync_reject(row: dict, reason: str) -> None:
    """Append a rejected ops_decisions row to the decisions sync-rejects debug log."""
    try:
        _DECISIONS_SYNC_REJECTS_LOG.parent.mkdir(parents=True, exist_ok=True)
        entry = {"rejected_at": datetime.now(timezone.utc).isoformat(), "reason": reason, "row": row}
        with _DECISIONS_SYNC_REJECTS_LOG.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as exc:  # noqa: BLE001
        logger.warning("sync_ops._write_decisions_sync_reject: could not write reject log: %s", exc)


def _coerce_ops_decisions_row(row: dict) -> dict:
    """Coerce Athena VarChar strings in an ops_decisions row to proper Python types.

    Also populates legacy decision_id from id (or vice versa) and logs a
    sync-reject entry when the dual-write invariant is violated.
    """
    decision_id = row.get("decision_id")
    if not isinstance(decision_id, int):
        try:
            row["decision_id"] = int(decision_id) if decision_id else None
        except (ValueError, TypeError):
            row["decision_id"] = None
    row["related_decisions"] = _coerce_athena_array(row.get("related_decisions"), elem_type=int)

    dec_id = row.get("id")
    coerced_did = row.get("decision_id")

    if not dec_id and coerced_did is not None:
        row["id"] = f"dec-{coerced_did:03d}"
    elif dec_id and coerced_did is not None:
        try:
            expected = int(dec_id.split("-")[1])
            if expected != coerced_did:
                _write_decisions_sync_reject(
                    row,
                    f"dual-write invariant: id={dec_id!r} implies decision_id={expected}, got {coerced_did}",
                )
        except (IndexError, ValueError):
            pass

    return row


def _coerce_ops_session_log_row(row: dict) -> dict:
    """Coerce Athena VarChar strings in an ops_session_log row to proper Python types."""
    for field in ("recs_attempted", "recs_closed"):
        row[field] = _coerce_athena_array(row.get(field))
    duration = row.get("duration_minutes")
    if not isinstance(duration, int):
        try:
            row["duration_minutes"] = int(duration) if duration else None
        except (ValueError, TypeError):
            row["duration_minutes"] = None
    return row


def check_sso(profile: str = _SSO_PROFILE) -> bool:
    """Return True if the given SSO profile has valid credentials."""
    try:
        result = subprocess.run(
            ["aws", "sts", "get-caller-identity", "--profile", profile],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        return result.returncode == 0
    except Exception as exc:  # noqa: BLE001
        logger.warning("sync_ops.check_sso: credential check failed: %s", exc)
        return False


def drain() -> dict[str, int]:
    """Flush all outbox entries to S3 via OpsWriter.

    Returns:
        Dict mapping table name to number of entries drained.
        Empty dict if outbox is empty or does not exist.
    """
    counts: dict[str, int] = {}

    if not _OUTBOX_DIR.exists():
        return counts

    try:
        from scripts.ops_writer import OpsWriter  # noqa: PLC0415  # lazy import

        writer = OpsWriter()

        for table_dir in _OUTBOX_DIR.iterdir():
            if not table_dir.is_dir():
                continue
            table = table_dir.name
            drained = 0
            for outbox_file in list(table_dir.glob("*.jsonl")):
                try:
                    raw = outbox_file.read_text(encoding="utf-8")
                    entry = json.loads(raw.strip())
                    writer.write(table, entry)
                    outbox_file.unlink(missing_ok=True)
                    drained += 1
                except Exception as exc:  # noqa: BLE001
                    logger.warning("sync_ops.drain: failed to drain %s: %s", outbox_file, exc)
            if drained:
                counts[table] = drained
                logger.info("sync_ops.drain: drained %d entries for %s", drained, table)

    except Exception as exc:  # noqa: BLE001
        logger.warning("sync_ops.drain: unexpected error: %s", exc)

    return counts


def _pull_single_table(table: str, profile: str = _SSO_PROFILE) -> int:
    """Pull a single Athena table/view and overwrite the local JSONL file.

    Returns number of rows pulled, or 0 on failure.
    """
    if not check_sso(profile):
        logger.warning("sync_ops._pull_single_table: SSO credentials not available for %s", table)
        return 0

    view = _TABLE_TO_VIEW.get(table)
    if not view:
        logger.warning("sync_ops._pull_single_table: unknown table %r", table)
        return 0

    try:
        import boto3 as _boto3  # noqa: PLC0415

        session = _boto3.Session(profile_name=profile)
        athena = session.client("athena", region_name="eu-west-2")

        query = f"SELECT * FROM {_DATABASE}.{view}"
        response = athena.start_query_execution(QueryString=query, WorkGroup=_WORKGROUP)
        execution_id = response["QueryExecutionId"]

        for _ in range(60):
            time.sleep(2)
            status_resp = athena.get_query_execution(QueryExecutionId=execution_id)
            state = status_resp["QueryExecution"]["Status"]["State"]
            if state in ("SUCCEEDED", "FAILED", "CANCELLED"):
                break

        if state != "SUCCEEDED":
            reason = status_resp["QueryExecution"]["Status"].get("StateChangeReason", "unknown")
            logger.warning("sync_ops._pull_single_table: query for %s ended with state %s: %s", table, state, reason)
            return 0

        rows: list[dict] = []
        rejected_count = 0
        paginator = athena.get_paginator("get_query_results")
        header: list[str] = []
        is_first_page = True

        for page in paginator.paginate(QueryExecutionId=execution_id):
            page_rows = page.get("ResultSet", {}).get("Rows", [])
            for row_index, raw_row in enumerate(page_rows):
                data = [col.get("VarCharValue", "") for col in raw_row.get("Data", [])]
                if is_first_page and row_index == 0:
                    header = data
                    is_first_page = False
                    continue
                if not header:
                    continue
                row: dict = dict(zip(header, data))
                row.pop("_rn", None)
                row.pop("row_num", None)
                if table == "ops_recommendations":
                    row = _coerce_ops_rec_row(row)  # type: ignore[assignment]
                    if row is None:
                        rejected_count += 1
                        continue
                    missing = [f for f in _REQUIRED_REC_FIELDS if not row.get(f) or not str(row[f]).strip()]
                    if missing:
                        _write_sync_reject(row, f"missing/empty required fields: {missing}")
                        rejected_count += 1
                        continue
                elif table == "ops_priority_queue":
                    row = _coerce_ops_priority_queue_row(row)
                elif table == "ops_decisions":
                    row = _coerce_ops_decisions_row(row)
                elif table == "ops_session_log":
                    row = _coerce_ops_session_log_row(row)
                rows.append(row)

        local_rel = _TABLE_TO_LOCAL.get(table)
        if local_rel:
            local_path = _LOGS_DIR / local_rel
            local_path.parent.mkdir(parents=True, exist_ok=True)
            with local_path.open("w", encoding="utf-8", newline="\n") as fh:
                for row in rows:
                    fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            if rejected_count:
                logger.warning(
                    "sync_ops._pull_single_table: rejected %d invalid rows for %s (see %s)",
                    rejected_count,
                    table,
                    _SYNC_REJECTS_LOG,
                )
            logger.info("sync_ops._pull_single_table: pulled %d rows for %s", len(rows), table)
            return len(rows)
        return 0

    except Exception as exc:  # noqa: BLE001
        logger.warning("sync_ops._pull_single_table: failed for %s: %s", table, exc)
        return 0


def _rebuild_local_cache(profile: str = _SSO_PROFILE) -> dict[str, int]:
    """Query Athena views and overwrite local JSONL files with fresh data.

    DESTRUCTIVE: overwrites local JSONL files with Athena state. If any S3 staging
    files for ops_recommendations exist today (unstaged writes), raises RuntimeError
    to prevent silent data loss. Call sync() first to compact pending writes.

    Requires valid SSO credentials. Returns empty dict if SSO is expired.

    Returns:
        Dict mapping table name to number of rows pulled.
    """
    counts: dict[str, int] = {}

    # Guard: refuse to overwrite if there are unstaged S3 writes for ops_recommendations
    try:
        import datetime as _dt  # noqa: PLC0415

        from scripts.ops_writer import STAGING_PREFIX, OpsWriter  # noqa: PLC0415

        _writer = OpsWriter()
        _bucket = _writer._bucket()
        if _bucket:
            _client = _writer._get_client()
            if _client:
                _today = _dt.date.today().isoformat()
                _prefix = f"{STAGING_PREFIX}/ops_recommendations/dt={_today}/"
                _paginator = _client.get_paginator("list_objects_v2")
                for _page in _paginator.paginate(Bucket=_bucket, Prefix=_prefix):
                    if _page.get("Contents"):
                        raise RuntimeError(
                            "_rebuild_local_cache: unstaged writes detected for ops_recommendations -- call sync() first"
                        )
    except RuntimeError:
        raise
    except Exception:  # noqa: BLE001
        pass  # staging guard failure is non-fatal

    if not check_sso(profile):
        logger.warning("sync_ops._rebuild_local_cache: SSO credentials not available -- skipping pull")
        return counts

    try:
        import boto3 as _boto3  # noqa: PLC0415

        session = _boto3.Session(profile_name=profile)
        athena = session.client("athena", region_name="eu-west-2")

        for table, view in _TABLE_TO_VIEW.items():
            try:
                query = f"SELECT * FROM {_DATABASE}.{view}"
                response = athena.start_query_execution(
                    QueryString=query,
                    WorkGroup=_WORKGROUP,
                )
                execution_id = response["QueryExecutionId"]

                for _ in range(60):
                    time.sleep(2)
                    status_resp = athena.get_query_execution(QueryExecutionId=execution_id)
                    state = status_resp["QueryExecution"]["Status"]["State"]
                    if state in ("SUCCEEDED", "FAILED", "CANCELLED"):
                        break

                if state != "SUCCEEDED":
                    reason = status_resp["QueryExecution"]["Status"].get("StateChangeReason", "unknown")
                    logger.warning("sync_ops._rebuild_local_cache: query for %s ended with state %s: %s", table, state, reason)
                    continue

                rows: list[dict] = []
                rejected_count = 0
                paginator = athena.get_paginator("get_query_results")
                header: list[str] = []
                is_first_page = True

                for page in paginator.paginate(QueryExecutionId=execution_id):
                    page_rows = page.get("ResultSet", {}).get("Rows", [])
                    for row_index, raw_row in enumerate(page_rows):
                        data = [col.get("VarCharValue", "") for col in raw_row.get("Data", [])]
                        if is_first_page and row_index == 0:
                            header = data
                            is_first_page = False
                            continue
                        if not header:
                            continue
                        row: dict = dict(zip(header, data))
                        row.pop("_rn", None)
                        row.pop("row_num", None)
                        if table == "ops_recommendations":
                            row = _coerce_ops_rec_row(row)  # type: ignore[assignment]
                            if row is None:
                                rejected_count += 1
                                continue
                            missing = [f for f in _REQUIRED_REC_FIELDS if not row.get(f) or not str(row[f]).strip()]
                            if missing:
                                _write_sync_reject(row, f"missing/empty required fields: {missing}")
                                rejected_count += 1
                                continue
                        elif table == "ops_priority_queue":
                            row = _coerce_ops_priority_queue_row(row)
                        elif table == "ops_decisions":
                            row = _coerce_ops_decisions_row(row)
                        elif table == "ops_session_log":
                            row = _coerce_ops_session_log_row(row)
                        rows.append(row)

                local_rel = _TABLE_TO_LOCAL.get(table)
                if local_rel:
                    local_path = _LOGS_DIR / local_rel
                    local_path.parent.mkdir(parents=True, exist_ok=True)
                    with local_path.open("w", encoding="utf-8", newline="\n") as fh:
                        for row in rows:
                            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                    counts[table] = len(rows)
                    if rejected_count:
                        logger.warning(
                            "sync_ops._rebuild_local_cache: rejected %d invalid rows for %s (see %s)",
                            rejected_count,
                            table,
                            _SYNC_REJECTS_LOG,
                        )
                    logger.info("sync_ops._rebuild_local_cache: pulled %d rows for %s", len(rows), table)

            except Exception as exc:  # noqa: BLE001
                logger.warning("sync_ops._rebuild_local_cache: failed for table %s: %s", table, exc)

    except Exception as exc:  # noqa: BLE001
        logger.warning("sync_ops._rebuild_local_cache: boto3 error: %s", exc)

    return counts


def sync(profile: str = _SSO_PROFILE) -> dict[str, dict[str, int]]:
    """Drain outbox then rebuild local cache from Athena.

    Drain runs first so any locally-queued entries reach S3 before pulling,
    ensuring the pulled view includes recently-drained data.

    Returns:
        {"drained": {table: count}, "pulled": {table: count}}
    """
    drain_result = drain()
    pull_result = _rebuild_local_cache(profile)
    return {"drained": drain_result, "pulled": pull_result}


def outbox_summary() -> dict[str, int]:
    """Count outbox files per table without draining.

    Returns:
        Dict mapping table name to file count. Empty dict if no outbox.
    """
    if not _OUTBOX_DIR.exists():
        return {}
    summary: dict[str, int] = {}
    try:
        for table_dir in _OUTBOX_DIR.iterdir():
            if not table_dir.is_dir():
                continue
            count = sum(1 for _ in table_dir.glob("*.jsonl"))
            if count:
                summary[table_dir.name] = count
    except Exception as exc:  # noqa: BLE001
        logger.warning("sync_ops.outbox_summary: error: %s", exc)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync ops Iceberg tables to local JSONL cache")
    parser.add_argument("command", choices=["sync"], help="Subcommand to run")
    parser.add_argument("--profile", default=_SSO_PROFILE, help=f"AWS SSO profile (default: {_SSO_PROFILE})")
    args = parser.parse_args()

    if args.command == "sync":
        result = sync(args.profile)
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
