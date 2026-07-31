"""Unit tests for tests/fixtures/outbox_guard.py -- the outbox hermeticity guard's detection logic."""

from __future__ import annotations

import os

from tests.fixtures.outbox_guard import (
    OUTBOX_BASE,
    diff_new_files,
    is_retired_dir,
    retired_files,
    snapshot,
)


class TestIsRetiredDir:
    def test_migrated_table_dir_is_retired(self):
        assert is_retired_dir("ops_recommendations") is True
        assert is_retired_dir("ops_decisions") is True
        assert is_retired_dir("ops_priority_queue") is True
        assert is_retired_dir("ops_execution_plans") is True

    def test_pending_suffix_is_retired(self):
        assert is_retired_dir("ops_recommendations_pending") is True

    def test_legacy_staging_dir_is_not_retired(self):
        assert is_retired_dir("telemetry") is False
        assert is_retired_dir("ops_session_log") is False


class TestSnapshot:
    def test_missing_base_returns_empty_set(self, tmp_path):
        base = tmp_path / "does-not-exist"
        assert snapshot(base) == frozenset()

    def test_clean_tree_is_clean(self, tmp_path):
        base = tmp_path / ".ops-outbox"
        base.mkdir()
        assert snapshot(base) == frozenset()

    def test_snapshot_finds_existing_files(self, tmp_path):
        base = tmp_path / ".ops-outbox"
        (base / "ops_recommendations").mkdir(parents=True)
        f = base / "ops_recommendations" / "one.jsonl"
        f.write_text("{}")
        assert snapshot(base) == frozenset({f})

    def test_base_is_absolute(self):
        assert OUTBOX_BASE.is_absolute()

    def test_base_survives_chdir(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert OUTBOX_BASE.is_absolute()
        assert os.getcwd() != str(OUTBOX_BASE.parent)


class TestDiffNewFiles:
    def test_new_file_in_retired_dir_is_detected(self, tmp_path):
        base = tmp_path / ".ops-outbox"
        (base / "ops_recommendations").mkdir(parents=True)
        before = snapshot(base)

        new_file = base / "ops_recommendations" / "new.jsonl"
        new_file.write_text("{}")
        after = snapshot(base)

        assert diff_new_files(before, after) == frozenset({new_file})

    def test_new_file_in_legacy_dir_is_detected(self, tmp_path):
        base = tmp_path / ".ops-outbox"
        (base / "telemetry").mkdir(parents=True)
        before = snapshot(base)

        new_file = base / "telemetry" / "new.jsonl"
        new_file.write_text("{}")
        after = snapshot(base)

        assert diff_new_files(before, after) == frozenset({new_file})

    def test_preexisting_legacy_file_not_reported_as_new(self, tmp_path):
        base = tmp_path / ".ops-outbox"
        (base / "telemetry").mkdir(parents=True)
        existing = base / "telemetry" / "existing.jsonl"
        existing.write_text("{}")

        before = snapshot(base)
        after = snapshot(base)

        assert diff_new_files(before, after) == frozenset()


class TestRetiredFiles:
    def test_preexisting_retired_file_trips_session_start_check(self, tmp_path):
        base = tmp_path / ".ops-outbox"
        (base / "ops_decisions").mkdir(parents=True)
        leaked = base / "ops_decisions" / "leaked.jsonl"
        leaked.write_text("{}")

        found = retired_files(snapshot(base), base=base)
        assert found == frozenset({leaked})

    def test_legacy_file_is_not_a_retired_file(self, tmp_path):
        base = tmp_path / ".ops-outbox"
        (base / "ops_session_log").mkdir(parents=True)
        legacy = base / "ops_session_log" / "pending.jsonl"
        legacy.write_text("{}")

        assert retired_files(snapshot(base), base=base) == frozenset()

    def test_clean_tree_has_no_retired_files(self, tmp_path):
        base = tmp_path / ".ops-outbox"
        base.mkdir()
        assert retired_files(snapshot(base), base=base) == frozenset()
