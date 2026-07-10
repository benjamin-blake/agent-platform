"""Priority-queue concern for session_preflight."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

from scripts.preflight import _common


def _shape_priority_queue_rows(rows: list[dict], max_items: int) -> list[dict]:
    """Normalise rows into the {rank, rec_id, rationale, north_star_impact} shape, rank-sorted.

    Sort BEFORE slicing: with more rows than max_items, slice-then-sort presented an arbitrary
    subset as the top N (unparseable ranks sort last).
    """

    def _rank_key(row: dict) -> tuple:
        try:
            return (False, int(row.get("rank", 0)))
        except (ValueError, TypeError):
            return (True, 0)

    result = []
    for row in sorted(rows, key=_rank_key)[:max_items]:
        try:
            rank = int(row.get("rank", 0))
        except (ValueError, TypeError):
            rank = 0
        result.append(
            {
                "rank": rank,
                "rec_id": row.get("rec_id", ""),
                "rationale": row.get("rationale", ""),
                "north_star_impact": row.get("north_star_impact", ""),
            }
        )
    return result


def _read_priority_queue_cache(max_items: int) -> list[dict]:
    """Read priority-queue rows from the local read-cache (degraded-mode fallback).

    Returns [] (with a loud warning) when the cache file is absent. There is no
    in-repo producer for PRIORITY_QUEUE_FILE today, so in practice this commonly
    degrades to empty rather than restoring rows -- acceptable under Decision 60.
    READ-ONLY: it never restages or writes the cache (warehouse-as-source-of-truth;
    no resurrection loop).
    """
    if not _common.PRIORITY_QUEUE_FILE.exists():
        print(
            "[WARN] priority queue unavailable: credentials down and no local cache at "
            f"{_common.PRIORITY_QUEUE_FILE}; returning empty (sync after creds restored).",
            file=sys.stderr,
        )
        return []
    mtime = datetime.fromtimestamp(_common.PRIORITY_QUEUE_FILE.stat().st_mtime, tz=timezone.utc)
    print(
        f"[WARN] priority queue read from local cache (creds unavailable); may be stale as of "
        f"{mtime.isoformat()}; sync after creds restored.",
        file=sys.stderr,
    )
    rows: list[dict] = []
    for line in _common.PRIORITY_QUEUE_FILE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            rows.append(json.loads(stripped))
        except json.JSONDecodeError:
            continue
    return _shape_priority_queue_rows(rows, max_items)


def read_priority_queue(
    max_items: int = 5, creds_status: str = "ok", cache_rows: object = _common._READER_SENTINEL
) -> list[dict]:
    """Read the priority queue via the priority_queue_current read verb (DuckLake reader).

    Decision 70: the verb's correlated subquery returns ALL entries of the latest
    curator run -- the generic latest-per-key current projection would silently
    change these semantics.

    cache_rows (neon-egress-reduction D4): when supplied, the queue is served from the warm-up
    sync's already-pulled priority_queue_current rows (zero reader call) -- the local cache IS that
    verb's output, so no re-derivation is needed, only shaping. A supplied None means the warm-up
    pull FAILED: degrade to the local read-cache with a staleness warning (the warm-up sync already
    surfaced the reader failure loudly; preflight completes in degraded mode, Decision 60). When
    omitted (sentinel) the function uses the reader directly -- the back-compat path below.

    When *creds_status* is not "ok" credentials are unavailable: fall back to the
    local read-cache with a staleness warning (empty-with-warning when absent; never
    crash -- T2.5 graceful-degradation requirement).

    When credentials ARE "ok" and the verb fails, that is a genuine infrastructure
    fault -- hard-exit with code 1 rather than masking it (Decision 60).

    Returns a list of dicts shaped as {rank, rec_id, rationale, north_star_impact}.
    Returns [] if the queue is empty.
    """
    if cache_rows is not _common._READER_SENTINEL:
        if cache_rows is None:
            return _read_priority_queue_cache(max_items)
        shaped = _shape_priority_queue_rows(cache_rows, max_items)  # type: ignore[arg-type]
        shaped.sort(key=lambda r: (r.get("rank") is None, r.get("rank", 0)))
        return shaped

    if creds_status != "ok":
        return _read_priority_queue_cache(max_items)

    # Decision 70 semantics (all entries of the LATEST curator run) are preserved inside the
    # priority_queue_current verb's correlated subquery -- not by the generic current projection.
    try:
        reader_rows = _common._make_reader(table="ops_priority_queue").named("priority_queue_current")
        shaped = _shape_priority_queue_rows(reader_rows, max_items)
        shaped.sort(key=lambda r: (r.get("rank") is None, r.get("rank", 0)))
        return shaped
    except Exception as exc:  # noqa: BLE001
        print(
            f"[ERROR] priority_queue_current verb failed ({exc}) -- infrastructure problem, "
            "not masking with fallback (Decision 60)",
            file=sys.stderr,
        )
        sys.exit(1)


def print_priority_queue(items: list[dict]) -> None:
    """Print the priority queue section to terminal."""
    print("\n--- Priority Queue (top 5) ---")
    if not items:
        print("  (empty)")
    else:
        for item in items:
            rank = item.get("rank", 0)
            rec_id = item.get("rec_id", "unknown")
            impact = item.get("north_star_impact", "")
            rationale = item.get("rationale", "")
            print(f"  #{rank} {rec_id}: [impact={impact}] -- {rationale}")
    print()
