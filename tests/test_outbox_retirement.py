"""Tests for src/common/outbox_retirement.py -- the sole retired-outbox classification.

Decision 84 I-4: the offline outbox for a DuckLake-migrated table (or any *_pending sibling) is
retired and must never be drained back into Iceberg. This module names the predicate; do not
quote it verbatim in this file's prose, since a recursive grep for the predicate's exact text
is used elsewhere to prove it has exactly one definition repo-wide.
"""

from __future__ import annotations

from src.common.outbox_retirement import DUCKLAKE_MIGRATED_TABLES, is_retired_dir


class TestDucklakeMigratedTables:
    def test_migrated_table_set(self):
        assert DUCKLAKE_MIGRATED_TABLES == frozenset(
            {"ops_recommendations", "ops_decisions", "ops_priority_queue", "ops_execution_plans"}
        )


class TestIsRetiredDir:
    def test_every_migrated_table_is_retired(self):
        for table in DUCKLAKE_MIGRATED_TABLES:
            assert is_retired_dir(table) is True

    def test_pending_suffix_is_retired(self):
        assert is_retired_dir("anything_pending") is True
        assert is_retired_dir("ops_recommendations_pending") is True

    def test_legitimately_drainable_dirs_are_not_retired(self):
        assert is_retired_dir("ops_session_log") is False
        assert is_retired_dir("telemetry_sessions") is False
