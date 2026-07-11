"""ops_decisions CRUD + DECISIONS.md ETL.

Owner-concern: filing/updating decision rows (numbering authority is DECISIONS.md; the
caller supplies decision_id, Decision 84 I-2 exception) and the idempotent backfill ETL
that rebuilds ops_decisions from DECISIONS.md. Preserves Decision 91 verb routing
(file_decision -> write_ops).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Optional

from scripts.executor.jsonl_store import DECISIONS_JSONL, Decision
from scripts.ops_portal.cache import _refresh_cache_after_write, _sanitize_athena_record, _sync_table
from scripts.ops_portal.write_validators import _load_write_time_validators
from scripts.ops_portal.writer_transport import _ducklake_write

logger = logging.getLogger(__name__)

# DECISIONS.md columns carried by the backfill ETL. Excludes id + decision_id (passed via
# _migration_int_id) and the timestamps (portal/runtime stamp them; the store is recreatable).
_DECISION_BACKFILL_COLS = ("title", "status", "problem", "decision_text", "context", "decided_date", "related_decisions")


def file_decision(
    fields: dict,
    profile: Optional[str] = None,
    _migration_int_id: Optional[int] = None,
    _skip_sync: bool = False,
) -> str:
    """File a decision row for a DECISIONS.md entry (numbering authority: DECISIONS.md).

    Decision 84 I-2 exception: decision numbers are human-assigned in DECISIONS.md before
    any write, so the caller supplies the integer number via fields['decision_id'] (the
    backfill path passes _migration_int_id). The id is formed as dec-{n:03d}. The write is
    a caller-keyed write_ops upsert, so re-running the backfill refreshes the same id
    rather than duplicating it.

    Returns:
        The decision ID string (e.g. 'dec-084'). Raises LOUDLY on any failure (no outbox).
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    merged = dict(fields)

    n = _migration_int_id if _migration_int_id is not None else merged.get("decision_id")
    if not isinstance(n, int) or n <= 0:
        raise ValueError(
            "file_decision requires the DECISIONS.md-assigned integer decision number "
            "(fields['decision_id'] or _migration_int_id): decisions are authored in "
            "DECISIONS.md FIRST (Decision 84 I-2 exception)"
        )

    dec_id = f"dec-{n:03d}"
    merged["id"] = dec_id
    merged["decision_id"] = n
    merged.setdefault("created_timestamp", now_iso)
    merged["last_updated_timestamp"] = now_iso

    for _col, _validator in _load_write_time_validators("ops_decisions"):
        _validator(merged.get(_col), _col)

    Decision.model_validate(merged)

    response = _ducklake_write("ops_decisions", merged, action="write_ops", profile=profile)
    logger.info("[PORTAL] Filed decision %s: %s", dec_id, merged.get("title", ""))
    _refresh_cache_after_write("ops_decisions", merged, response, DECISIONS_JSONL, append_only=_skip_sync)
    return dec_id


def _fetch_decision_from_reader(decision_id: str, profile: Optional[str] = None) -> Optional[dict]:
    """Fetch a single ops_decisions record by id via the decision_by_id read verb.

    Closed boundary (Decision 84 I-1/I-3): decisions read from DuckLake like every migrated
    ops table; the Athena fallback retired with the estate. Decision 69: raises on reader
    failure; never returns cache. Returns the coerced record dict or None if not found.
    """
    if not re.fullmatch(r"dec-\d+", decision_id):
        raise ValueError(f"_fetch_decision_from_reader: invalid decision_id: {decision_id!r}")

    from scripts.sync.ops import _coerce_ops_decisions_row  # noqa: PLC0415
    from src.common.iceberg_reader import make_reader  # noqa: PLC0415

    rows = make_reader(profile=profile).named("decision_by_id", id=decision_id)
    if not rows:
        return None
    rec = _coerce_ops_decisions_row(dict(rows[0]))
    return _sanitize_athena_record(rec) if rec is not None else None


# Back-compat alias: read-engine.yaml's single_portal_invariant names the historical symbol.
_fetch_decision_from_athena = _fetch_decision_from_reader


def update_decision(decision_id: str, updates: dict, profile: Optional[str] = None) -> bool:
    """Merge update fields into an existing decision via the DuckLake writer.

    Reads the current record through the decision_by_id verb, merges updates,
    validates, and writes via update_ops (in-transaction referential check).

    Args:
        decision_id: Decision ID string to update (e.g. 'dec-072').
        updates: Fields to merge into the existing record.
        profile: Optional AWS profile override.

    Returns:
        True on success.

    Raises:
        RuntimeError: If Athena is unreachable.
        ValidationError: If the merged record fails schema validation.
    """
    existing = _fetch_decision_from_reader(decision_id, profile=profile)
    if existing is None:
        raise RuntimeError(
            f"update_decision: {decision_id} does not exist in the current projection -- an absent decision "
            "cannot be updated (referential, CD.33 cl.8 / D-5). File it first via file_decision."
        )
    merged = {**existing, **updates}
    merged["id"] = decision_id

    Decision.model_validate(merged)

    response = _ducklake_write("ops_decisions", merged, action="update_ops", profile=profile)
    logger.info("[PORTAL] Updated %s: %s", decision_id, list(updates.keys()))
    _refresh_cache_after_write("ops_decisions", merged, response, DECISIONS_JSONL)
    return True


def backfill_decisions_from_md(profile: Optional[str] = None) -> dict:
    """ETL DECISIONS.md -> ops_decisions (premise P3: the markdown is the source of truth).

    Idempotent: each entry is a caller-keyed write_ops upsert on dec-{n:03d}, so re-running
    refreshes current rows (one SCD2 append per run) instead of duplicating.

    Returns:
        {"written": N, "failed": M, "skipped": K}
    """
    from scripts.decisions_md import parse_decisions_md  # noqa: PLC0415
    from scripts.sync.ops import _coerce_athena_array  # noqa: PLC0415

    written = failed = skipped = 0
    for entry in parse_decisions_md():
        try:
            n = int(str(entry.get("decision_id", "")).strip())
        except ValueError:
            n = 0
        if n <= 0:
            skipped += 1
            continue
        fields = {k: v for k, v in entry.items() if k in _DECISION_BACKFILL_COLS and v not in (None, "")}
        # Archive entries may carry no status marker; the column is non-nullable, so be honest.
        fields.setdefault("status", "unspecified")
        if "related_decisions" in fields:
            fields["related_decisions"] = _coerce_athena_array(fields["related_decisions"], elem_type=int)
        try:
            file_decision(fields, profile=profile, _migration_int_id=n, _skip_sync=True)
            written += 1
        except Exception as exc:  # noqa: BLE001 -- per-row isolation; the summary surfaces failures
            logger.warning("[PORTAL] backfill_decisions_from_md: dec-%03d failed: %s", n, exc)
            failed += 1
    if written:
        _sync_table("ops_decisions")
    return {"written": written, "failed": failed, "skipped": skipped}
