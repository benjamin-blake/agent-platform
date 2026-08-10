"""Sole home for the retired-outbox classification (Decision 84 I-4).

DUCKLAKE_MIGRATED_TABLES names the tables that transit the DuckLake closed boundary: their
offline outbox dirs are retired and must never be drained back into Iceberg, since a re-staged
row would resurrect a deleted-on-the-warehouse record. is_retired_dir() extends that to any
*_pending sibling dir. Every drain path (scripts/ops_writer.py, scripts/sync/ops.py) and every
staleness/hermeticity guard (scripts/checks/ops_governance/validate_outbox_staleness.py,
tests/fixtures/outbox_guard.py) consumes this module rather than redefining the predicate.

Pure stdlib leaf: no boto3, no awswrangler, no scripts.* imports. Bundled into the data-pipeline
and ops-compaction Lambda zips via their `includes: - src/` wildcard.
"""

from __future__ import annotations

DUCKLAKE_MIGRATED_TABLES: frozenset[str] = frozenset(
    {"ops_recommendations", "ops_decisions", "ops_priority_queue", "ops_execution_plans"}
)


def is_retired_dir(dirname: str) -> bool:
    """A retired-outbox subdirectory is a migrated table or its *_pending sibling."""
    return dirname in DUCKLAKE_MIGRATED_TABLES or dirname.endswith("_pending")
