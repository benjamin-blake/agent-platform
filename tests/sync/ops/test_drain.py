"""drain() concern: tests/sync/ops/test_drain.py (rec-2709 Wave 10).

Split from the former tests/test_sync_ops.py monolith: TestDrain, TestDrainSkipsRecsOutbox. Each
method-local _FakeOpsWriter/_FailingOpsWriter class moves VERBATIM with its owning method (they
are defined INSIDE the test bodies -- no module-level helper, no cross-import).
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# drain() tests
# ---------------------------------------------------------------------------


class TestDrain:
    def test_drain_empty_outbox_returns_empty_dict(self, tmp_path):
        """drain() returns {} when outbox dir does not exist."""
        with patch("scripts.sync.ops._OUTBOX_DIR", tmp_path / "nonexistent"):
            from scripts.sync.ops import drain

            result = drain()
        assert result == {}

    def test_drain_reads_outbox_calls_opswriter_deletes_file(self, tmp_path):
        """drain() reads non-migrated table files, calls OpsWriter.write(), and deletes the files."""
        outbox_dir = tmp_path / "ops_session_log"
        outbox_dir.mkdir(parents=True)
        entry = {"session_id": "sess-001", "workflow": "plan"}
        (outbox_dir / "test-entry.jsonl").write_text(json.dumps(entry) + "\n", encoding="utf-8")

        mock_writer_instance = MagicMock()
        mock_writer_cls = MagicMock(return_value=mock_writer_instance)

        with patch("scripts.sync.ops._OUTBOX_DIR", tmp_path):
            from scripts.sync import ops as sync_ops

            # patch lazy import inside drain
            with patch.dict("sys.modules", {"scripts.ops_writer": MagicMock(OpsWriter=mock_writer_cls)}):
                result = sync_ops.drain()

        # Verify file was deleted
        assert not (outbox_dir / "test-entry.jsonl").exists()
        assert result.get("ops_session_log", 0) >= 1  # drained at least 1

    def test_drain_factory(self, tmp_path):
        """drain() with real outbox directory successfully drains non-migrated entries."""
        outbox_dir = tmp_path / "ops_session_log"
        outbox_dir.mkdir(parents=True)
        entry = {"session_id": "sess-drain-001", "workflow": "plan"}
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

        assert result.get("ops_session_log") == 1
        mock_writer_instance.write.assert_called_once_with("ops_session_log", entry)
        assert not outfile.exists()

    def test_drain_write_failure_keeps_file(self, tmp_path):
        """If OpsWriter.write() raises, the file is NOT deleted (retry next time)."""
        outbox_dir = tmp_path / "ops_session_log"
        outbox_dir.mkdir(parents=True)
        entry = {"session_id": "sess-002"}
        outfile = outbox_dir / "entry.jsonl"
        outfile.write_text(json.dumps(entry) + "\n", encoding="utf-8")

        class _FailingOpsWriter:
            def __init__(self):
                pass

            def write(self, table, e):
                raise RuntimeError("S3 failure")

        with (
            patch("scripts.sync.ops._OUTBOX_DIR", tmp_path),
            patch.dict(
                "sys.modules",
                {"scripts.ops_writer": MagicMock(OpsWriter=_FailingOpsWriter)},
            ),
        ):
            from scripts.sync import ops as sync_ops

            result = sync_ops.drain()

        # File should still exist since write failed
        assert outfile.exists()
        assert result == {}


# ---------------------------------------------------------------------------
# T2.19 DuckLake cutover -- drain() skips recs outbox
# ---------------------------------------------------------------------------


class TestDrainSkipsRecsOutbox:
    """T2.19: drain() must skip the ops_recommendations outbox dir (Decision 81 cl.7)."""

    def test_drain_skips_recs_outbox_dir(self, tmp_path):
        """drain() skips ops_recommendations outbox files -- recs transit DuckLake boundary."""
        recs_outbox = tmp_path / "ops_recommendations"
        recs_outbox.mkdir(parents=True)
        entry = {"id": "rec-001", "status": "open"}
        outbox_file = recs_outbox / "entry.jsonl"
        outbox_file.write_text(json.dumps(entry) + "\n", encoding="utf-8")

        write_calls: list[tuple] = []

        class _FakeOpsWriter:
            def __init__(self):
                pass

            def write(self, table, e):
                write_calls.append((table, e))

        with (
            patch("scripts.sync.ops._OUTBOX_DIR", tmp_path),
            patch.dict(
                "sys.modules",
                {"scripts.ops_writer": MagicMock(OpsWriter=_FakeOpsWriter)},
            ),
        ):
            from scripts.sync import ops as sync_ops

            result = sync_ops.drain()

        # ops_recommendations outbox entries must NOT be written via OpsWriter
        assert not any(t == "ops_recommendations" for t, _ in write_calls), (
            "drain() must not route ops_recommendations through OpsWriter (Decision 81 cl.7)"
        )
        # Outbox file for recs is NOT deleted (was never processed)
        assert outbox_file.exists(), "recs outbox file should not be deleted (was skipped)"
        # drain() reports 0 for ops_recommendations
        assert result.get("ops_recommendations", 0) == 0

    def test_drain_skips_every_ducklake_migrated_table_and_pending_dirs(self, tmp_path, caplog):
        """drain() skips all _DUCKLAKE_MIGRATED_TABLES dirs and any *_pending dir, with a loud warning.

        Decision 84 I-1/I-4: entries under these dirs are anomalies -- they must never be
        re-staged to Iceberg via OpsWriter (stale-store hazard); the files stay in place.
        """
        import logging

        skip_dirs = ["ops_recommendations", "ops_decisions", "ops_priority_queue", "ops_recommendations_pending"]
        for name in skip_dirs:
            d = tmp_path / name
            d.mkdir(parents=True)
            (d / "entry.jsonl").write_text(json.dumps({"id": "x-001"}) + "\n", encoding="utf-8")

        write_calls: list[tuple] = []

        class _FakeOpsWriter:
            def __init__(self):
                pass

            def write(self, table, e):
                write_calls.append((table, e))

        with (
            patch("scripts.sync.ops._OUTBOX_DIR", tmp_path),
            patch.dict(
                "sys.modules",
                {"scripts.ops_writer": MagicMock(OpsWriter=_FakeOpsWriter)},
            ),
            caplog.at_level(logging.WARNING, logger="scripts.sync.ops"),
        ):
            from scripts.sync import ops as sync_ops

            result = sync_ops.drain()

        assert write_calls == [], "no skipped-table entry may reach OpsWriter"
        assert result == {}
        for name in skip_dirs:
            assert (tmp_path / name / "entry.jsonl").exists(), f"{name} entry must be left in place"
        warned = " ".join(r.message for r in caplog.records)
        assert "DuckLake" in warned and "outbox is retired" in warned
