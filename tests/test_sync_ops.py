"""Tests for scripts/sync_ops.py."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# drain() tests
# ---------------------------------------------------------------------------


class TestDrain:
    def test_drain_empty_outbox_returns_empty_dict(self, tmp_path):
        """drain() returns {} when outbox dir does not exist."""
        with patch("scripts.sync_ops._OUTBOX_DIR", tmp_path / "nonexistent"):
            from scripts.sync_ops import drain

            result = drain()
        assert result == {}

    def test_drain_reads_outbox_calls_opswriter_deletes_file(self, tmp_path):
        """drain() reads files, calls OpsWriter.write(), and deletes the files."""
        outbox_dir = tmp_path / "ops_decisions"
        outbox_dir.mkdir(parents=True)
        entry = {"id": "dec-001", "status": "open"}
        (outbox_dir / "test-entry.jsonl").write_text(json.dumps(entry) + "\n", encoding="utf-8")

        mock_writer_instance = MagicMock()
        mock_writer_cls = MagicMock(return_value=mock_writer_instance)

        with (
            patch("scripts.sync_ops._OUTBOX_DIR", tmp_path),
            patch("scripts.sync_ops.OpsWriter", mock_writer_cls, create=True),
        ):
            from scripts import sync_ops

            # patch lazy import inside drain
            with patch.dict("sys.modules", {"scripts.ops_writer": MagicMock(OpsWriter=mock_writer_cls)}):
                result = sync_ops.drain()

        # Verify file was deleted
        assert not (outbox_dir / "test-entry.jsonl").exists()
        assert result.get("ops_decisions", 0) >= 1  # drained at least 1

    def test_drain_factory(self, tmp_path):
        """drain() with real outbox directory successfully drains entries."""
        outbox_dir = tmp_path / "ops_decisions"
        outbox_dir.mkdir(parents=True)
        entry = {"id": "dec-drain-001", "status": "open"}
        outfile = outbox_dir / "entry.jsonl"
        outfile.write_text(json.dumps(entry) + "\n", encoding="utf-8")

        mock_writer_instance = MagicMock()

        class _FakeOpsWriter:
            def __init__(self):
                pass

            def write(self, table, e):
                mock_writer_instance.write(table, e)

        with (
            patch("scripts.sync_ops._OUTBOX_DIR", tmp_path),
            patch.dict(
                "sys.modules",
                {"scripts.ops_writer": MagicMock(OpsWriter=_FakeOpsWriter)},
            ),
        ):
            from scripts import sync_ops

            result = sync_ops.drain()

        assert result.get("ops_decisions") == 1
        mock_writer_instance.write.assert_called_once_with("ops_decisions", entry)
        assert not outfile.exists()

    def test_drain_write_failure_keeps_file(self, tmp_path):
        """If OpsWriter.write() raises, the file is NOT deleted (retry next time)."""
        outbox_dir = tmp_path / "ops_recommendations"
        outbox_dir.mkdir(parents=True)
        entry = {"id": "rec-002"}
        outfile = outbox_dir / "entry.jsonl"
        outfile.write_text(json.dumps(entry) + "\n", encoding="utf-8")

        class _FailingOpsWriter:
            def __init__(self):
                pass

            def write(self, table, e):
                raise RuntimeError("S3 failure")

        with (
            patch("scripts.sync_ops._OUTBOX_DIR", tmp_path),
            patch.dict(
                "sys.modules",
                {"scripts.ops_writer": MagicMock(OpsWriter=_FailingOpsWriter)},
            ),
        ):
            from scripts import sync_ops

            result = sync_ops.drain()

        # File should still exist since write failed
        assert outfile.exists()
        assert result == {}


# ---------------------------------------------------------------------------
# pull() tests
# ---------------------------------------------------------------------------


class TestPull:
    def test_pull_sso_expired_returns_empty(self):
        """When reader fails and SSO is expired, _rebuild_local_cache() returns {}."""
        _bypass = MagicMock()
        _bypass._bucket.return_value = ""
        with (
            patch("scripts.sync_ops._pull_via_reader", return_value=None),
            patch("scripts.sync_ops.check_sso", return_value=False),
            patch.dict(
                "sys.modules",
                {"scripts.ops_writer": MagicMock(OpsWriter=lambda: _bypass, STAGING_PREFIX="staging")},
            ),
        ):
            from scripts.sync_ops import _rebuild_local_cache

            result = _rebuild_local_cache()
        assert result == {}

    def test_pull_queries_athena_writes_local_files(self, tmp_path):
        """Athena fallback: _rebuild_local_cache() writes rows when reader fails."""
        mock_athena = MagicMock()
        mock_athena.start_query_execution.return_value = {"QueryExecutionId": "qid-001"}
        mock_athena.get_query_execution.return_value = {"QueryExecution": {"Status": {"State": "SUCCEEDED"}}}
        # Simulate paginator with header row + one data row (all required fields included)
        mock_page = {
            "ResultSet": {
                "Rows": [
                    {
                        "Data": [
                            {"VarCharValue": "id"},
                            {"VarCharValue": "status"},
                            {"VarCharValue": "title"},
                            {"VarCharValue": "source"},
                            {"VarCharValue": "effort"},
                            {"VarCharValue": "priority"},
                            {"VarCharValue": "file"},
                            {"VarCharValue": "context"},
                            {"VarCharValue": "acceptance"},
                        ]
                    },
                    {
                        "Data": [
                            {"VarCharValue": "rec-001"},
                            {"VarCharValue": "open"},
                            {"VarCharValue": "Test rec"},
                            {"VarCharValue": "manual"},
                            {"VarCharValue": "S"},
                            {"VarCharValue": "Low"},
                            {"VarCharValue": "scripts/test.py"},
                            {"VarCharValue": "context text"},
                            {"VarCharValue": "tests pass"},
                        ]
                    },
                ]
            }
        }
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [mock_page]
        mock_athena.get_paginator.return_value = mock_paginator

        mock_session = MagicMock()
        mock_session.client.return_value = mock_athena

        local_file = tmp_path / ".recommendations-log.jsonl"
        _bypass = MagicMock()
        _bypass._bucket.return_value = ""

        with (
            patch("scripts.sync_ops._pull_via_reader", return_value=None),
            patch("scripts.sync_ops.check_sso", return_value=True),
            patch("scripts.sync_ops._LOGS_DIR", tmp_path),
            patch("scripts.sync_ops._TABLE_TO_VIEW", {"ops_recommendations": "ops_recommendations_current"}),
            patch("scripts.sync_ops._TABLE_TO_LOCAL", {"ops_recommendations": ".recommendations-log.jsonl"}),
            patch.dict(
                "sys.modules",
                {
                    "boto3": MagicMock(Session=MagicMock(return_value=mock_session)),
                    "scripts.ops_writer": MagicMock(OpsWriter=lambda: _bypass, STAGING_PREFIX="staging"),
                },
            ),
            patch("time.sleep"),
        ):
            from scripts import sync_ops

            result = sync_ops._rebuild_local_cache()

        assert result.get("ops_recommendations") == 1
        assert local_file.exists()
        saved = json.loads(local_file.read_text(encoding="utf-8").strip())
        assert saved["id"] == "rec-001"

    def test_pull_reader_path_writes_local_files(self, tmp_path):
        """Reader path: _rebuild_local_cache() uses reader rows directly when reader succeeds."""
        local_file = tmp_path / ".recommendations-log.jsonl"
        _bypass = MagicMock()
        _bypass._bucket.return_value = ""

        reader_data = [
            {
                "id": "rec-001",
                "status": "open",
                "title": "Reader test",
                "source": "manual",
                "effort": "S",
                "priority": "Low",
            }
        ]

        with (
            patch("scripts.sync_ops._pull_via_reader", return_value=reader_data),
            patch("scripts.sync_ops._LOGS_DIR", tmp_path),
            patch("scripts.sync_ops._TABLE_TO_VIEW", {"ops_recommendations": "ops_recommendations_current"}),
            patch("scripts.sync_ops._TABLE_TO_LOCAL", {"ops_recommendations": ".recommendations-log.jsonl"}),
            patch.dict(
                "sys.modules",
                {"scripts.ops_writer": MagicMock(OpsWriter=lambda: _bypass, STAGING_PREFIX="staging")},
            ),
        ):
            from scripts import sync_ops

            result = sync_ops._rebuild_local_cache()

        assert result.get("ops_recommendations") == 1
        assert local_file.exists()
        saved = json.loads(local_file.read_text(encoding="utf-8").strip())
        assert saved["id"] == "rec-001"

    def test_pull_reader_fallback_to_athena_on_reader_failure(self, tmp_path):
        """When reader returns None, _rebuild_local_cache() falls back to Athena."""
        mock_athena = MagicMock()
        mock_athena.start_query_execution.return_value = {"QueryExecutionId": "qid-fbk"}
        mock_athena.get_query_execution.return_value = {"QueryExecution": {"Status": {"State": "SUCCEEDED"}}}
        mock_page = {
            "ResultSet": {
                "Rows": [
                    {
                        "Data": [
                            {"VarCharValue": "id"},
                            {"VarCharValue": "title"},
                            {"VarCharValue": "source"},
                            {"VarCharValue": "effort"},
                            {"VarCharValue": "priority"},
                        ]
                    },
                    {
                        "Data": [
                            {"VarCharValue": "rec-fbk"},
                            {"VarCharValue": "Fallback rec"},
                            {"VarCharValue": "manual"},
                            {"VarCharValue": "S"},
                            {"VarCharValue": "Low"},
                        ]
                    },
                ]
            }
        }
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [mock_page]
        mock_athena.get_paginator.return_value = mock_paginator
        mock_session = MagicMock()
        mock_session.client.return_value = mock_athena
        local_file = tmp_path / ".recommendations-log.jsonl"
        _bypass = MagicMock()
        _bypass._bucket.return_value = ""

        with (
            patch("scripts.sync_ops._pull_via_reader", return_value=None),
            patch("scripts.sync_ops.check_sso", return_value=True),
            patch("scripts.sync_ops._LOGS_DIR", tmp_path),
            patch("scripts.sync_ops._TABLE_TO_VIEW", {"ops_recommendations": "ops_recommendations_current"}),
            patch("scripts.sync_ops._TABLE_TO_LOCAL", {"ops_recommendations": ".recommendations-log.jsonl"}),
            patch.dict(
                "sys.modules",
                {
                    "boto3": MagicMock(Session=MagicMock(return_value=mock_session)),
                    "scripts.ops_writer": MagicMock(OpsWriter=lambda: _bypass, STAGING_PREFIX="staging"),
                },
            ),
            patch("time.sleep"),
        ):
            from scripts import sync_ops

            result = sync_ops._rebuild_local_cache()

        assert result.get("ops_recommendations") == 1
        saved = json.loads(local_file.read_text(encoding="utf-8").strip())
        assert saved["id"] == "rec-fbk"

    def test_pull_athena_failure_continues_to_next_table(self, tmp_path):
        """Athena fallback: _rebuild_local_cache() continues to next table when Athena fails."""
        mock_athena = MagicMock()
        mock_athena.start_query_execution.side_effect = [
            Exception("Athena unavailable"),
            {"QueryExecutionId": "qid-002"},
        ]
        mock_athena.get_query_execution.return_value = {"QueryExecution": {"Status": {"State": "SUCCEEDED"}}}
        mock_page = {
            "ResultSet": {
                "Rows": [
                    {"Data": [{"VarCharValue": "id"}]},
                    {"Data": [{"VarCharValue": "plan-001"}]},
                ]
            }
        }
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [mock_page]
        mock_athena.get_paginator.return_value = mock_paginator

        mock_session = MagicMock()
        mock_session.client.return_value = mock_athena
        _bypass = MagicMock()
        _bypass._bucket.return_value = ""

        with (
            patch("scripts.sync_ops._pull_via_reader", return_value=None),
            patch("scripts.sync_ops.check_sso", return_value=True),
            patch("scripts.sync_ops._LOGS_DIR", tmp_path),
            patch(
                "scripts.sync_ops._TABLE_TO_VIEW",
                {
                    "ops_recommendations": "ops_recommendations_current",
                    "ops_execution_plans": "ops_execution_plans",
                },
            ),
            patch(
                "scripts.sync_ops._TABLE_TO_LOCAL",
                {
                    "ops_recommendations": ".recommendations-log.jsonl",
                    "ops_execution_plans": ".execution-plans.jsonl",
                },
            ),
            patch.dict(
                "sys.modules",
                {
                    "boto3": MagicMock(Session=MagicMock(return_value=mock_session)),
                    "scripts.ops_writer": MagicMock(OpsWriter=lambda: _bypass, STAGING_PREFIX="staging"),
                },
            ),
            patch("time.sleep"),
        ):
            from scripts import sync_ops

            result = sync_ops._rebuild_local_cache()

        # Second table should have succeeded
        assert result.get("ops_execution_plans") == 1

    def test_pull_coerces_ops_recommendations_array_fields(self, tmp_path):
        """Athena fallback: coercion applied for VarChar array fields (reader not available)."""
        mock_athena = MagicMock()
        mock_athena.start_query_execution.return_value = {"QueryExecutionId": "qid-coerce"}
        mock_athena.get_query_execution.return_value = {"QueryExecution": {"Status": {"State": "SUCCEEDED"}}}
        mock_page = {
            "ResultSet": {
                "Rows": [
                    {
                        "Data": [
                            {"VarCharValue": "id"},
                            {"VarCharValue": "dependencies"},
                            {"VarCharValue": "tags"},
                            {"VarCharValue": "execution_steps"},
                            {"VarCharValue": "title"},
                            {"VarCharValue": "source"},
                            {"VarCharValue": "effort"},
                            {"VarCharValue": "priority"},
                            {"VarCharValue": "file"},
                            {"VarCharValue": "context"},
                            {"VarCharValue": "acceptance"},
                        ]
                    },
                    {
                        "Data": [
                            {"VarCharValue": "rec-001"},
                            {"VarCharValue": "[dep-001, dep-002]"},
                            {"VarCharValue": "[]"},
                            {"VarCharValue": "3"},
                            {"VarCharValue": "Test rec"},
                            {"VarCharValue": "manual"},
                            {"VarCharValue": "S"},
                            {"VarCharValue": "Low"},
                            {"VarCharValue": "scripts/test.py"},
                            {"VarCharValue": "context text"},
                            {"VarCharValue": "tests pass"},
                        ]
                    },
                ]
            }
        }
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [mock_page]
        mock_athena.get_paginator.return_value = mock_paginator
        mock_session = MagicMock()
        mock_session.client.return_value = mock_athena
        local_file = tmp_path / ".recommendations-log.jsonl"
        _bypass = MagicMock()
        _bypass._bucket.return_value = ""
        with (
            patch("scripts.sync_ops._pull_via_reader", return_value=None),
            patch("scripts.sync_ops.check_sso", return_value=True),
            patch("scripts.sync_ops._LOGS_DIR", tmp_path),
            patch("scripts.sync_ops._TABLE_TO_VIEW", {"ops_recommendations": "ops_recommendations_current"}),
            patch("scripts.sync_ops._TABLE_TO_LOCAL", {"ops_recommendations": ".recommendations-log.jsonl"}),
            patch.dict(
                "sys.modules",
                {
                    "boto3": MagicMock(Session=MagicMock(return_value=mock_session)),
                    "scripts.ops_writer": MagicMock(OpsWriter=lambda: _bypass, STAGING_PREFIX="staging"),
                },
            ),
            patch("time.sleep"),
        ):
            from scripts import sync_ops

            sync_ops._rebuild_local_cache()
        saved = json.loads(local_file.read_text(encoding="utf-8").strip())
        assert saved["dependencies"] == ["dep-001", "dep-002"]
        assert saved["tags"] == []
        assert saved["execution_steps"] == 3

    def test_pull_strips_scd2_view_columns_from_rows(self, tmp_path):
        """Athena fallback: _rn and row_num columns stripped from rows in local JSONL."""
        mock_athena = MagicMock()
        mock_athena.start_query_execution.return_value = {"QueryExecutionId": "qid-strip"}
        mock_athena.get_query_execution.return_value = {"QueryExecution": {"Status": {"State": "SUCCEEDED"}}}
        # Athena returns a row that includes view-only SCD2 dedup columns plus all required fields
        mock_page = {
            "ResultSet": {
                "Rows": [
                    {
                        "Data": [
                            {"VarCharValue": "id"},
                            {"VarCharValue": "status"},
                            {"VarCharValue": "_rn"},
                            {"VarCharValue": "row_num"},
                            {"VarCharValue": "title"},
                            {"VarCharValue": "source"},
                            {"VarCharValue": "effort"},
                            {"VarCharValue": "priority"},
                            {"VarCharValue": "file"},
                            {"VarCharValue": "context"},
                            {"VarCharValue": "acceptance"},
                        ]
                    },
                    {
                        "Data": [
                            {"VarCharValue": "rec-001"},
                            {"VarCharValue": "open"},
                            {"VarCharValue": "1"},
                            {"VarCharValue": "1"},
                            {"VarCharValue": "Test rec"},
                            {"VarCharValue": "manual"},
                            {"VarCharValue": "S"},
                            {"VarCharValue": "Low"},
                            {"VarCharValue": "scripts/test.py"},
                            {"VarCharValue": "context text"},
                            {"VarCharValue": "tests pass"},
                        ]
                    },
                ]
            }
        }
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [mock_page]
        mock_athena.get_paginator.return_value = mock_paginator

        mock_session = MagicMock()
        mock_session.client.return_value = mock_athena

        local_file = tmp_path / ".recommendations-log.jsonl"
        _bypass = MagicMock()
        _bypass._bucket.return_value = ""
        with (
            patch("scripts.sync_ops._pull_via_reader", return_value=None),
            patch("scripts.sync_ops.check_sso", return_value=True),
            patch("scripts.sync_ops._LOGS_DIR", tmp_path),
            patch("scripts.sync_ops._TABLE_TO_VIEW", {"ops_recommendations": "ops_recommendations_current"}),
            patch("scripts.sync_ops._TABLE_TO_LOCAL", {"ops_recommendations": ".recommendations-log.jsonl"}),
            patch.dict(
                "sys.modules",
                {
                    "boto3": MagicMock(Session=MagicMock(return_value=mock_session)),
                    "scripts.ops_writer": MagicMock(OpsWriter=lambda: _bypass, STAGING_PREFIX="staging"),
                },
            ),
            patch("time.sleep"),
        ):
            from scripts import sync_ops

            sync_ops._rebuild_local_cache()

        assert local_file.exists()
        saved = json.loads(local_file.read_text(encoding="utf-8").strip())
        assert "_rn" not in saved, "_rn must be stripped by _rebuild_local_cache()"
        assert "row_num" not in saved, "row_num must be stripped by _rebuild_local_cache()"
        assert saved["id"] == "rec-001"

    def test_pull_rejects_hollow_ops_recommendations_row(self, tmp_path):
        """Athena fallback: hollow rows (missing required fields) are rejected and logged."""
        mock_athena = MagicMock()
        mock_athena.start_query_execution.return_value = {"QueryExecutionId": "qid-hollow"}
        mock_athena.get_query_execution.return_value = {"QueryExecution": {"Status": {"State": "SUCCEEDED"}}}
        # Row has id but empty title/source/effort/priority -- hollow record
        mock_page = {
            "ResultSet": {
                "Rows": [
                    {"Data": [{"VarCharValue": "id"}, {"VarCharValue": "title"}, {"VarCharValue": "source"}]},
                    {"Data": [{"VarCharValue": "rec-hollow"}, {"VarCharValue": ""}, {"VarCharValue": ""}]},
                ]
            }
        }
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [mock_page]
        mock_athena.get_paginator.return_value = mock_paginator
        mock_session = MagicMock()
        mock_session.client.return_value = mock_athena
        local_file = tmp_path / ".recommendations-log.jsonl"
        reject_log = tmp_path / "debug" / "dq-sync-rejects.jsonl"
        _bypass = MagicMock()
        _bypass._bucket.return_value = ""

        with (
            patch("scripts.sync_ops._pull_via_reader", return_value=None),
            patch("scripts.sync_ops.check_sso", return_value=True),
            patch("scripts.sync_ops._LOGS_DIR", tmp_path),
            patch("scripts.sync_ops._SYNC_REJECTS_LOG", reject_log),
            patch("scripts.sync_ops._TABLE_TO_VIEW", {"ops_recommendations": "ops_recommendations_current"}),
            patch("scripts.sync_ops._TABLE_TO_LOCAL", {"ops_recommendations": ".recommendations-log.jsonl"}),
            patch.dict(
                "sys.modules",
                {
                    "boto3": MagicMock(Session=MagicMock(return_value=mock_session)),
                    "scripts.ops_writer": MagicMock(OpsWriter=lambda: _bypass, STAGING_PREFIX="staging"),
                },
            ),
            patch("time.sleep"),
        ):
            from scripts import sync_ops

            result = sync_ops._rebuild_local_cache()

        # Hollow row must be rejected -- local JSONL should be empty or not written
        assert result.get("ops_recommendations") == 0
        assert not local_file.exists() or local_file.read_text(encoding="utf-8").strip() == ""
        # Reject log must capture the hollow row
        assert reject_log.exists()
        reject_entry = json.loads(reject_log.read_text(encoding="utf-8").strip())
        assert reject_entry["row"]["id"] == "rec-hollow"
        assert "title" in reject_entry["reason"] or "source" in reject_entry["reason"]

    def test_coerce_rows_list_handles_reader_typed_values(self) -> None:
        """_coerce_rows_list() tolerates already-typed values from the reader."""
        from scripts.sync_ops import _coerce_rows_list

        reader_row = {
            "id": "rec-001",
            "dependencies": ["dep-001"],
            "tags": [],
            "execution_steps": 3,
            "automatable": True,
            "title": "Test",
            "source": "manual",
            "effort": "S",
            "priority": "Low",
        }
        rows = _coerce_rows_list("ops_recommendations", [reader_row])
        assert len(rows) == 1
        assert rows[0]["id"] == "rec-001"
        assert rows[0]["execution_steps"] == 3

    def test_write_rows_to_local_creates_jsonl(self, tmp_path) -> None:
        """_write_rows_to_local() writes rows as JSONL and returns count."""
        rows = [{"id": "rec-001", "status": "open"}, {"id": "rec-002", "status": "closed"}]
        with patch("scripts.sync_ops._LOGS_DIR", tmp_path):
            from scripts import sync_ops

            count = sync_ops._write_rows_to_local("ops_recommendations", rows, ".recs.jsonl")

        assert count == 2
        written = list((tmp_path / ".recs.jsonl").read_text(encoding="utf-8").splitlines())
        assert len(written) == 2
        assert json.loads(written[0])["id"] == "rec-001"

    def test_pull_via_reader_returns_none_on_exception(self) -> None:
        """_pull_via_reader() returns None when DuckDBIcebergReader raises."""
        with patch(
            "src.common.iceberg_reader.DuckDBIcebergReader.current_state",
            side_effect=RuntimeError("catalog down"),
        ):
            from scripts.sync_ops import _pull_via_reader

            result = _pull_via_reader("ops_recommendations")
        assert result is None

    def test_pull_single_table_uses_reader_first(self, tmp_path) -> None:
        """_pull_single_table() uses reader rows when reader succeeds."""
        reader_data = [
            {
                "id": "rec-rdr",
                "status": "open",
                "title": "Reader row",
                "source": "manual",
                "effort": "S",
                "priority": "Low",
            }
        ]
        with (
            patch("scripts.sync_ops._pull_via_reader", return_value=reader_data),
            patch("scripts.sync_ops._LOGS_DIR", tmp_path),
            patch("scripts.sync_ops._TABLE_TO_LOCAL", {"ops_recommendations": ".recs.jsonl"}),
        ):
            from scripts import sync_ops

            count = sync_ops._pull_single_table("ops_recommendations")

        assert count == 1
        saved = json.loads((tmp_path / ".recs.jsonl").read_text(encoding="utf-8").strip())
        assert saved["id"] == "rec-rdr"


# ---------------------------------------------------------------------------
# sync() tests
# ---------------------------------------------------------------------------


class TestSync:
    def test_sync_calls_drain_then_pull(self):
        """sync() calls drain() then _rebuild_local_cache() and returns combined result."""
        with (
            patch("scripts.sync_ops.drain", return_value={"ops_recommendations": 2}) as mock_drain,
            patch("scripts.sync_ops._rebuild_local_cache", return_value={"ops_recommendations": 50}) as mock_rebuild,
        ):
            from scripts.sync_ops import sync

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
            patch("scripts.sync_ops.drain", side_effect=fake_drain),
            patch("scripts.sync_ops._rebuild_local_cache", side_effect=fake_rebuild),
        ):
            from scripts.sync_ops import sync

            sync()

        assert call_order == ["drain", "pull"]


# ---------------------------------------------------------------------------
# outbox_summary() tests
# ---------------------------------------------------------------------------


class TestOutboxSummary:
    def test_no_outbox_returns_empty(self, tmp_path):
        """outbox_summary() returns {} when outbox dir does not exist."""
        with patch("scripts.sync_ops._OUTBOX_DIR", tmp_path / "nonexistent"):
            from scripts.sync_ops import outbox_summary

            result = outbox_summary()
        assert result == {}

    def test_counts_files_per_table(self, tmp_path):
        """outbox_summary() counts files in each table subdirectory."""
        (tmp_path / "ops_recommendations").mkdir()
        for i in range(3):
            (tmp_path / "ops_recommendations" / f"entry-{i}.jsonl").write_text("{}", encoding="utf-8")
        (tmp_path / "ops_execution_plans").mkdir()
        (tmp_path / "ops_execution_plans" / "plan.jsonl").write_text("{}", encoding="utf-8")

        with patch("scripts.sync_ops._OUTBOX_DIR", tmp_path):
            from scripts.sync_ops import outbox_summary

            result = outbox_summary()

        assert result["ops_recommendations"] == 3
        assert result["ops_execution_plans"] == 1

    def test_empty_table_dir_excluded(self, tmp_path):
        """outbox_summary() does not include tables with 0 files."""
        (tmp_path / "ops_recommendations").mkdir()
        # No files in dir

        with patch("scripts.sync_ops._OUTBOX_DIR", tmp_path):
            from scripts.sync_ops import outbox_summary

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
            [sys.executable, "-m", "scripts.sync_ops", "--help"],
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

        import scripts.sync_ops as _sync_ops

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
        from scripts.sync_ops import _TABLE_TO_LOCAL, _TABLE_TO_VIEW

        for table in self._TELEMETRY_TABLES:
            assert table not in _TABLE_TO_LOCAL, f"{table} should be removed from _TABLE_TO_LOCAL"
            assert table not in _TABLE_TO_VIEW, f"{table} should be removed from _TABLE_TO_VIEW"

    def test_non_migrated_ops_tables_absent(self):
        """ops_session_log and ops_execution_plans are not migrated and must be absent."""
        from scripts.sync_ops import _TABLE_TO_LOCAL, _TABLE_TO_VIEW

        for table in self._REMOVED_OPS_TABLES:
            assert table not in _TABLE_TO_LOCAL
            assert table not in _TABLE_TO_VIEW

    def test_migrated_ops_tables_present(self):
        """ops_decisions and ops_priority_queue remain in _TABLE_TO_VIEW.

        ops_recommendations excluded (DuckLake, Decision 81 cl.7).
        """
        from scripts.sync_ops import _TABLE_TO_LOCAL, _TABLE_TO_VIEW

        # ops_recommendations uses DuckLake reader only -- excluded from Athena view map
        assert set(_TABLE_TO_VIEW) == {"ops_decisions", "ops_priority_queue"}
        # _TABLE_TO_LOCAL still covers all three (local cache updated from DuckLake for recs, Athena for others)
        assert set(_TABLE_TO_LOCAL) == {"ops_recommendations", "ops_decisions", "ops_priority_queue"}
        assert _TABLE_TO_VIEW["ops_decisions"] == "ops_decisions_current"
        assert _TABLE_TO_VIEW["ops_priority_queue"] == "ops_priority_queue_current"

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
            patch("scripts.sync_ops._OUTBOX_DIR", tmp_path),
            patch.dict(
                "sys.modules",
                {"scripts.ops_writer": MagicMock(OpsWriter=_FakeOpsWriter)},
            ),
        ):
            from scripts import sync_ops

            result = sync_ops.drain()

        assert result.get("telemetry_sessions") == 1
        mock_writer_instance.write.assert_called_once_with("telemetry_sessions", entry)
        assert not outfile.exists()


# ---------------------------------------------------------------------------
# _coerce_ops_rec_row() tests
# ---------------------------------------------------------------------------


class TestCoerceOpsRecRow:
    def test_coerces_bracket_array_fields_to_list(self):
        """Athena bracket-array strings are split into Python lists."""
        from scripts.sync_ops import _coerce_ops_rec_row

        row = {"id": "rec-001", "dependencies": "[dep-001, dep-002]", "tags": "[alpha, beta]", "execution_steps": "3"}
        result = _coerce_ops_rec_row(row)
        assert result["dependencies"] == ["dep-001", "dep-002"]
        assert result["tags"] == ["alpha", "beta"]
        assert result["execution_steps"] == 3

    def test_coerces_empty_bracket_to_empty_list(self):
        """An empty bracket string '[]' becomes an empty Python list."""
        from scripts.sync_ops import _coerce_ops_rec_row

        row = {"id": "rec-001", "dependencies": "[]", "tags": "[]", "execution_steps": ""}
        result = _coerce_ops_rec_row(row)
        assert result["dependencies"] == []
        assert result["tags"] == []
        assert result["execution_steps"] is None

    def test_coerces_null_varchar_to_empty_list(self):
        """A null VarChar '' for array fields becomes an empty list."""
        from scripts.sync_ops import _coerce_ops_rec_row

        row = {"id": "rec-001", "dependencies": "", "tags": ""}
        result = _coerce_ops_rec_row(row)
        assert result["dependencies"] == []
        assert result["tags"] == []

    def test_coerces_execution_steps_integer_string(self):
        """A numeric string for execution_steps becomes an int."""
        from scripts.sync_ops import _coerce_ops_rec_row

        row = {"id": "rec-001", "execution_steps": "5"}
        result = _coerce_ops_rec_row(row)
        assert result["execution_steps"] == 5

    def test_passes_through_int_execution_steps_unchanged(self):
        """An already-int execution_steps value is not modified."""
        from scripts.sync_ops import _coerce_ops_rec_row

        row = {"id": "rec-001", "execution_steps": 7}
        result = _coerce_ops_rec_row(row)
        assert result["execution_steps"] == 7

    def test_handles_missing_fields_gracefully(self):
        """Rows without array/int fields get safe defaults, no KeyError."""
        from scripts.sync_ops import _coerce_ops_rec_row

        row = {"id": "rec-001", "status": "open"}
        result = _coerce_ops_rec_row(row)
        assert result["dependencies"] == []
        assert result["tags"] == []
        assert result["execution_steps"] is None

    def test_coerces_automatable_empty_string_to_none(self):
        """Athena NULL for automatable arrives as '' and must become None."""
        from scripts.sync_ops import _coerce_ops_rec_row

        row = {"id": "rec-001", "automatable": ""}
        result = _coerce_ops_rec_row(row)
        assert result["automatable"] is None

    def test_coerces_automatable_true_string_to_bool(self):
        """Athena boolean strings 'true'/'false' become Python booleans."""
        from scripts.sync_ops import _coerce_ops_rec_row

        assert _coerce_ops_rec_row({"id": "rec-001", "automatable": "true"})["automatable"] is True
        assert _coerce_ops_rec_row({"id": "rec-001", "automatable": "false"})["automatable"] is False

    def test_passes_through_bool_automatable_unchanged(self):
        """An already-bool automatable value is not modified."""
        from scripts.sync_ops import _coerce_ops_rec_row

        assert _coerce_ops_rec_row({"id": "rec-001", "automatable": True})["automatable"] is True
        assert _coerce_ops_rec_row({"id": "rec-001", "automatable": False})["automatable"] is False


# ---------------------------------------------------------------------------
# _coerce_athena_array() tests
# ---------------------------------------------------------------------------


class TestCoerceAthenaArray:
    def test_bracket_string_parses_to_list(self):
        """'[a, b]' parses to ['a', 'b']."""
        from scripts.sync_ops import _coerce_athena_array

        assert _coerce_athena_array("[a, b]") == ["a", "b"]

    def test_empty_bracket_returns_empty_list(self):
        """'[]' returns []."""
        from scripts.sync_ops import _coerce_athena_array

        assert _coerce_athena_array("[]") == []

    def test_empty_string_returns_empty_list(self):
        """Athena NULL ('')  returns []."""
        from scripts.sync_ops import _coerce_athena_array

        assert _coerce_athena_array("") == []

    def test_none_value_returns_empty_list(self):
        """None input returns []."""
        from scripts.sync_ops import _coerce_athena_array

        assert _coerce_athena_array(None) == []

    def test_scalar_string_wraps_in_list(self):
        """A plain string without brackets becomes a one-element list."""
        from scripts.sync_ops import _coerce_athena_array

        assert _coerce_athena_array("rec-001") == ["rec-001"]

    def test_int_elem_type_coerces_elements(self):
        """elem_type=int converts each element."""
        from scripts.sync_ops import _coerce_athena_array

        assert _coerce_athena_array("[1, 2, 3]", elem_type=int) == [1, 2, 3]

    def test_int_elem_type_invalid_element_skipped(self):
        """Invalid elements for the given elem_type are silently skipped."""
        from scripts.sync_ops import _coerce_athena_array

        assert _coerce_athena_array("[1, notanint, 3]", elem_type=int) == [1, 3]

    def test_scalar_int_elem_type_wraps(self):
        """A plain '5' with elem_type=int returns [5]."""
        from scripts.sync_ops import _coerce_athena_array

        assert _coerce_athena_array("5", elem_type=int) == [5]


# ---------------------------------------------------------------------------
# _coerce_ops_priority_queue_row() tests
# ---------------------------------------------------------------------------


class TestCoerceOpsPriorityQueueRow:
    def test_coerces_rank_string_to_int(self):
        from scripts.sync_ops import _coerce_ops_priority_queue_row

        row = {"rank": "3", "compound_with": "[]", "gates": "[]"}
        result = _coerce_ops_priority_queue_row(row)
        assert result["rank"] == 3
        assert result["compound_with"] == []
        assert result["gates"] == []

    def test_coerces_array_fields(self):
        from scripts.sync_ops import _coerce_ops_priority_queue_row

        row = {"rank": "1", "compound_with": "[rec-002, rec-003]", "gates": "[gate-a]"}
        result = _coerce_ops_priority_queue_row(row)
        assert result["compound_with"] == ["rec-002", "rec-003"]
        assert result["gates"] == ["gate-a"]

    def test_null_rank_becomes_none(self):
        from scripts.sync_ops import _coerce_ops_priority_queue_row

        row = {"rank": ""}
        result = _coerce_ops_priority_queue_row(row)
        assert result["rank"] is None


# ---------------------------------------------------------------------------
# _coerce_ops_decisions_row() tests
# ---------------------------------------------------------------------------


class TestCoerceOpsDecisionsRow:
    def test_coerces_decision_id_string_to_int(self):
        from scripts.sync_ops import _coerce_ops_decisions_row

        row = {"decision_id": "42", "related_decisions": "[]"}
        result = _coerce_ops_decisions_row(row)
        assert result["decision_id"] == 42
        assert result["related_decisions"] == []

    def test_coerces_related_decisions_array_to_int_list(self):
        from scripts.sync_ops import _coerce_ops_decisions_row

        row = {"decision_id": "1", "related_decisions": "[2, 3, 4]"}
        result = _coerce_ops_decisions_row(row)
        assert result["related_decisions"] == [2, 3, 4]

    def test_null_decision_id_becomes_none(self):
        from scripts.sync_ops import _coerce_ops_decisions_row

        row = {"decision_id": ""}
        result = _coerce_ops_decisions_row(row)
        assert result["decision_id"] is None

    def test_populates_id_from_decision_id_when_absent(self):
        """When id is absent, populates it as dec-NNN from decision_id (D11)."""
        from scripts.sync_ops import _coerce_ops_decisions_row

        row = {"decision_id": "37"}
        result = _coerce_ops_decisions_row(row)
        assert result["id"] == "dec-037"
        assert result["decision_id"] == 37

    def test_dual_write_violation_logs_reject(self):
        """Mismatched id/decision_id calls _write_decisions_sync_reject (D11)."""
        from unittest.mock import patch

        from scripts.sync_ops import _coerce_ops_decisions_row

        row = {"id": "dec-010", "decision_id": "99"}
        with patch("scripts.sync_ops._write_decisions_sync_reject") as mock_reject:
            _coerce_ops_decisions_row(row)
        mock_reject.assert_called_once()
        reason = mock_reject.call_args[0][1]
        assert "dual-write invariant" in reason

    def test_no_reject_when_invariant_holds(self):
        """Matched id/decision_id does not call _write_decisions_sync_reject (D11)."""
        from unittest.mock import patch

        from scripts.sync_ops import _coerce_ops_decisions_row

        row = {"id": "dec-042", "decision_id": "42"}
        with patch("scripts.sync_ops._write_decisions_sync_reject") as mock_reject:
            _coerce_ops_decisions_row(row)
        mock_reject.assert_not_called()


# ---------------------------------------------------------------------------
# _coerce_ops_session_log_row() tests
# ---------------------------------------------------------------------------


class TestCoerceOpsSessionLogRow:
    def test_coerces_array_fields(self):
        from scripts.sync_ops import _coerce_ops_session_log_row

        row = {"recs_attempted": "[rec-001, rec-002]", "recs_closed": "[rec-001]", "duration_minutes": "45"}
        result = _coerce_ops_session_log_row(row)
        assert result["recs_attempted"] == ["rec-001", "rec-002"]
        assert result["recs_closed"] == ["rec-001"]
        assert result["duration_minutes"] == 45

    def test_null_duration_becomes_none(self):
        from scripts.sync_ops import _coerce_ops_session_log_row

        row = {"duration_minutes": ""}
        result = _coerce_ops_session_log_row(row)
        assert result["duration_minutes"] is None

    def test_empty_array_fields_return_empty_list(self):
        from scripts.sync_ops import _coerce_ops_session_log_row

        row = {"recs_attempted": "", "recs_closed": "[]"}
        result = _coerce_ops_session_log_row(row)
        assert result["recs_attempted"] == []
        assert result["recs_closed"] == []


class TestPipelineConsolidation:
    """Tests for pipeline consolidation changes (Decision 69)."""

    def test_coerce_ops_rec_row_rejects_dec_ids(self):
        """_coerce_ops_rec_row returns None and writes a reject log for dec-* prefixed IDs."""
        from unittest.mock import patch

        from scripts.sync_ops import _coerce_ops_rec_row

        row = {"id": "dec-42", "title": "Test", "source": "manual", "effort": "S", "priority": "Low"}
        with patch("scripts.sync_ops._write_sync_reject") as mock_reject:
            result = _coerce_ops_rec_row(row)

        assert result is None
        mock_reject.assert_called_once()
        call_args = mock_reject.call_args[0]
        assert call_args[0] is row
        assert "invalid id prefix" in call_args[1]

    def test_coerce_ops_rec_row_accepts_valid_prefixes(self):
        """_coerce_ops_rec_row returns the row for rec-, agent-, and test- prefixes."""
        from scripts.sync_ops import _coerce_ops_rec_row

        for valid_id in ("rec-001", "agent-abc", "test-xyz"):
            row = {"id": valid_id, "dependencies": "", "tags": "", "execution_steps": "", "automatable": ""}
            result = _coerce_ops_rec_row(row)
            assert result is not None, f"expected non-None for id={valid_id!r}"
            assert result["id"] == valid_id

    def test_drain_cli_removed(self):
        """Running `python -m scripts.sync_ops drain` exits non-zero (subcommand removed)."""
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, "-m", "scripts.sync_ops", "drain"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(Path(__file__).parent.parent),
        )
        assert result.returncode != 0

    def test_pull_cli_removed(self):
        """Running `python -m scripts.sync_ops pull` exits non-zero (subcommand removed)."""
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, "-m", "scripts.sync_ops", "pull"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(Path(__file__).parent.parent),
        )
        assert result.returncode != 0


def test_coerce_athena_array_handles_native_list():
    """DuckLake reader returns native lists; the coercion returns them element-typed (not re-parsed)."""
    from scripts.sync_ops import _coerce_athena_array

    assert _coerce_athena_array(["rec-1", "rec-2"]) == ["rec-1", "rec-2"]
    assert _coerce_athena_array([1, 2, 3], elem_type=int) == [1, 2, 3]
    assert _coerce_athena_array([None, "x"]) == ["x"]
    # Athena string form still parses
    assert _coerce_athena_array("[a, b]") == ["a", "b"]


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
            patch("scripts.sync_ops._OUTBOX_DIR", tmp_path),
            patch.dict(
                "sys.modules",
                {"scripts.ops_writer": MagicMock(OpsWriter=_FakeOpsWriter)},
            ),
        ):
            from scripts import sync_ops

            result = sync_ops.drain()

        # ops_recommendations outbox entries must NOT be written via OpsWriter
        assert not any(t == "ops_recommendations" for t, _ in write_calls), (
            "drain() must not route ops_recommendations through OpsWriter (Decision 81 cl.7)"
        )
        # Outbox file for recs is NOT deleted (was never processed)
        assert outbox_file.exists(), "recs outbox file should not be deleted (was skipped)"
        # drain() reports 0 for ops_recommendations
        assert result.get("ops_recommendations", 0) == 0
