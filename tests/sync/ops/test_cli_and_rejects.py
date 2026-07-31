"""Tests for scripts/sync/ops.py -- reject-logging, check_sso, outbox_summary, main(), and
drain()'s outer exception-handling concern.

PLAN-coverage-paydown-ops-writer-sync-ops: covers the remaining 31 statements --
_write_decisions_sync_reject (7), check_sso (6), outbox_summary (3), main (3), drain (3),
_write_sync_reject (2), plus residual scattered lines. Collision-free (existing module is
test_sync_cli.py).
"""

from __future__ import annotations

import json
import sys
from unittest.mock import MagicMock, patch


class TestWriteSyncReject:
    def test_writes_reject_entry_to_log(self, tmp_path):
        """_write_sync_reject() appends a JSONL entry with reason and row."""
        from scripts.sync.ops import _write_sync_reject

        reject_log = tmp_path / "debug" / "dq-sync-rejects.jsonl"
        with patch("scripts.sync.ops._SYNC_REJECTS_LOG", reject_log):
            _write_sync_reject({"id": "rec-bad"}, "invalid id prefix")

        entry = json.loads(reject_log.read_text(encoding="utf-8").strip())
        assert entry["reason"] == "invalid id prefix"
        assert entry["row"]["id"] == "rec-bad"

    def test_write_failure_is_swallowed(self, tmp_path):
        """_write_sync_reject() logs a warning and does not raise when the write fails."""
        from scripts.sync.ops import _write_sync_reject

        blocking_file = tmp_path / "blocked"
        blocking_file.write_text("not a directory", encoding="utf-8")
        reject_log = blocking_file / "nested" / "dq-sync-rejects.jsonl"

        with patch("scripts.sync.ops._SYNC_REJECTS_LOG", reject_log):
            _write_sync_reject({"id": "rec-bad"}, "some reason")  # must not raise


class TestWriteDecisionsSyncReject:
    def test_writes_reject_entry_to_log(self, tmp_path):
        """_write_decisions_sync_reject() appends a JSONL entry with reason and row."""
        from scripts.sync.ops import _write_decisions_sync_reject

        reject_log = tmp_path / "debug" / "decisions-sync-rejects.jsonl"
        with patch("scripts.sync.ops._DECISIONS_SYNC_REJECTS_LOG", reject_log):
            _write_decisions_sync_reject({"id": "dec-010"}, "dual-write invariant violated")

        entry = json.loads(reject_log.read_text(encoding="utf-8").strip())
        assert entry["reason"] == "dual-write invariant violated"
        assert entry["row"]["id"] == "dec-010"

    def test_write_failure_is_swallowed(self, tmp_path):
        """_write_decisions_sync_reject() logs a warning and does not raise when the write fails."""
        from scripts.sync.ops import _write_decisions_sync_reject

        blocking_file = tmp_path / "blocked"
        blocking_file.write_text("not a directory", encoding="utf-8")
        reject_log = blocking_file / "nested" / "decisions-sync-rejects.jsonl"

        with patch("scripts.sync.ops._DECISIONS_SYNC_REJECTS_LOG", reject_log):
            _write_decisions_sync_reject({"id": "dec-010"}, "some reason")  # must not raise


class TestCheckSso:
    def test_returns_true_when_returncode_zero(self):
        """check_sso() returns True when the aws CLI subprocess exits 0."""
        from scripts.sync.ops import check_sso

        mock_result = MagicMock(returncode=0)
        with patch("scripts.sync.ops.subprocess.run", return_value=mock_result) as mock_run:
            result = check_sso("agent_platform")

        assert result is True
        call_args = mock_run.call_args[0][0]
        assert call_args == ["aws", "sts", "get-caller-identity", "--profile", "agent_platform"]

    def test_returns_false_when_returncode_nonzero(self):
        """check_sso() returns False when the aws CLI subprocess exits non-zero."""
        from scripts.sync.ops import check_sso

        mock_result = MagicMock(returncode=1)
        with patch("scripts.sync.ops.subprocess.run", return_value=mock_result):
            result = check_sso("agent_platform")

        assert result is False

    def test_returns_false_and_logs_on_exception(self):
        """check_sso() catches any exception (e.g. timeout) and returns False."""
        from scripts.sync.ops import check_sso

        with patch("scripts.sync.ops.subprocess.run", side_effect=RuntimeError("aws cli not found")):
            result = check_sso("agent_platform")

        assert result is False


class TestOutboxSummaryEdgeCases:
    def test_skips_non_directory_entries(self, tmp_path):
        """outbox_summary() skips a stray file directly under the outbox root."""
        from scripts.sync import ops as sync_ops

        (tmp_path / "stray_file.txt").write_text("not a table dir", encoding="utf-8")
        table_dir = tmp_path / "ops_recommendations"
        table_dir.mkdir()
        (table_dir / "entry.jsonl").write_text("{}", encoding="utf-8")

        with patch("scripts.sync.ops._OUTBOX_DIR", tmp_path):
            result = sync_ops.outbox_summary()

        assert result == {"ops_recommendations": 1}

    def test_exception_is_caught_and_logged(self):
        """outbox_summary() catches an unexpected exception and returns whatever was gathered so far."""
        from scripts.sync import ops as sync_ops

        mock_outbox = MagicMock()
        mock_outbox.exists.return_value = True
        mock_outbox.iterdir.side_effect = RuntimeError("disk error")

        with patch("scripts.sync.ops._OUTBOX_DIR", mock_outbox):
            result = sync_ops.outbox_summary()

        assert result == {}


class TestDrainOuterExceptionHandling:
    def test_unexpected_exception_is_caught_and_logged(self):
        """drain()'s outer try/except catches an unexpected failure (e.g. iterdir() raising)."""
        from scripts.sync import ops as sync_ops

        mock_outbox = MagicMock()
        mock_outbox.exists.return_value = True
        mock_outbox.iterdir.side_effect = RuntimeError("disk error")

        with patch("scripts.sync.ops._OUTBOX_DIR", mock_outbox):
            result = sync_ops.drain()

        assert result == {}

    def test_drain_skips_non_directory_entry_under_outbox(self, tmp_path):
        """drain() skips (continue) a stray file directly under _OUTBOX_DIR that is not a directory."""
        from scripts.sync import ops as sync_ops

        (tmp_path / "stray_file.jsonl").write_text("{}", encoding="utf-8")
        table_dir = tmp_path / "ops_session_log"
        table_dir.mkdir()
        entry = {"session_id": "sess-001"}
        (table_dir / "entry.jsonl").write_text(json.dumps(entry) + "\n", encoding="utf-8")

        mock_writer_instance = MagicMock()

        class _FakeOpsWriter:
            def __init__(self):
                pass

            def write(self, table, e):
                mock_writer_instance.write(table, e)

        with (
            patch("scripts.sync.ops._OUTBOX_DIR", tmp_path),
            patch.dict("sys.modules", {"scripts.ops_writer": MagicMock(OpsWriter=_FakeOpsWriter)}),
        ):
            result = sync_ops.drain()

        assert result.get("ops_session_log") == 1
        mock_writer_instance.write.assert_called_once_with("ops_session_log", entry)


class TestPullViaReaderPriorityQueueVerb:
    def test_pull_via_reader_uses_named_priority_queue_current_verb(self):
        """_pull_via_reader() routes ops_priority_queue through reader.named('priority_queue_current')

        Decision 70: the queue current state is ALL entries of the LATEST curator run, so this
        table uses the dedicated `named()` verb rather than the generic `current_state()` path
        every other migrated table uses.
        """
        from scripts.sync.ops import _pull_via_reader

        reader = MagicMock()
        reader.named.return_value = [{"rec_id": "rec-1", "rank": 1}]
        with patch("src.common.iceberg_reader.make_reader", return_value=reader) as mock_make:
            result = _pull_via_reader("ops_priority_queue")

        assert result == [{"rec_id": "rec-1", "rank": 1}]
        mock_make.assert_called_once_with(table="ops_priority_queue")
        reader.named.assert_called_once_with("priority_queue_current")
        reader.current_state.assert_not_called()


class TestMainCli:
    def test_main_sync_command_prints_json_result(self, capsys):
        """main() with the 'sync' command calls sync() and prints its result as JSON."""
        from scripts.sync import ops as sync_ops

        fake_result = {"drained": {}, "pulled": {"ops_recommendations": 5}}
        old_argv = sys.argv
        sys.argv = ["sync_ops", "sync"]
        try:
            with patch("scripts.sync.ops.sync", return_value=fake_result) as mock_sync:
                sync_ops.main()
        finally:
            sys.argv = old_argv

        mock_sync.assert_called_once_with(sync_ops._SSO_PROFILE)
        printed = json.loads(capsys.readouterr().out)
        assert printed == fake_result

    def test_main_sync_command_passes_custom_profile(self, capsys):
        """main() forwards a custom --profile value through to sync()."""
        from scripts.sync import ops as sync_ops

        old_argv = sys.argv
        sys.argv = ["sync_ops", "sync", "--profile", "custom-profile"]
        try:
            with patch("scripts.sync.ops.sync", return_value={}) as mock_sync:
                sync_ops.main()
        finally:
            sys.argv = old_argv

        mock_sync.assert_called_once_with("custom-profile")
