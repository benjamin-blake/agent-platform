"""Non-CRUD portal operations (CLI-driven): selftests, bulk-enqueue, and postmortem maintenance.

Owner-concern: operational verbs that support the rec/decision CRUD in the facade and
decisions.py but are not themselves CRUD. purge_postmortems_for stays a private surface
(Decision 70: no public delete_rec is introduced).
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

from pydantic import ValidationError

from scripts.executor.jsonl_store import RECS_JSONL, Recommendation
from scripts.ops_portal.writer_transport import _ducklake_write

logger = logging.getLogger(__name__)


def selftest_read(table: str = "ops_recommendations", profile: Optional[str] = None) -> dict:
    """Read a sample row from *table* via the ACTIVE backend's reader (VP14 rollback rehearsal).

    Proves the DuckLake read path serves rows (the boundary is the sole backend, Decision 84).
    Returns {"backend": ..., "table": ..., "row_count": ..., "sample_id": ...}.
    """
    from src.common.iceberg_reader import make_reader  # noqa: PLC0415

    backend = "ducklake"
    rows = make_reader(profile=profile).current_state(table) or []
    sample_id = (rows[0].get("id") if rows else None) if rows else None
    return {"backend": backend, "table": table, "row_count": len(rows), "sample_id": sample_id}


def selftest_roundtrip(profile: Optional[str] = None) -> dict:
    """Write a file_rec-shaped throwaway rec via the active backend, then read it back (VP15 sign-off).

    Uses a `test-roundtrip-<uuid>` id (valid `test-` prefix; not a DynamoDB-allocated rec-NNN, so the
    live counter is untouched) so the proof does not consume a production ID. On DuckLake the write
    transits the writer Function URL and the read transits the reader -- the closed-boundary proof.
    """
    from src.common.iceberg_reader import make_reader  # noqa: PLC0415

    backend = "ducklake"
    probe_id = f"test-roundtrip-{uuid.uuid4().hex[:12]}"
    now_iso = datetime.now(timezone.utc).isoformat()
    record = {
        "id": probe_id,
        "title": "ducklake cutover selftest-roundtrip",
        "source": "manual",
        "status": "open",
        "effort": "XS",
        "priority": "Low",
        "risk": "low",
        # DQ-required NOT-NULL column (rec-2114): populated so the probe row is data-quality-clean
        # while it persists, matching the ops_read_your_write probe's convention.
        "automatable": False,
        "file": "scripts/ops_data_portal.py",
        "context": (
            "Selftest roundtrip probe written by --selftest-roundtrip to prove the active backend's "
            "write+read path end-to-end at cutover sign-off (VP15). Safe to ignore/purge."
        ),
        "acceptance": "grep -q selftest-roundtrip logs/.recommendations-log.jsonl",
        "created_timestamp": now_iso,
        "last_updated_timestamp": now_iso,
    }
    Recommendation.model_validate(record)

    # ops_recommendations always routes to DuckLake (Decision 81 cl.7 / T2.19).
    _ducklake_write("ops_recommendations", record, action="write_ops", profile=profile)

    rows = make_reader(profile=profile).current_state("ops_recommendations", row_filter=f"id = '{probe_id}'") or []
    read_back = bool(rows) and rows[0].get("id") == probe_id
    if not read_back:
        raise RuntimeError(f"selftest_roundtrip FAIL ({backend}): wrote {probe_id} but read-back returned {len(rows)} rows")

    # SCD2 supersede via the writer on the caller-keyed test- keyspace (Decision 84 I-2 sanctioned
    # exception; Decision 103/81). NOT via update_rec: its _fetch_rec_from_reader helper only
    # accepts writer-allocated rec-NNN ids, and this is a caller-keyed test- probe id.
    superseded_record = {
        **record,
        "status": "superseded",
        "resolution": "Superseded by --selftest-roundtrip on successful read-back.",
    }
    _ducklake_write("ops_recommendations", superseded_record, action="update_ops", profile=profile)
    return {"backend": backend, "probe_id": probe_id, "read_back": True, "superseded": True}


def enqueue_findings(path: Path, profile: Optional[str] = None) -> dict:
    """Bulk-enqueue findings from a JSONL file into the ops_recommendations portal.

    Reads one finding per line. Blank lines and lines starting with '#' are skipped.
    Schema-invalid entries are counted as invalid, not raised. Per-line JSON parse
    errors are counted as skipped. Missing or empty input file returns zeros without raising.

    Args:
        path: Path to a JSONL file; each line is a dict of Recommendation fields.
        profile: Optional AWS profile override (passed through to file_rec).

    Returns:
        dict with keys: enqueued (int), invalid (int), skipped (int).
    """
    from scripts.ops_data_portal import file_rec  # noqa: PLC0415

    enqueued = 0
    invalid = 0
    skipped = 0

    if not path.exists() or path.stat().st_size == 0:
        return {"enqueued": 0, "invalid": 0, "skipped": 0}

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            skipped += 1
            continue
        # Pre-validate schema so invalid entries are caught even on the offline path
        # (file_rec skips Pydantic validation when DynamoDB is unreachable)
        try:
            probe = dict(entry)
            probe.setdefault("id", "test-0")  # satisfies rec-/agent-/test- prefix rule
            probe.setdefault("date", date.today().isoformat())
            Recommendation.model_validate(probe)
        except ValidationError:
            invalid += 1
            continue
        try:
            file_rec(entry, profile=profile)
            enqueued += 1
        except ValidationError:
            invalid += 1
        except OSError:
            skipped += 1

    return {"enqueued": enqueued, "invalid": invalid, "skipped": skipped}


def find_open_postmortem_for(failed_rec_id: str) -> Optional[dict]:
    """Return the first open executor-postmortem for failed_rec_id from local JSONL, or None.

    Uses last-wins JSONL semantics (builds a dict keyed by rec ID) then filters
    for source == "executor-postmortem", status == "open", and title containing
    failed_rec_id. Pure function; no side effects.
    """
    try:
        lines = RECS_JSONL.read_text(encoding="utf-8").splitlines()
    except (FileNotFoundError, OSError):
        return None
    by_id: dict = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            entry = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        rec_id = entry.get("id")
        if rec_id:
            by_id[rec_id] = entry
    for rec in by_id.values():
        if (
            rec.get("source") == "executor-postmortem"
            and rec.get("status") == "open"
            and failed_rec_id in rec.get("title", "")
        ):
            return rec
    return None


def purge_postmortems_for(failed_rec_id: str, dry_run: bool = False, profile: Optional[str] = None) -> dict:
    """Supersede all executor postmortems for failed_rec_id and decline the rec itself.

    SCD2 deletion model (Decision 84): postmortems become status=superseded via update_rec --
    no DML DELETE, no local-JSONL rewrite. The cache refresh after each update reflects the
    new current rows; history retains the full audit trail.

    Returns:
        {"matched": [rec ids], "superseded": N}
    """
    from scripts.ops_data_portal import update_rec  # noqa: PLC0415

    if not re.fullmatch(r"rec-\d+", failed_rec_id):
        raise ValueError(f"Invalid rec ID for purge: {failed_rec_id!r}. Must match rec-\\d+.")

    from src.common.iceberg_reader import make_reader  # noqa: PLC0415

    title_prefix = f"Investigate executor failure for {failed_rec_id}"
    rows = make_reader(profile=profile).named("recs_by_title_prefix", title_prefix=f"{title_prefix}%")
    id_re = re.compile(rf"Investigate executor failure for {re.escape(failed_rec_id)}(?![0-9])")
    matched = [
        r["id"]
        for r in rows
        if r.get("source") == "executor-postmortem"
        and r.get("status") != "superseded"
        and id_re.match(r.get("title", ""))  # LIKE 'rec-1%' also matches rec-10/rec-1NN -- re-filter exactly
    ]
    result: dict = {"matched": matched, "superseded": 0}

    if dry_run:
        logger.info("[PURGE] Dry-run for %s: %d postmortems would be superseded.", failed_rec_id, len(matched))
        return result

    for rec_id in matched:
        update_rec(
            rec_id,
            {
                "status": "superseded",
                "resolution": f"Superseded via ops_data_portal --purge-postmortems-for {failed_rec_id}.",
            },
            profile=profile,
        )
        result["superseded"] += 1

    resolution = (
        f"SCP block prevents IAM/OIDC operations required by {failed_rec_id}. "
        "Executor postmortems superseded via ops_data_portal --purge-postmortems-for."
    )
    update_rec(failed_rec_id, {"status": "declined", "resolution": resolution}, profile=profile)

    logger.info("[PURGE] Complete for %s: %d postmortems superseded.", failed_rec_id, result["superseded"])
    return result
