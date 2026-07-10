"""Open-recommendation tallies over the warm cache for session_preflight."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

from scripts.preflight import _common


def _derive_open_recs(rows: list[dict]) -> list[dict]:
    """Client-side `open_recs` verb: open rows projected to the tally columns, ordered by id."""
    open_rows = [
        {
            "id": r.get("id", ""),
            "title": r.get("title", ""),
            "context": r.get("context", ""),
            "created_timestamp": r.get("created_timestamp"),
            "automatable": r.get("automatable"),
        }
        for r in rows
        if r.get("status") == "open"
    ]
    return sorted(open_rows, key=lambda r: r.get("id") or "")


def _derive_decisions_max_updated(rows: list[dict]) -> list[dict]:
    """Client-side `decisions_max_updated` verb: [{ts: max(last_updated_timestamp)}] (mirrors the verb row)."""
    stamps = [_common._row_ts(r, "last_updated_timestamp") for r in rows]
    stamps = [s for s in stamps if s is not None]
    if not stamps:
        return [{"ts": None}]
    newest = max(stamps)
    # Echo the original string form when present (the verb returns the stored value, not a re-format).
    for r in rows:
        if _common._row_ts(r, "last_updated_timestamp") == newest:
            return [{"ts": r.get("last_updated_timestamp")}]
    return [{"ts": newest.isoformat()}]


def _tally_rec_counts(
    rows: list[dict],
    source: str = "reader",
) -> tuple[int, int, int, list[dict]]:
    """Compute (open_count, aging_count, non_auto_count, non_auto_details) from a row list."""
    now = datetime.now(timezone.utc)
    open_count = len(rows)
    aging_count = 0
    non_auto_count = 0
    non_auto_details: list[dict] = []

    for entry in rows:
        date_str = entry.get("created_timestamp", "")
        if date_str:
            try:
                if isinstance(date_str, str):
                    entry_date = datetime.fromisoformat(date_str.replace("Z", "+00:00")).replace(tzinfo=timezone.utc)
                else:
                    import datetime as _dt  # noqa: PLC0415

                    if hasattr(date_str, "timestamp"):
                        entry_date = _dt.datetime.fromtimestamp(date_str.timestamp(), tz=timezone.utc)
                    else:
                        entry_date = now
                if (now - entry_date).days > 30:
                    aging_count += 1
            except (ValueError, AttributeError, TypeError):
                pass
        # Reader rows carry native Python bools; rows migrated from the legacy Athena path may
        # still serialise booleans as the strings "true"/"false" -- normalise both forms.
        raw_auto = entry.get("automatable", True)
        if isinstance(raw_auto, bool):
            automatable = raw_auto
        else:
            automatable = str(raw_auto).lower() != "false"
        if not automatable:
            non_auto_count += 1
            if len(non_auto_details) < 10:
                context = entry.get("context", "")
                non_auto_details.append(
                    {
                        "id": entry.get("id", ""),
                        "title": entry.get("title", ""),
                        "context_excerpt": (context[:200] if isinstance(context, str) else ""),
                    }
                )

    return open_count, aging_count, non_auto_count, non_auto_details


def _count_recommendations_reader(cache_rows: object = _common._READER_SENTINEL) -> tuple[int, int, int, list[dict]] | str:
    """Return open recommendation counts -- from the warm-pulled cache rows, else the DuckLake reader.

    cache_rows (neon-egress-reduction D4): when supplied, the count is DERIVED from the warm-up sync's
    already-pulled rows (zero reader call). A supplied None means the warm-up recs pull FAILED ->
    "reader_unreachable" (Decision 55: loud degraded signal, never a false zero). When omitted
    (sentinel) the function falls back to its own reader call -- the back-compat path for standalone
    callers and tests.

    Returns the tally tuple on success, or the string "reader_unreachable" on reader failure.
    """
    if cache_rows is not _common._READER_SENTINEL:
        if cache_rows is None:
            return "reader_unreachable"
        return _tally_rec_counts(_derive_open_recs(cache_rows), source="cache")  # type: ignore[arg-type]

    try:
        rows = _common._make_reader().named("open_recs")
        return _tally_rec_counts(rows, source="reader")
    except Exception as exc:  # noqa: BLE001
        import logging as _log  # noqa: PLC0415

        _log.getLogger(__name__).warning("session_preflight._count_recommendations_reader: reader unreachable: %s", exc)

    return "reader_unreachable"


def count_recommendations() -> tuple[int, int, int, list[dict]]:
    """Count open, aging (>30 days), and non-automatable recommendations.

    Reads from the DuckLake reader first (Decision 81 cl.7 / T2.19 cutover); there is
    no Athena fallback. On reader failure, emits a LOUD reader_unreachable warning
    (Decision 55: never a silent false zero) and degrades to counting from the local
    read cache (S3 backend or logs/.recommendations-log.jsonl), which may be stale.

    Note: main() does not call this function -- it calls _count_recommendations_reader()
    directly and reports the sentinel (0,0,0,[]) plus recs_read_status=reader_unreachable
    on failure. This cache-counting fallback is retained for non-main consumers.
    """
    result = _count_recommendations_reader()
    if result != "reader_unreachable":
        print("  (recommendations sourced from DuckLake reader)")
        return result  # type: ignore[return-value]

    print(
        "[WARN] session_preflight: recs reader unreachable -- recs counts are DEGRADED "
        "(recs_read_status=reader_unreachable). Run `aws sts get-caller-identity --profile "
        "agent_platform` to verify credentials. The ops loop is impaired until the reader "
        "is reachable.",
        file=sys.stderr,
    )
    # Return sentinel -- callers must check recs_read_status in the report
    open_count = 0
    aging_count = 0
    non_auto_count = 0
    non_auto_details: list[dict] = []
    now = datetime.now(timezone.utc)
    try:
        if _common.get_backend() == "s3":
            entries = _common.read_jsonl(".recommendations-log.jsonl")
        elif not _common.RECOMMENDATIONS_FILE.exists():
            return 0, 0, 0, []
        else:
            entries = []
            for line in _common.RECOMMENDATIONS_FILE.read_text(encoding="utf-8").splitlines():
                if not line.strip() or line.startswith("#"):
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        for entry in entries:
            if entry.get("status", "").lower() != "open":
                continue
            open_count += 1
            date_str = entry.get("date", "")
            if date_str:
                try:
                    entry_date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                    if (now - entry_date).days > 30:
                        aging_count += 1
                except ValueError:
                    pass
            if not entry.get("automatable", True):
                non_auto_count += 1
                if len(non_auto_details) < 10:
                    context = entry.get("context", "")
                    non_auto_details.append(
                        {
                            "id": entry.get("id", ""),
                            "title": entry.get("title", ""),
                            "context_excerpt": context[:200] if context else "",
                        }
                    )
    except IOError:
        return 0, 0, 0, []

    return open_count, aging_count, non_auto_count, non_auto_details


def _check_non_automatable_softcap(non_auto_count: int) -> bool:
    """Return True when non-automatable rec count exceeds the soft cap."""
    return non_auto_count > _common._NON_AUTOMATABLE_SOFTCAP


def _get_latest_decision_ts(cache_rows: object = _common._READER_SENTINEL) -> str | None:
    """Return the max decision last_updated_timestamp -- from the warm-pulled rows, else the verb.

    cache_rows (neon-egress-reduction D4): a supplied row list is served via
    _derive_decisions_max_updated (zero reader call); a supplied None -> None. Omitted (sentinel) ->
    decisions_max_updated verb (back-compat / tests).
    """
    if cache_rows is not _common._READER_SENTINEL:
        if cache_rows is None:
            return None
        rows = _derive_decisions_max_updated(cache_rows)  # type: ignore[arg-type]
    else:
        try:
            rows = _common._make_reader(table="ops_decisions").named("decisions_max_updated")
        except Exception:  # noqa: BLE001
            return None
    if not rows:
        return None
    ts = rows[0].get("ts") or ""
    return str(ts) if ts else None
