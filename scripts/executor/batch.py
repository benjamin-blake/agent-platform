"""Batch and compound orchestration for the recommendation executor.

Extracted from scripts/execute_recommendation.py (Strangler Fig pattern).
All functions remain importable from the original module via re-exports.

Thin facade (Decision 104/80 mechanism): compound-branch execution
(load_cluster, _ensure_compound_branch, execute_compound) lives in
scripts.executor.batch_compound and is re-exported here. ``os`` and
``subprocess`` stay imported at module scope even though this facade's
own remaining code does not call them directly -- they are the anchor
attributes that batch_compound's ``_ba.os`` / ``_ba.subprocess`` routing
resolves through, and ``subprocess`` is a direct test-patch target
(``scripts.executor.batch.subprocess.run``).
"""

from __future__ import annotations

import graphlib
import logging
import os  # noqa: F401  (anchor for batch_compound's _ba.os routing)
import subprocess  # noqa: F401  (anchor for batch_compound's _ba.subprocess routing; direct patch target)

from scripts.executor.batch_compound import (  # noqa: F401  (facade re-export)
    _ensure_compound_branch,
    execute_compound,
    load_cluster,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EFFORT_WEIGHTS: dict[str, float] = {"XS": 0.5, "S": 1.0, "M": 2.0, "L": 4.0, "XL": 8.0}
EFFORT_ORDER: dict[str, int] = {"XS": 0, "S": 1, "M": 2, "L": 3, "XL": 4}
PRIORITY_ORDER: dict[str, int] = {
    "Critical": 0,
    "High": 1,
    "Medium": 2,
    "Low": 3,
}
MAX_BATCH_EFFORT: float = 2.0  # equivalent to M
MAX_BATCH_SIZE: int = 4
DEFAULT_NEXT_BATCH_LIMIT: int = 3


# ---------------------------------------------------------------------------
# Batch selection
# ---------------------------------------------------------------------------


def select_compound_batch(recs: list[dict]) -> list[dict]:
    """Select recs for compound execution (total effort <= M, max 4 recs).

    Prefers recs with lower effort to maximise batch size.
    Prefer same-file recs to reduce merge conflicts (sort by primary file secondarily).
    """
    eligible = [r for r in recs if r.get("automatable", True) and r.get("status", "open") == "open"]
    eligible.sort(
        key=lambda r: (
            EFFORT_WEIGHTS.get(r.get("effort", "M"), 2.0),
            r.get("file", ""),
        )
    )

    batch: list[dict] = []
    total_effort = 0.0
    for rec in eligible:
        effort = EFFORT_WEIGHTS.get(rec.get("effort", "M"), 2.0)
        if total_effort + effort <= MAX_BATCH_EFFORT and len(batch) < MAX_BATCH_SIZE:
            batch.append(rec)
            total_effort += effort
        if total_effort >= MAX_BATCH_EFFORT or len(batch) >= MAX_BATCH_SIZE:
            break
    return batch


def get_eligible_recs() -> list[dict]:
    """Return all eligible recommendations in their JSONL order."""
    from scripts.execute_recommendation import is_eligible  # noqa: PLC0415
    from scripts.executor.jsonl_store import load_all_recommendations  # noqa: PLC0415

    recs_by_id = load_all_recommendations()
    return [rec for rec in recs_by_id.values() if is_eligible(rec, recs_by_id)]


def select_next_batch(
    limit: int = DEFAULT_NEXT_BATCH_LIMIT,
) -> dict:
    """Select the next batch of recs for the supervisor prompt.

    Applies the standard eligibility filter (status open, automatable,
    risk low, dependencies closed) then sorts by priority (Critical
    first) and effort (XS first).  Recs that are open but blocked by
    unclosed dependencies appear in the ``skipped`` list with a reason.

    Args:
        limit: Maximum number of recommended rec IDs to return.

    Returns:
        ``{"recommended": [...ids], "skipped": [...{id, reason}]}``
    """
    from scripts.executor.jsonl_store import load_all_recommendations  # noqa: PLC0415

    recs_by_id = load_all_recommendations()

    recommended: list[dict] = []
    skipped: list[dict] = []

    for rec in recs_by_id.values():
        if rec.get("status") != "open":
            continue
        if not rec.get("automatable", False):
            continue
        if rec.get("risk") != "low":
            continue

        # Check dependency blocking
        deps: list[str] = rec.get("dependencies", [])
        blocked_by: list[str] = []
        for dep_id in deps:
            dep = recs_by_id.get(dep_id)
            if dep is None or dep.get("status") != "closed":
                blocked_by.append(dep_id)

        if blocked_by:
            skipped.append(
                {
                    "id": rec["id"],
                    "reason": ("blocked by unclosed dependencies: " + ", ".join(blocked_by)),
                }
            )
            continue

        recommended.append(rec)

    # Sort: priority ascending (Critical=0), then effort ascending
    recommended.sort(
        key=lambda r: (
            PRIORITY_ORDER.get(r.get("priority", "Medium"), 2),
            EFFORT_ORDER.get(r.get("effort", "M"), 2),
        )
    )

    rec_ids = [r["id"] for r in recommended[:limit]]
    return {"recommended": rec_ids, "skipped": skipped}


def topological_sort_recs(recs: list[dict]) -> list[dict]:
    """Sort recommendations in dependency order using graphlib.TopologicalSorter.

    Returns empty list on cycle.
    """
    rec_ids = {rec["id"] for rec in recs}
    rec_by_id = {rec["id"]: rec for rec in recs}

    graph: dict[str, set[str]] = {rec["id"]: set() for rec in recs}
    for rec in recs:
        for dep_id in rec.get("dependencies", []):
            if dep_id in rec_ids:
                graph[rec["id"]].add(dep_id)

    try:
        sorter = graphlib.TopologicalSorter(graph)
        order = list(sorter.static_order())
        return [rec_by_id[rid] for rid in order if rid in rec_by_id]
    except graphlib.CycleError as e:
        logger.error("[BATCH] Dependency cycle detected: %s", e)
        return []


# ---------------------------------------------------------------------------
# Batch execution
# ---------------------------------------------------------------------------


def execute_batch(
    no_merge: bool = False,
    max_recs: int = 10,
    restart: bool = False,
) -> dict:
    """Process eligible recommendations in dependency order.

    Returns:
        Summary dict: {attempted, succeeded, failed, skipped}
    """
    from scripts.execute_recommendation import execute_recommendation  # noqa: PLC0415

    attempted = 0
    succeeded = 0
    failed = 0
    processed_ids: set[str] = set()

    print("\n" + "=" * 60)
    print("BATCH MODE")
    print("=" * 60)

    while attempted < max_recs:
        eligible = get_eligible_recs()
        eligible = [r for r in eligible if r["id"] not in processed_ids]

        if not eligible:
            print("[BATCH] No more eligible recommendations")
            break

        sorted_recs = topological_sort_recs(eligible)
        if not sorted_recs:
            print("[BATCH] No recs after topological sort (possible cycle or empty)")
            break

        rec = sorted_recs[0]
        rec_id = rec["id"]
        processed_ids.add(rec_id)
        attempted += 1

        print(f"\n[BATCH] Processing {rec_id}: {rec.get('title', '(no title)')} ({attempted}/{max_recs})")

        success = execute_recommendation(rec_id, no_merge=no_merge, restart=restart)
        if success:
            succeeded += 1
            print(f"[BATCH] {rec_id}: SUCCESS")
        else:
            failed += 1
            print(f"[BATCH] {rec_id}: FAILED -- continuing to next eligible rec")

        try:
            from scripts.sync.ops import drain as drain_outbox  # noqa: PLC0415

            drain_outbox()
        except Exception:  # noqa: BLE001
            pass  # drain is best-effort; full sync runs at preflight/postflight only

    final_eligible = get_eligible_recs()
    skipped = max(0, len([r for r in final_eligible if r["id"] not in processed_ids]))
    summary = {
        "attempted": attempted,
        "succeeded": succeeded,
        "failed": failed,
        "skipped": skipped,
    }

    print("\n" + "=" * 60)
    print(f"BATCH SUMMARY: {attempted} attempted / {succeeded} succeeded / {failed} failed / {summary['skipped']} skipped")
    print("=" * 60)
    return summary
