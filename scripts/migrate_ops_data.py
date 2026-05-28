"""One-time migration of ops_recommendations + ops_decisions to the personal account.

Single Portal Invariant (Decision 69): this migration WRITES exclusively through
ops_data_portal.file_rec / file_decision -- never OpsWriter.write() directly. The READ
side is a plain, read-only Athena query against the SOURCE (work) account's *_current
views via its own boto3 session; reading a foreign warehouse is not a portal-write concern
(Decision 75). The migration NEVER reads any logs/ path as input.

Sequencing:
  - Run AFTER the Phase D constant flip has merged so ops_writer.DATABASE == "agent_platform"
    and the portal resolves to the personal account. A startup assertion enforces this.
  - Export AWS_PROFILE=agent_platform (or pass --profile-dest) for the DEST writes.
  - Supply the work SOURCE profile at runtime: --profile-source <work-profile>. The default
    below is the repo's redaction placeholder, NOT a real work identifier -- the real source
    profile name is deliberately kept out of this (public) repository.

ID preservation: rec-NNN / dec-NNN integer ids are preserved verbatim via the portal's private
_migration_int_id parameter (padded f"rec-{n:03d}" / f"dec-{n:03d}"), so dependency /
related_decisions / priority-queue foreign keys stay intact. Counters are then reseeded above
the migrated max (HARD gate, Decision 50) so a future allocation cannot re-issue a migrated id.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SUMMARY_PATH = _REPO_ROOT / "logs" / "debug" / "migration-summary.json"
_AWS_REGION = "eu-west-2"

# SOURCE (work account) Athena coordinates. _SOURCE_DATABASE is a public-safe work resource
# name kept committed; the migration legitimately reads the work warehouse through it.
_SOURCE_DATABASE = "trading_formulas_db"

# The real source workgroup and profile are supplied at runtime via --source-workgroup /
# --profile-source. These defaults are redaction placeholders ONLY and will not resolve to a
# live workgroup/profile on their own -- the real source workgroup is a scrubbed identifier
# deliberately kept out of this (public) repository.
_DEFAULT_SOURCE_WORKGROUP = "company-aws-workgroup"
_DEFAULT_SOURCE_PROFILE = "company-aws-profile"
_DEFAULT_DEST_PROFILE = "agent_platform"

_DEST_BUCKET = "agent-platform-data-lake"
_DEST_DATABASE = "agent_platform"
_COUNTER_TABLE = "agent-platform-counters"
_COUNTER_MARGIN = 1000

# OpsWriter's un-bypassable backstop raises on any empty value in this set. The migration
# pre-validates each source row against it and skips+reports unmigratable rows rather than
# letting the write abort mid-stream (after which the idempotency guard would block re-run).
_REQUIRED_REC_FIELDS = ["title", "source", "effort", "priority", "file", "context", "acceptance"]
_VALID_REC_STATUSES = {"open", "closed", "failed", "declined", "superseded"}

# Recognised Recommendation columns passed to file_rec. Excludes id (supplied via
# _migration_int_id) and last_updated_timestamp (portal stamps it = import time).
_REC_PASS_FIELDS = [
    "title",
    "source",
    "effort",
    "priority",
    "status",
    "automatable",
    "risk",
    "file",
    "context",
    "acceptance",
    "verification",
    "verification_tier",
    "dependencies",
    "tags",
    "resolution",
    "execution_result",
    "execution_date",
    "execution_branch",
    "execution_pr_url",
    "execution_steps",
    "created_timestamp",
]

# Recognised Decision columns passed to file_decision. Excludes id + decision_id (both
# derived from _migration_int_id; passing decision_id risks the dual-write invariant) and
# last_updated_timestamp (portal stamps it).
_DEC_PASS_FIELDS = [
    "title",
    "status",
    "created_timestamp",
    "problem",
    "decision_text",
    "context",
    "decided_date",
    "related_decisions",
    "related_decisions_v2",
]


def _athena_rows(session, query: str, workgroup: str) -> list[dict]:
    """Run an Athena query and return result rows as list[dict] (header -> VarChar value).

    Raises RuntimeError on timeout or non-SUCCEEDED terminal state.
    """
    athena = session.client("athena", region_name=_AWS_REGION)
    eid = athena.start_query_execution(QueryString=query, WorkGroup=workgroup)["QueryExecutionId"]

    deadline = time.time() + 120
    state = "RUNNING"
    status: dict = {}
    while time.time() < deadline:
        status = athena.get_query_execution(QueryExecutionId=eid)["QueryExecution"]["Status"]
        state = status["State"]
        if state in ("SUCCEEDED", "FAILED", "CANCELLED"):
            break
        time.sleep(2)
    else:
        raise RuntimeError(f"Athena query timed out: {query[:80]}")

    if state != "SUCCEEDED":
        raise RuntimeError(f"Athena query {state}: {status.get('StateChangeReason', 'unknown')} | {query[:80]}")

    rows: list[dict] = []
    header: list[str] = []
    paginator = athena.get_paginator("get_query_results")
    for page in paginator.paginate(QueryExecutionId=eid):
        for row in page.get("ResultSet", {}).get("Rows", []):
            data = [col.get("VarCharValue", "") for col in row.get("Data", [])]
            if not header:
                header = data
                continue
            rows.append(dict(zip(header, data)))
    return rows


def _rec_int(rec_id: str) -> Optional[int]:
    """Return the integer of a rec-NNN id, or None if not a plain rec-\\d+ id."""
    if not isinstance(rec_id, str):
        return None
    if not rec_id.startswith("rec-"):
        return None
    try:
        return int(rec_id.split("-", 1)[1])
    except (ValueError, IndexError):
        return None


def _none_if_blank(value: object) -> object:
    """Athena serialises NULL as ''. Convert blank scalars to None; leave lists/bools/ints."""
    if isinstance(value, str) and not value.strip():
        return None
    return value


def _build_rec_fields(coerced: dict) -> dict:
    """Select recognised Recommendation columns from a coerced source row.

    Blank scalars become None. id and last_updated_timestamp are intentionally omitted.
    """
    fields: dict = {}
    for key in _REC_PASS_FIELDS:
        if key in coerced:
            fields[key] = _none_if_blank(coerced[key])
    return fields


def _build_decision_fields(coerced: dict) -> tuple[dict, Optional[int]]:
    """Return (fields, migration_int_id) for a coerced source decision row.

    A falsy created_timestamp key is DROPPED (not set to None) so file_decision's
    setdefault stamps it -- Decision.created_timestamp is a required str and setdefault
    will not replace an explicit None.
    """
    migration_int = coerced.get("decision_id")
    if not isinstance(migration_int, int):
        migration_int = _rec_int(str(coerced.get("id", "")).replace("dec-", "rec-"))
    fields: dict = {}
    for key in _DEC_PASS_FIELDS:
        if key in coerced:
            fields[key] = _none_if_blank(coerced[key])
    if not fields.get("created_timestamp"):
        fields.pop("created_timestamp", None)
    return fields, migration_int


def _pre_validate_rec(fields: dict) -> Optional[str]:
    """Return a skip-reason string if the rec is unmigratable, else None.

    Covers OpsWriter's un-bypassable required-field backstop plus status-domain (which
    Recommendation.model_validate enforces and _migration_mode does NOT bypass).
    """
    for req in _REQUIRED_REC_FIELDS:
        val = fields.get(req)
        if val is None or not str(val).strip():
            return f"missing required field '{req}'"
    status = fields.get("status")
    if status not in _VALID_REC_STATUSES:
        return f"invalid status {status!r}"
    return None


def _registered_sources() -> set[str]:
    from scripts.executor.rec_write_guidance import load_source_registry  # noqa: PLC0415

    return {e["canonical_id"] for e in load_source_registry()}


def _reconcile_sources(source_values: set[str]) -> list[str]:
    """Return source values present in the data but absent from the registry."""
    registered = _registered_sources()
    return sorted(v for v in source_values if v and v not in registered)


def _read_counter(session, name: str) -> Optional[int]:
    ddb = session.client("dynamodb", region_name=_AWS_REGION)
    item = ddb.get_item(TableName=_COUNTER_TABLE, Key={"counter_name": {"S": name}}).get("Item")
    if not item:
        return None
    return int(item["current_value"]["N"])


def _write_summary(summary: dict) -> None:
    _SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    _SUMMARY_PATH.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Wrote migration summary -> %s", _SUMMARY_PATH)


def _dry_run_skip_accounting(coerced_recs: list[dict], summary: dict) -> None:
    """Populate summary['skipped_invalid'] for a dry-run so the reported expected count is honest."""
    for row in coerced_recs:
        rid = _rec_int(str(row.get("id", "")))
        if rid is None:
            summary["skipped_invalid"].append({"id": row.get("id"), "reason": "non rec-NNN id"})
            continue
        reason = _pre_validate_rec(_build_rec_fields(row))
        if reason:
            summary["skipped_invalid"].append({"id": row.get("id"), "reason": reason})


def _write_recs(coerced_recs: list[dict], existing_rec_ids: set[str], file_rec, summary: dict) -> tuple[int, list[str], bool]:
    """Write recommendations via the portal. Returns (max_int, imported_ids, aborted)."""
    max_rec_int = 0
    imported: list[str] = []
    for row in coerced_recs:
        rid = _rec_int(str(row.get("id", "")))
        if rid is None:
            summary["skipped_invalid"].append({"id": row.get("id"), "reason": "non rec-NNN id"})
            continue
        if f"rec-{rid:03d}" in existing_rec_ids:
            continue
        fields = _build_rec_fields(row)
        reason = _pre_validate_rec(fields)
        if reason:
            summary["skipped_invalid"].append({"id": row.get("id"), "reason": reason})
            continue
        result = file_rec(fields, _migration_int_id=rid, _skip_sync=True, _migration_mode=True)
        if str(result).startswith("pending-"):
            logger.error("file_rec returned outbox sentinel %s for source id %s -- aborting.", result, row.get("id"))
            summary["failed_recs"] = summary.get("failed_recs", []) + [{"id": row.get("id"), "result": result}]
            return max_rec_int, imported, True
        summary["imported_recs"] += 1
        max_rec_int = max(max_rec_int, rid)
        imported.append(f"rec-{rid:03d}")
    return max_rec_int, imported, False


def _write_decisions(coerced_decs: list[dict], existing_dec_ids: set[str], file_decision, summary: dict) -> tuple[int, bool]:
    """Write decisions via the portal. Returns (max_int, aborted)."""
    max_dec_int = 0
    for row in coerced_decs:
        fields, dec_int = _build_decision_fields(row)
        if dec_int is None:
            summary["failed_decisions"].append({"id": row.get("id"), "reason": "no decision_id"})
            continue
        if f"dec-{dec_int:03d}" in existing_dec_ids:
            max_dec_int = max(max_dec_int, dec_int)
            continue
        try:
            result = file_decision(fields, _migration_int_id=dec_int, _skip_sync=True)
        except Exception as exc:  # noqa: BLE001
            logger.error("file_decision failed for dec-%03d: %s", dec_int, exc)
            summary["failed_decisions"].append({"id": f"dec-{dec_int:03d}", "reason": str(exc)})
            continue
        if str(result).startswith("pending-"):
            logger.error("file_decision returned outbox sentinel %s for dec-%03d -- aborting.", result, dec_int)
            summary["failed_decisions"].append({"id": f"dec-{dec_int:03d}", "result": result})
            return max_dec_int, True
        summary["imported_decisions"] += 1
        max_dec_int = max(max_dec_int, dec_int)
    return max_dec_int, False


def _verify_migration(
    summary: dict,
    dest_session,
    coerced_recs: list[dict],
    imported_rec_ids: list[str],
    workgroup: str,
) -> bool:
    """Re-query dest counts, assert against source, and spot-check a sample. Returns ok."""
    rec_count_sql = f"SELECT count(*) AS n FROM {_DEST_DATABASE}.ops_recommendations_current"
    dec_count_sql = f"SELECT count(*) AS n FROM {_DEST_DATABASE}.ops_decisions_current"
    summary["dest_recs"] = int(_athena_rows(dest_session, rec_count_sql, workgroup)[0]["n"])
    summary["dest_decisions"] = int(_athena_rows(dest_session, dec_count_sql, workgroup)[0]["n"])
    expected_recs = summary["source_recs"] - len(summary["skipped_invalid"])
    ok = True
    if summary["dest_recs"] != expected_recs:
        logger.error("Rec count mismatch: dest=%d expected=%d (source - skipped_invalid)", summary["dest_recs"], expected_recs)
        ok = False
    if summary["dest_decisions"] != summary["source_decisions"]:
        logger.error("Decision count mismatch: dest=%d source=%d", summary["dest_decisions"], summary["source_decisions"])
        ok = False
    if summary["failed_decisions"]:
        logger.error("%d decision(s) failed to migrate: %s", len(summary["failed_decisions"]), summary["failed_decisions"])
        ok = False

    # Content spot-check: sample a handful of IMPORTED ids and diff title/source/created_timestamp.
    sample_ids = imported_rec_ids[:5]
    if not sample_ids:
        return ok
    src_by_id = {
        f"rec-{_rec_int(str(r.get('id', ''))):03d}": r for r in coerced_recs if _rec_int(str(r.get("id", ""))) is not None
    }
    in_list = ", ".join(f"'{i}'" for i in sample_ids)
    dest_sample = {
        r["id"]: r
        for r in _athena_rows(
            dest_session,
            f"SELECT id, title, source, created_timestamp FROM {_DEST_DATABASE}.ops_recommendations_current "
            f"WHERE id IN ({in_list})",
            workgroup,
        )
    }
    for sid in sample_ids:
        s = src_by_id.get(sid, {})
        d = dest_sample.get(sid, {})
        for col in ("title", "source", "created_timestamp"):
            if str(s.get(col) or "") != str(d.get(col) or ""):
                logger.error("Content mismatch on %s.%s: source=%r dest=%r", sid, col, s.get(col), d.get(col))
                ok = False
    return ok


def migrate(
    profile_source: str,
    profile_dest: str,
    source_workgroup: str,
    dry_run: bool,
    force_skip_existing: bool,
) -> int:
    """Execute (or dry-run) the ops migration. Returns a process exit code."""
    import boto3  # noqa: PLC0415

    from scripts.sync_ops import _coerce_ops_decisions_row, _coerce_ops_rec_row  # noqa: PLC0415

    # DEST resolution is constant + env driven (Decision 69): the portal reads the personal
    # account from the FLIPPED module constants and AWS_PROFILE. Set both explicitly.
    os.environ["AWS_PROFILE"] = profile_dest
    os.environ["S3_LOG_BUCKET"] = _DEST_BUCKET

    # Startup assertions -- fail fast before any write.
    import scripts.ops_writer as ow  # noqa: PLC0415

    assert ow.DATABASE == _DEST_DATABASE, (
        f"ops_writer.DATABASE is {ow.DATABASE!r}, expected {_DEST_DATABASE!r}. "
        "Run this migration only AFTER the Phase D constant flip has landed."
    )
    assert ow.OpsWriter()._bucket() == _DEST_BUCKET, (
        f"OpsWriter._bucket() resolved {ow.OpsWriter()._bucket()!r}, expected {_DEST_BUCKET!r}."
    )

    source_session = boto3.Session(profile_name=profile_source)
    summary: dict = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "dry_run": dry_run,
        "source_recs": 0,
        "source_decisions": 0,
        "dest_recs": None,
        "dest_decisions": None,
        "imported_recs": 0,
        "imported_decisions": 0,
        "skipped_invalid": [],
        "failed_decisions": [],
    }

    # --- READ SOURCE (read-only foreign-warehouse query) ---
    logger.info("Reading source recommendations from %s.ops_recommendations_current ...", _SOURCE_DATABASE)
    raw_recs = _athena_rows(
        source_session,
        f"SELECT * FROM {_SOURCE_DATABASE}.ops_recommendations_current",
        source_workgroup,
    )
    logger.info("Reading source decisions from %s.ops_decisions_current ...", _SOURCE_DATABASE)
    raw_decs = _athena_rows(
        source_session,
        f"SELECT * FROM {_SOURCE_DATABASE}.ops_decisions_current",
        source_workgroup,
    )
    summary["source_recs"] = len(raw_recs)
    summary["source_decisions"] = len(raw_decs)

    coerced_recs = [r for r in (_coerce_ops_rec_row(dict(row)) for row in raw_recs) if r is not None]
    coerced_decs = [_coerce_ops_decisions_row(dict(row)) for row in raw_decs]

    # --- SOURCE-REGISTRY RECONCILIATION (before any write; also in dry-run) ---
    strays = _reconcile_sources({str(r.get("source") or "") for r in coerced_recs})
    if strays:
        logger.error(
            "Unregistered source value(s) in migration data: %s. Register them in "
            "config/agent/data_quality/source_registry.yaml (legacy entries) before migrating.",
            strays,
        )
        summary["unregistered_sources"] = strays
        _write_summary(summary)
        return 1

    if dry_run:
        _dry_run_skip_accounting(coerced_recs, summary)
        logger.info(
            "DRY RUN: source_recs=%d source_decisions=%d would_skip=%d (0 writes)",
            summary["source_recs"],
            summary["source_decisions"],
            len(summary["skipped_invalid"]),
        )
        _write_summary(summary)
        return 0

    # --- IDEMPOTENCY GUARD (first thing on the dest) ---
    dest_session = boto3.Session(profile_name=profile_dest)
    dest_recs_before = int(
        _athena_rows(
            dest_session, f"SELECT count(*) AS n FROM {_DEST_DATABASE}.ops_recommendations_current", ow.ATHENA_WORKGROUP
        )[0]["n"]
    )
    dest_decs_before = int(
        _athena_rows(dest_session, f"SELECT count(*) AS n FROM {_DEST_DATABASE}.ops_decisions_current", ow.ATHENA_WORKGROUP)[
            0
        ]["n"]
    )
    existing_rec_ids: set[str] = set()
    existing_dec_ids: set[str] = set()
    if dest_recs_before or dest_decs_before:
        if not force_skip_existing:
            logger.error(
                "Destination already populated (recs=%d decisions=%d) -- aborting to avoid duplicate "
                "appends / SCD2 resurrection. Pass --force-skip-existing to resume a partial migration.",
                dest_recs_before,
                dest_decs_before,
            )
            summary["dest_recs"] = dest_recs_before
            summary["dest_decisions"] = dest_decs_before
            _write_summary(summary)
            return 1
        existing_rec_ids = {
            r["id"]
            for r in _athena_rows(
                dest_session, f"SELECT id FROM {_DEST_DATABASE}.ops_recommendations_current", ow.ATHENA_WORKGROUP
            )
        }
        existing_dec_ids = {
            r["id"]
            for r in _athena_rows(dest_session, f"SELECT id FROM {_DEST_DATABASE}.ops_decisions_current", ow.ATHENA_WORKGROUP)
        }

    from scripts.ops_data_portal import file_decision, file_rec, sync  # noqa: PLC0415

    # --- WRITE via the portal (per-row sync suppressed; one flush at the end) ---
    max_rec_int, imported_rec_ids, aborted = _write_recs(coerced_recs, existing_rec_ids, file_rec, summary)
    if aborted:
        _write_summary(summary)
        return 1
    max_dec_int, aborted = _write_decisions(coerced_decs, existing_dec_ids, file_decision, summary)
    if aborted:
        _write_summary(summary)
        return 1

    logger.info("Flushing via ops_data_portal.sync() ...")
    sync()

    # --- COUNTER RESEED (HARD gate, Decision 50): monotonic, above migrated max ---
    from scripts.sync_recommendations import reseed_decisions_counter, reseed_recommendations_counter  # noqa: PLC0415

    rec_target = max_rec_int + _COUNTER_MARGIN
    dec_target = max_dec_int + _COUNTER_MARGIN
    reseed_recommendations_counter(rec_target, profile=profile_dest)
    reseed_decisions_counter(dec_target, profile=profile_dest)
    rec_counter = _read_counter(dest_session, "recommendations")
    dec_counter = _read_counter(dest_session, "decisions")
    summary["counters"] = {"recommendations": rec_counter, "decisions": dec_counter}
    assert rec_counter is not None and rec_counter >= rec_target, (
        f"recommendations counter {rec_counter} < migrated max + margin {rec_target}"
    )
    assert dec_counter is not None and dec_counter >= dec_target, (
        f"decisions counter {dec_counter} < migrated max + margin {dec_target}"
    )

    # --- POST-WRITE VERIFICATION via LIVE dest views ---
    ok = _verify_migration(summary, dest_session, coerced_recs, imported_rec_ids, ow.ATHENA_WORKGROUP)
    _write_summary(summary)

    logger.info(
        "Migration complete: recs %d/%d (skipped %d), decisions %d/%d. dest_recs=%s dest_decisions=%s",
        summary["imported_recs"],
        summary["source_recs"],
        len(summary["skipped_invalid"]),
        summary["imported_decisions"],
        summary["source_decisions"],
        summary["dest_recs"],
        summary["dest_decisions"],
    )
    return 0 if ok else 1


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="One-time ops_recommendations + ops_decisions migration (Phase C).")
    parser.add_argument(
        "--dry-run", action="store_true", help="Report source counts and write the summary JSON; perform zero writes."
    )
    parser.add_argument(
        "--profile-source",
        default=_DEFAULT_SOURCE_PROFILE,
        help="AWS profile for the SOURCE (work) account read. Pass the real work profile at runtime.",
    )
    parser.add_argument(
        "--source-workgroup",
        default=_DEFAULT_SOURCE_WORKGROUP,
        help="Athena workgroup for the SOURCE (work) account read. Pass the real work workgroup at runtime.",
    )
    parser.add_argument(
        "--profile-dest", default=_DEFAULT_DEST_PROFILE, help="AWS profile for the DEST (personal) account writes."
    )
    parser.add_argument(
        "--force-skip-existing",
        action="store_true",
        help="Resume a partial migration: skip ids already present in the destination.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        return migrate(
            profile_source=args.profile_source,
            profile_dest=args.profile_dest,
            source_workgroup=args.source_workgroup,
            dry_run=args.dry_run,
            force_skip_existing=args.force_skip_existing,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Migration aborted: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
