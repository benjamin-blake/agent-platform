"""Tests for scripts/ops_writer.py -- OpsWriter.drain() concern.

PLAN-coverage-paydown-ops-writer-sync-ops: covers the 29 previously-uncovered statements in
drain(). Decision 84 I-4 CONSTRAINT: no test here may assert that a DuckLake-migrated table
(the two tables the DuckLake closed boundary owns per docs/contracts/storage-substrate.yaml,
scripts.ops_writer._OPS_TABLE_NAMES minus ops_session_log) is drained or put_object'd -- that
would encode as blessed the exact resurrection behaviour the warehouse invariant forbids. Every
early-return/happy-path statement is reached using ONLY ops_session_log (the _OPS_TABLE_NAMES /
dt= partition branch) and a telemetry_* table (the else / trade_date= partition branch), both of
which legitimately drain via OpsWriter.

PLAN-opswriter-never-drain-guard (rec-2929): the module now DOES name the two forbidden tables
deliberately, in TestOpsWriterDrainSkipsRetiredTables -- ops_decisions and ops_priority_queue are
the only two TABLE_NAMES members the never-drain guard changes behaviour for (no *_pending
member, and neither ops_recommendations nor ops_execution_plans belong to TABLE_NAMES), so a
fixture staged under any other name would pass identically with and without the guard.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from tests.fixtures.ops_writer_helpers import make_writer as _make_writer


class TestOpsWriterDrainEarlyReturns:
    """drain()'s three early-return guards, before any table is touched."""

    def test_drain_returns_zeros_when_outbox_base_missing(self, tmp_path):
        """drain() returns all-zero results when _OUTBOX_BASE does not exist."""
        from scripts.ops_writer import TABLE_NAMES

        writer = _make_writer()
        with patch("scripts.ops_writer._OUTBOX_BASE", tmp_path / "does-not-exist"):
            result = writer.drain()

        assert result == {t: 0 for t in TABLE_NAMES}

    def test_drain_returns_zeros_when_client_none(self, tmp_path):
        """drain() returns all-zero results and logs a warning when _get_client() returns None."""
        from scripts.ops_writer import TABLE_NAMES

        writer = _make_writer()
        outbox_base = tmp_path / ".ops-outbox"
        outbox_base.mkdir()

        with (
            patch("scripts.ops_writer._OUTBOX_BASE", outbox_base),
            patch.object(writer, "_get_client", return_value=None),
        ):
            result = writer.drain()

        assert result == {t: 0 for t in TABLE_NAMES}

    def test_drain_returns_zeros_when_bucket_empty(self, tmp_path):
        """drain() returns all-zero results when _bucket() resolves to an empty string."""
        from scripts.ops_writer import TABLE_NAMES

        writer = _make_writer()
        outbox_base = tmp_path / ".ops-outbox"
        outbox_base.mkdir()

        with (
            patch("scripts.ops_writer._OUTBOX_BASE", outbox_base),
            patch.object(writer, "_get_client", return_value=MagicMock()),
            patch.object(writer, "_bucket", return_value=""),
        ):
            result = writer.drain()

        assert result == {t: 0 for t in TABLE_NAMES}

    def test_drain_skips_table_dir_that_does_not_exist(self, tmp_path):
        """drain() skips (continue) a TABLE_NAMES entry whose outbox subdir was never created."""
        from scripts.ops_writer import TABLE_NAMES

        writer = _make_writer()
        outbox_base = tmp_path / ".ops-outbox"
        outbox_base.mkdir()  # base exists, but no per-table subdirs

        mock_client = MagicMock()
        with (
            patch("scripts.ops_writer._OUTBOX_BASE", outbox_base),
            patch.object(writer, "_get_client", return_value=mock_client),
            patch.object(writer, "_bucket", return_value="my-bucket"),
        ):
            result = writer.drain()

        assert result == {t: 0 for t in TABLE_NAMES}
        mock_client.put_object.assert_not_called()


class TestOpsWriterDrainOpsTableBranch:
    """drain()'s _OPS_TABLE_NAMES branch (dt= partition key), exercised via ops_session_log only."""

    def test_drain_ops_session_log_uses_dt_partition_key(self, tmp_path):
        """A staged ops_session_log entry is drained with a dt= partitioned key and deleted."""
        import datetime

        writer = _make_writer()
        outbox_base = tmp_path / ".ops-outbox"
        table_dir = outbox_base / "ops_session_log"
        table_dir.mkdir(parents=True)
        entry = {"session_id": "sess-drain-001", "workflow": "plan"}
        outbox_file = table_dir / "entry.jsonl"
        outbox_file.write_text(json.dumps(entry) + "\n", encoding="utf-8")

        mock_client = MagicMock()
        today = datetime.date.today().isoformat()

        with (
            patch("scripts.ops_writer._OUTBOX_BASE", outbox_base),
            patch.object(writer, "_get_client", return_value=mock_client),
            patch.object(writer, "_bucket", return_value="my-bucket"),
        ):
            result = writer.drain()

        assert result["ops_session_log"] == 1
        assert not outbox_file.exists()
        mock_client.put_object.assert_called_once()
        call_kwargs = mock_client.put_object.call_args[1]
        assert call_kwargs["Bucket"] == "my-bucket"
        assert call_kwargs["Key"].startswith(f"staging/ops_session_log/dt={today}/batch-drain-")
        assert call_kwargs["ContentType"] == "application/x-ndjson"
        saved = json.loads(call_kwargs["Body"].decode("utf-8"))
        assert saved["session_id"] == "sess-drain-001"


class TestOpsWriterDrainTelemetryBranch:
    """drain()'s else branch (trade_date= partition key), exercised via a telemetry_* table."""

    def test_drain_telemetry_table_uses_trade_date_from_entry(self, tmp_path):
        """A telemetry entry carrying its own trade_date drains with that value in the key."""
        writer = _make_writer()
        outbox_base = tmp_path / ".ops-outbox"
        table_dir = outbox_base / "telemetry_sessions"
        table_dir.mkdir(parents=True)
        entry = {"session_id": "sess-tele-001", "trade_date": "2026-03-01"}
        outbox_file = table_dir / "entry.jsonl"
        outbox_file.write_text(json.dumps(entry) + "\n", encoding="utf-8")

        mock_client = MagicMock()

        with (
            patch("scripts.ops_writer._OUTBOX_BASE", outbox_base),
            patch.object(writer, "_get_client", return_value=mock_client),
            patch.object(writer, "_bucket", return_value="my-bucket"),
        ):
            result = writer.drain()

        assert result["telemetry_sessions"] == 1
        assert not outbox_file.exists()
        call_kwargs = mock_client.put_object.call_args[1]
        assert call_kwargs["Key"].startswith("staging/telemetry_sessions/trade_date=2026-03-01/batch-drain-")

    def test_drain_telemetry_table_defaults_trade_date_when_absent(self, tmp_path):
        """A telemetry entry with no trade_date falls back to today's date in the key."""
        import datetime

        writer = _make_writer()
        outbox_base = tmp_path / ".ops-outbox"
        table_dir = outbox_base / "telemetry_sessions"
        table_dir.mkdir(parents=True)
        entry = {"session_id": "sess-tele-002"}
        outbox_file = table_dir / "entry.jsonl"
        outbox_file.write_text(json.dumps(entry) + "\n", encoding="utf-8")

        mock_client = MagicMock()
        today = datetime.date.today().isoformat()

        with (
            patch("scripts.ops_writer._OUTBOX_BASE", outbox_base),
            patch.object(writer, "_get_client", return_value=mock_client),
            patch.object(writer, "_bucket", return_value="my-bucket"),
        ):
            result = writer.drain()

        assert result["telemetry_sessions"] == 1
        call_kwargs = mock_client.put_object.call_args[1]
        assert call_kwargs["Key"].startswith(f"staging/telemetry_sessions/trade_date={today}/batch-drain-")


class TestOpsWriterDrainExceptionHandling:
    """drain()'s per-file exception path: a failure is logged and the file is left in place."""

    def test_drain_put_object_failure_leaves_file_and_continues(self, tmp_path, caplog):
        """A put_object failure for one file is caught, logged, and does not stop other files."""
        import logging

        writer = _make_writer()
        outbox_base = tmp_path / ".ops-outbox"
        table_dir = outbox_base / "ops_session_log"
        table_dir.mkdir(parents=True)

        failing_file = table_dir / "aaa-fail.jsonl"
        failing_file.write_text(json.dumps({"session_id": "sess-fail"}) + "\n", encoding="utf-8")
        ok_file = table_dir / "zzz-ok.jsonl"
        ok_file.write_text(json.dumps({"session_id": "sess-ok"}) + "\n", encoding="utf-8")

        mock_client = MagicMock()
        mock_client.put_object.side_effect = [RuntimeError("S3 down"), None]

        with (
            patch("scripts.ops_writer._OUTBOX_BASE", outbox_base),
            patch.object(writer, "_get_client", return_value=mock_client),
            patch.object(writer, "_bucket", return_value="my-bucket"),
            caplog.at_level(logging.WARNING, logger="scripts.ops_writer"),
        ):
            result = writer.drain()

        # sorted(*.glob) processes aaa-fail.jsonl before zzz-ok.jsonl
        assert failing_file.exists(), "the file whose put_object raised must not be deleted"
        assert not ok_file.exists(), "the file whose put_object succeeded must be deleted"
        assert result["ops_session_log"] == 1
        warned = " ".join(r.message for r in caplog.records)
        assert "failed to drain" in warned

    def test_drain_bad_json_in_outbox_file_is_caught_and_file_kept(self, tmp_path):
        """Malformed JSON in an outbox file raises inside the try block and is swallowed."""
        writer = _make_writer()
        outbox_base = tmp_path / ".ops-outbox"
        table_dir = outbox_base / "ops_session_log"
        table_dir.mkdir(parents=True)
        bad_file = table_dir / "bad.jsonl"
        bad_file.write_text("not valid json{{{", encoding="utf-8")

        mock_client = MagicMock()

        with (
            patch("scripts.ops_writer._OUTBOX_BASE", outbox_base),
            patch.object(writer, "_get_client", return_value=mock_client),
            patch.object(writer, "_bucket", return_value="my-bucket"),
        ):
            result = writer.drain()

        assert bad_file.exists()
        assert result["ops_session_log"] == 0
        mock_client.put_object.assert_not_called()


class TestOpsWriterDrainSkipsRetiredTables:
    """The never-drain guard (Decision 84 I-4, rec-2929): drain() must never put_object() for,
    and must never unlink, a file staged under a retired outbox dir. ops_decisions and
    ops_priority_queue are the only two TABLE_NAMES members this guard changes behaviour for --
    ops_recommendations and ops_execution_plans are not TABLE_NAMES members, and there is no
    *_pending member, so a fixture staged under any of those would pass identically before and
    after the guard and would prove nothing.
    """

    def test_drain_skips_retired_ops_decisions_outbox(self, tmp_path):
        """A staged ops_decisions entry is neither put_object()'d nor unlinked."""
        writer = _make_writer()
        outbox_base = tmp_path / ".ops-outbox"
        table_dir = outbox_base / "ops_decisions"
        table_dir.mkdir(parents=True)
        outbox_file = table_dir / "entry.jsonl"
        outbox_file.write_text(json.dumps({"decision_id": "dec-999"}) + "\n", encoding="utf-8")

        mock_client = MagicMock()

        with (
            patch("scripts.ops_writer._OUTBOX_BASE", outbox_base),
            patch.object(writer, "_get_client", return_value=mock_client),
            patch.object(writer, "_bucket", return_value="my-bucket"),
        ):
            result = writer.drain()

        mock_client.put_object.assert_not_called()
        assert outbox_file.exists(), "a retired-dir outbox file must never be unlinked"
        assert result["ops_decisions"] == 0

    def test_drain_skips_retired_ops_priority_queue_outbox(self, tmp_path):
        """A staged ops_priority_queue entry is neither put_object()'d nor unlinked."""
        writer = _make_writer()
        outbox_base = tmp_path / ".ops-outbox"
        table_dir = outbox_base / "ops_priority_queue"
        table_dir.mkdir(parents=True)
        outbox_file = table_dir / "entry.jsonl"
        outbox_file.write_text(json.dumps({"rec_id": "rec-999"}) + "\n", encoding="utf-8")

        mock_client = MagicMock()

        with (
            patch("scripts.ops_writer._OUTBOX_BASE", outbox_base),
            patch.object(writer, "_get_client", return_value=mock_client),
            patch.object(writer, "_bucket", return_value="my-bucket"),
        ):
            result = writer.drain()

        mock_client.put_object.assert_not_called()
        assert outbox_file.exists(), "a retired-dir outbox file must never be unlinked"
        assert result["ops_priority_queue"] == 0

    def test_drain_skips_retired_but_still_drains_legitimate_tables(self, tmp_path):
        """A retired dir alongside a legitimate one: only the legitimate one drains."""
        writer = _make_writer()
        outbox_base = tmp_path / ".ops-outbox"

        retired_dir = outbox_base / "ops_decisions"
        retired_dir.mkdir(parents=True)
        retired_file = retired_dir / "entry.jsonl"
        retired_file.write_text(json.dumps({"decision_id": "dec-998"}) + "\n", encoding="utf-8")

        session_dir = outbox_base / "ops_session_log"
        session_dir.mkdir(parents=True)
        session_file = session_dir / "entry.jsonl"
        session_file.write_text(json.dumps({"session_id": "sess-legit"}) + "\n", encoding="utf-8")

        telemetry_dir = outbox_base / "telemetry_sessions"
        telemetry_dir.mkdir(parents=True)
        telemetry_file = telemetry_dir / "entry.jsonl"
        telemetry_file.write_text(json.dumps({"session_id": "sess-tele"}) + "\n", encoding="utf-8")

        mock_client = MagicMock()

        with (
            patch("scripts.ops_writer._OUTBOX_BASE", outbox_base),
            patch.object(writer, "_get_client", return_value=mock_client),
            patch.object(writer, "_bucket", return_value="my-bucket"),
        ):
            result = writer.drain()

        drained_tables = {call.kwargs["Key"].split("/")[1] for call in mock_client.put_object.call_args_list}
        assert drained_tables == {"ops_session_log", "telemetry_sessions"}
        assert retired_file.exists(), "the retired-dir file must survive"
        assert not session_file.exists()
        assert not telemetry_file.exists()
        assert result["ops_decisions"] == 0
        assert result["ops_session_log"] == 1
        assert result["telemetry_sessions"] == 1

    def test_drain_results_stay_full_width_for_retired_tables(self, tmp_path):
        """drain()'s returned dict still reports 0 for retired tables rather than omitting them."""
        from scripts.ops_writer import TABLE_NAMES

        writer = _make_writer()
        outbox_base = tmp_path / ".ops-outbox"
        outbox_base.mkdir()

        mock_client = MagicMock()

        with (
            patch("scripts.ops_writer._OUTBOX_BASE", outbox_base),
            patch.object(writer, "_get_client", return_value=mock_client),
            patch.object(writer, "_bucket", return_value="my-bucket"),
        ):
            result = writer.drain()

        assert set(result) == set(TABLE_NAMES), "retired tables must still appear in the results shape"
        assert result["ops_decisions"] == 0
        assert result["ops_priority_queue"] == 0
