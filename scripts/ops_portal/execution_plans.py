"""ops_execution_plans producer -- Single-Portal write path for the executor's plan-revision log.

Owner-concern: projecting ExecutionPlan.to_dict() (scripts/executor/plan.py) onto the
ops_execution_plans registered columns and writing it through the DuckLake closed boundary
(Decision 84 / 81 cl.4). Mirrors scripts/ops_portal/decisions.py's file_decision shape: a single
caller-keyed write_ops upsert -- merge_key is rec_id, and every write (first revision or a later
one) goes through the same verb (no file_ops/update_ops referential distinction; write_ops never
requires the merge key to pre-exist, so it covers both cases uniformly).

The executor producer (scripts/executor/plan.py::save_plan) is CD.17-frozen, so this producer
lands no rows in production until the executor resumes; VP proves the write path directly against
the deployed writer/reader (save_execution_plan -> write_ops -> reader round-trip).
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from scripts.ops_portal._common import ROOT
from scripts.ops_portal.cache import _refresh_cache_after_write
from scripts.ops_portal.writer_transport import _ducklake_write

logger = logging.getLogger(__name__)

# Current-state read cache for ops_execution_plans (Decision 84 I-4: downstream of the writer,
# never a write source). Deliberately distinct from logs/.execution-plans.jsonl -- the executor's
# own append-only per-revision log (scripts/executor/plan.py::save_plan / get_latest_plan) -- since
# this cache is a one-row-per-rec_id CURRENT projection (upsert_cache_row semantics, the same shape
# as RECS_JSONL/DECISIONS_JSONL); collapsing the executor's append log onto that shape would destroy
# its per-revision history.
EXECUTION_PLANS_JSONL = ROOT / "logs" / ".execution-plans-index.jsonl"

# Columns whose DuckLake sql_type is VARCHAR-carrying-JSON (config/lambda/ducklake/field_semantics.static.yaml).
_JSON_BLOB_FIELDS = ("steps", "critique_history")


def save_execution_plan(plan_dict: dict, profile: Optional[str] = None) -> bool:
    """Write one ExecutionPlan revision to ops_execution_plans via the DuckLake closed boundary.

    plan_dict is ExecutionPlan.to_dict(): rec_id/revision/status/model/tokens_used/prompt_hash/
    slug/planning_session_id are carried as scalars; steps/critique_history are json.dumps'd onto
    their VARCHAR JSON columns (the schema gate requires a str for a VARCHAR field -- a raw list
    fails isinstance). planning_session_id passes through as an opaque string carry (no UUID/ULID
    translation table, Decision 97 cl.4 / session-id.yaml). Unregistered dataclass fields (e.g.
    `timestamp`) are dropped silently by the writer transport's column projection.

    Fail-loud (Decision 84 I-4): no try/except-warn wrapper. A write that cannot complete raises.

    Returns:
        True on success. Raises on any writer failure (no offline outbox).
    """
    merged = dict(plan_dict)
    for field_name in _JSON_BLOB_FIELDS:
        if field_name in merged and not isinstance(merged[field_name], str):
            merged[field_name] = json.dumps(merged[field_name])

    response = _ducklake_write("ops_execution_plans", merged, action="write_ops", profile=profile)
    logger.info(
        "[PORTAL] Wrote ops_execution_plans %s revision %s (%s)",
        merged.get("rec_id"),
        merged.get("revision"),
        merged.get("status"),
    )

    # upsert_cache_row's merge_key defaults to "id" (scripts/ops_portal/cache.py); alias rec_id onto
    # a cache-only "id" key for THIS local projection rather than widening the shared cache helper's
    # default merge key. The warehouse write above already used `merged` (no "id" key), so this alias
    # never reaches the wire.
    cache_record = dict(merged)
    cache_record.setdefault("id", cache_record.get("rec_id"))
    _refresh_cache_after_write("ops_execution_plans", cache_record, response, EXECUTION_PLANS_JSONL)
    return True
