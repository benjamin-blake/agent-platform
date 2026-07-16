"""sync orchestration + outbox + CLI + table-map invariants + upsert concern:
tests/sync/ops/test_sync_cli.py (rec-2709 Wave 10).

Split from the former tests/test_sync_ops.py monolith: TestSync, TestOutboxSummary, TestMain,
TestTelemetryMappings, TestPipelineConsolidation, TestUpsertCacheRow.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# sync() tests
# ---------------------------------------------------------------------------


class TestSync:
    def test_sync_calls_drain_then_pull(self):
        """sync() calls drain() then _rebuild_local_cache() and returns combined result."""
        with (
            patch("scripts.sync.ops.drain", return_value={"ops_recommendations": 2}) as mock_drain,
            patch("scripts.sync.ops._rebuild_local_cache", return_value={"ops_recommendations": 50}) as mock_rebuild,
        ):
            from scripts.sync.ops import sync

            result = sync(profile="test-profile")

        mock_drain.assert_called_once()
        mock_rebuild.assert_called_once_with("test-profile")
        assert result["drained"] == {"ops_recommendations": 2}
        assert result["pulled"] == {"ops_recommendations": 50}

    def test_sync_drain_before_pull_ordering(self):
        """sync() always calls drain before _rebuild_local_cache."""
        call_order = []

        def fake_drain():
            call_order.append("drain")
            return {}

        def fake_rebuild(profile=None):
            call_order.append("pull")
            return {}

        with (
            patch("scripts.sync.ops.drain", side_effect=fake_drain),
            patch("scripts.sync.ops._rebuild_local_cache", side_effect=fake_rebuild),
        ):
            from scripts.sync.ops import sync

            sync()

        assert call_order == ["drain", "pull"]


# ---------------------------------------------------------------------------
# outbox_summary() tests
# ---------------------------------------------------------------------------


class TestOutboxSummary:
    def test_no_outbox_returns_empty(self, tmp_path):
        """outbox_summary() returns {} when outbox dir does not exist."""
        with patch("scripts.sync.ops._OUTBOX_DIR", tmp_path / "nonexistent"):
            from scripts.sync.ops import outbox_summary

            result = outbox_summary()
        assert result == {}

    def test_counts_files_per_table(self, tmp_path):
        """outbox_summary() counts files in each table subdirectory."""
        (tmp_path / "ops_recommendations").mkdir()
        for i in range(3):
            (tmp_path / "ops_recommendations" / f"entry-{i}.jsonl").write_text("{}", encoding="utf-8")
        (tmp_path / "ops_execution_plans").mkdir()
        (tmp_path / "ops_execution_plans" / "plan.jsonl").write_text("{}", encoding="utf-8")

        with patch("scripts.sync.ops._OUTBOX_DIR", tmp_path):
            from scripts.sync.ops import outbox_summary

            result = outbox_summary()

        assert result["ops_recommendations"] == 3
        assert result["ops_execution_plans"] == 1

    def test_empty_table_dir_excluded(self, tmp_path):
        """outbox_summary() does not include tables with 0 files."""
        (tmp_path / "ops_recommendations").mkdir()
        # No files in dir

        with patch("scripts.sync.ops._OUTBOX_DIR", tmp_path):
            from scripts.sync.ops import outbox_summary

            result = outbox_summary()

        assert "ops_recommendations" not in result


# ---------------------------------------------------------------------------
# main() / CLI tests
# ---------------------------------------------------------------------------


class TestMain:
    def test_help_exits_0(self):
        """sync_ops --help exits 0."""
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, "-m", "scripts.sync.ops", "--help"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        assert result.returncode == 0

    def test_drain_subcommand(self):
        """sync_ops drain subcommand is removed -- argparse exits non-zero."""
        import sys

        import pytest

        import scripts.sync.ops as _sync_ops

        old_argv = sys.argv
        sys.argv = ["sync_ops", "drain"]
        try:
            with pytest.raises(SystemExit) as exc_info:
                _sync_ops.main()
            assert exc_info.value.code != 0
        finally:
            sys.argv = old_argv


# ---------------------------------------------------------------------------
# Telemetry table mapping tests
# ---------------------------------------------------------------------------


class TestTelemetryMappings:
    """Telemetry + non-migrated ops tables were removed from the sync maps (public-migration).

    Only ops_recommendations / ops_decisions / ops_priority_queue are migrated to the personal
    account; telemetry_*, ops_session_log, and ops_execution_plans must NOT appear in the maps, or
    sync_ops.pull would issue TABLE_NOT_FOUND queries on every sync.
    """

    _TELEMETRY_TABLES = [
        "telemetry_sessions",
        "telemetry_phases",
        "telemetry_steps",
        "telemetry_process_events",
        "telemetry_model_calls",
        "telemetry_transcripts",
        "telemetry_agent_invocations",
    ]
    _REMOVED_OPS_TABLES = ["ops_session_log", "ops_execution_plans"]

    def test_telemetry_tables_absent_from_maps(self):
        """No telemetry table is mapped (they are not migrated to the personal account)."""
        from scripts.sync.ops import _TABLE_TO_LOCAL

        for table in self._TELEMETRY_TABLES:
            assert table not in _TABLE_TO_LOCAL, f"{table} should be removed from _TABLE_TO_LOCAL"

    def test_non_migrated_ops_tables_absent(self):
        """ops_session_log and ops_execution_plans are not migrated and must be absent."""
        from scripts.sync.ops import _TABLE_TO_LOCAL

        for table in self._REMOVED_OPS_TABLES:
            assert table not in _TABLE_TO_LOCAL

    def test_migrated_ops_tables_present(self):
        """All three migrated tables are cached locally; the Athena view map is deleted (Decision 84 I-1)."""
        import scripts.sync.ops as sync_ops

        assert set(sync_ops._TABLE_TO_LOCAL) == {"ops_recommendations", "ops_decisions", "ops_priority_queue"}
        assert sync_ops._DUCKLAKE_MIGRATED_TABLES == frozenset({"ops_recommendations", "ops_decisions", "ops_priority_queue"})
        # The Athena pull estate is gone: no view map, no per-table Athena pull.
        assert not hasattr(sync_ops, "_TABLE_TO_VIEW")
        assert not hasattr(sync_ops, "_pull_single_table_athena")

    def test_drain_handles_telemetry_outbox_files(self, tmp_path):
        """drain() can process outbox files for telemetry tables."""
        outbox_dir = tmp_path / "telemetry_sessions"
        outbox_dir.mkdir(parents=True)
        entry = {
            "session_id": "sess-001",
            "workflow": "executor",
            "outcome": "success",
        }
        outfile = outbox_dir / "entry.jsonl"
        outfile.write_text(json.dumps(entry) + "\n", encoding="utf-8")

        mock_writer_instance = MagicMock()

        class _FakeOpsWriter:
            def __init__(self):
                pass

            def write(self, table, e):
                mock_writer_instance.write(table, e)

        with (
            patch("scripts.sync.ops._OUTBOX_DIR", tmp_path),
            patch.dict(
                "sys.modules",
                {"scripts.ops_writer": MagicMock(OpsWriter=_FakeOpsWriter)},
            ),
        ):
            from scripts.sync import ops as sync_ops

            result = sync_ops.drain()

        assert result.get("telemetry_sessions") == 1
        mock_writer_instance.write.assert_called_once_with("telemetry_sessions", entry)
        assert not outfile.exists()


class TestPipelineConsolidation:
    """Tests for pipeline consolidation changes (Decision 69)."""

    def test_coerce_ops_rec_row_rejects_dec_ids(self):
        """_coerce_ops_rec_row returns None and writes a reject log for dec-* prefixed IDs."""
        from unittest.mock import patch

        from scripts.sync.ops import _coerce_ops_rec_row

        row = {"id": "dec-42", "title": "Test", "source": "manual", "effort": "S", "priority": "Low"}
        with patch("scripts.sync.ops._write_sync_reject") as mock_reject:
            result = _coerce_ops_rec_row(row)

        assert result is None
        mock_reject.assert_called_once()
        call_args = mock_reject.call_args[0]
        assert call_args[0] is row
        assert "invalid id prefix" in call_args[1]

    def test_coerce_ops_rec_row_accepts_valid_prefixes(self):
        """_coerce_ops_rec_row returns the row for rec-, agent-, and test- prefixes."""
        from scripts.sync.ops import _coerce_ops_rec_row

        for valid_id in ("rec-001", "agent-abc", "test-xyz"):
            row = {"id": valid_id, "dependencies": "", "tags": "", "execution_steps": "", "automatable": ""}
            result = _coerce_ops_rec_row(row)
            assert result is not None, f"expected non-None for id={valid_id!r}"
            assert result["id"] == valid_id

    def test_drain_cli_removed(self):
        """Running `python -m scripts.sync.ops drain` exits non-zero (subcommand removed)."""
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, "-m", "scripts.sync.ops", "drain"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(Path(__file__).parent.parent.parent.parent),
        )
        assert result.returncode != 0

    def test_pull_cli_removed(self):
        """Running `python -m scripts.sync.ops pull` exits non-zero (subcommand removed)."""
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, "-m", "scripts.sync.ops", "pull"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(Path(__file__).parent.parent.parent.parent),
        )
        assert result.returncode != 0


# ---------------------------------------------------------------------------
# upsert_cache_row() tests
# ---------------------------------------------------------------------------


class TestUpsertCacheRow:
    def test_devnull_sentinel_returns_zero_no_tmp_written(self) -> None:
        """upsert_cache_row with path=Path(os.devnull) returns 0 and writes no .tmp file."""
        from scripts.sync import ops as sync_ops

        result = sync_ops.upsert_cache_row("ops_recommendations", {"id": "rec-9999", "title": "t"}, path=Path(os.devnull))
        assert result == 0
        assert not Path(os.devnull + ".tmp").exists()

    def test_real_path_writes_cache_row(self, tmp_path: Path) -> None:
        """upsert_cache_row with a real path writes the row and returns row count."""
        from scripts.sync import ops as sync_ops

        cache_file = tmp_path / "recs.jsonl"
        result = sync_ops.upsert_cache_row("ops_recommendations", {"id": "rec-0001", "title": "hello"}, path=cache_file)
        assert result == 1
        assert cache_file.exists()
        row = json.loads(cache_file.read_text(encoding="utf-8").strip())
        assert row["id"] == "rec-0001"
