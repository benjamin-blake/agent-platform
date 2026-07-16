"""Tests for scripts/ops_writer.py -- compact() + compact_all() DataFrame/timestamp concern.

rec-2709 Wave 9: split from the former tests/test_ops_writer.py monolith. This is the only
concern-split module that references a real heavy dependency (pandas, via three lazy
`import pandas as pd` statements inside the moved test methods) -- the module-level
`import pandas` marker below proactively defers this file to the full presubmit tier's
collectability partition (pandas is excluded from requirements-fast.txt).
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pandas  # noqa: F401

from tests.fixtures.ops_writer_helpers import make_writer as _make_writer


class TestOpsWriterCompact:
    """Tests for OpsWriter.compact()."""

    def _make_mock_client_with_staging(self, entries: list[dict], table: str = "ops_execution_plans") -> MagicMock:
        """Build a mock boto3 client that returns *entries* as staging files."""
        mock_client = MagicMock()

        line_bytes = b"\n".join(json.dumps(e).encode() for e in entries)

        # list_objects_v2 paginator returns one page with one object
        mock_paginator = MagicMock()
        mock_page = {"Contents": [{"Key": f"staging/{table}/dt=2026-04-20/batch-abc.jsonl"}]}
        mock_paginator.paginate.return_value = [mock_page]
        mock_client.get_paginator.return_value = mock_paginator

        mock_client.get_object.return_value = {"Body": MagicMock(read=MagicMock(return_value=line_bytes))}
        return mock_client

    def test_compact_reads_staging_creates_dataframe_calls_awswrangler(self):
        """compact() reads staging files, creates DataFrame, calls wr.athena.to_iceberg."""
        entries = [
            {
                "id": "ep-001",
                "created_timestamp": "2026-04-20T10:00:00+00:00",
                "last_updated_timestamp": "2026-04-20T10:00:00+00:00",
            },
        ]
        mock_client = self._make_mock_client_with_staging(entries)

        writer = _make_writer()
        writer._client = mock_client

        with (
            patch("scripts.ops_writer._AWR_AVAILABLE", True),
            patch("scripts.ops_writer._BOTO3_AVAILABLE", True),
            patch.object(writer, "_bucket", return_value="my-bucket"),
            patch.object(writer, "_is_test_env", return_value=False),
            patch.object(writer, "_get_boto3_session", return_value=MagicMock()),
            patch("scripts.ops_writer.wr") as mock_wr,
        ):
            count = writer.compact("ops_execution_plans", "2026-04-20")

        assert count == 1
        mock_wr.athena.to_iceberg.assert_called_once()
        call_kwargs = mock_wr.athena.to_iceberg.call_args[1]
        assert call_kwargs["database"] == "agent_platform"
        assert call_kwargs["table"] == "ops_execution_plans"
        assert call_kwargs["mode"] == "append"
        assert call_kwargs["workgroup"] == "agent-platform-production"

    def test_compact_deletes_staging_files_after_compaction(self):
        """compact() calls delete_object for each staging file after success."""
        entries = [
            {
                "id": "ep-001",
                "created_timestamp": "2026-04-20T10:00:00+00:00",
                "last_updated_timestamp": "2026-04-20T10:00:00+00:00",
            }
        ]
        mock_client = self._make_mock_client_with_staging(entries)

        writer = _make_writer()
        writer._client = mock_client

        with (
            patch("scripts.ops_writer._AWR_AVAILABLE", True),
            patch("scripts.ops_writer._BOTO3_AVAILABLE", True),
            patch.object(writer, "_bucket", return_value="my-bucket"),
            patch.object(writer, "_is_test_env", return_value=False),
            patch.object(writer, "_get_boto3_session", return_value=MagicMock()),
            patch("scripts.ops_writer.wr"),
        ):
            writer.compact("ops_execution_plans", "2026-04-20")

        mock_client.delete_object.assert_called_once_with(
            Bucket="my-bucket",
            Key="staging/ops_execution_plans/dt=2026-04-20/batch-abc.jsonl",
        )

    def test_compact_returns_zero_when_awswrangler_unavailable(self):
        """compact() returns 0 when awswrangler is not available."""
        writer = _make_writer()
        writer._client = MagicMock()

        with (
            patch("scripts.ops_writer._AWR_AVAILABLE", False),
            patch("scripts.ops_writer._BOTO3_AVAILABLE", True),
            patch.object(writer, "_bucket", return_value="my-bucket"),
            patch.object(writer, "_is_test_env", return_value=False),
        ):
            count = writer.compact("ops_recommendations", "2026-04-20")

        assert count == 0

    def test_compact_returns_zero_when_no_staging_files(self):
        """compact() returns 0 when the staging prefix has no objects."""
        mock_client = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"Contents": []}]
        mock_client.get_paginator.return_value = mock_paginator

        writer = _make_writer()
        writer._client = mock_client

        with (
            patch("scripts.ops_writer._AWR_AVAILABLE", True),
            patch("scripts.ops_writer._BOTO3_AVAILABLE", True),
            patch.object(writer, "_bucket", return_value="my-bucket"),
            patch.object(writer, "_is_test_env", return_value=False),
        ):
            count = writer.compact("ops_recommendations", "2026-04-20")

        assert count == 0

    def test_compact_returns_zero_no_content_key(self):
        """compact() returns 0 when paginator pages have no 'Contents' key."""
        mock_client = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{}]  # No 'Contents' key
        mock_client.get_paginator.return_value = mock_paginator

        writer = _make_writer()
        writer._client = mock_client

        with (
            patch("scripts.ops_writer._AWR_AVAILABLE", True),
            patch("scripts.ops_writer._BOTO3_AVAILABLE", True),
            patch.object(writer, "_bucket", return_value="my-bucket"),
            patch.object(writer, "_is_test_env", return_value=False),
        ):
            count = writer.compact("ops_recommendations", "2026-04-20")

        assert count == 0

    def test_compact_skips_when_test_env(self):
        """compact() returns 0 in test environment without calling S3."""
        writer = _make_writer()
        writer._client = MagicMock()

        with (
            patch("scripts.ops_writer._AWR_AVAILABLE", True),
            patch.object(writer, "_bucket", return_value="my-bucket"),
            patch.object(writer, "_is_test_env", return_value=True),
        ):
            count = writer.compact("ops_recommendations", "2026-04-20")

        assert count == 0
        writer._client.get_paginator.assert_not_called()

    def test_compact_handles_exception_gracefully(self):
        """compact() raises RuntimeError when an unexpected exception occurs during S3/Athena ops."""
        import pytest

        mock_client = MagicMock()
        mock_client.get_paginator.side_effect = RuntimeError("unexpected!")

        writer = _make_writer()
        writer._client = mock_client

        with (
            patch("scripts.ops_writer._AWR_AVAILABLE", True),
            patch("scripts.ops_writer._BOTO3_AVAILABLE", True),
            patch.object(writer, "_bucket", return_value="my-bucket"),
            patch.object(writer, "_is_test_env", return_value=False),
        ):
            with pytest.raises(RuntimeError, match="infrastructure failure"):
                writer.compact("ops_execution_plans", "2026-04-20")

    def test_compact_drops_scd2_view_columns_before_iceberg(self):
        """compact() strips _rn and row_num from the DataFrame before calling to_iceberg."""
        import pandas as pd

        entry = {"id": "ep-001", "_rn": "1", "row_num": 1}
        line_bytes = (json.dumps(entry) + "\n").encode()

        mock_client = MagicMock()
        mock_s3_paginator = MagicMock()
        mock_s3_paginator.paginate.return_value = [
            {"Contents": [{"Key": "staging/ops_execution_plans/dt=2026-04-20/batch-x.jsonl"}]}
        ]
        mock_client.get_paginator.return_value = mock_s3_paginator
        mock_client.get_object.return_value = {"Body": MagicMock(read=MagicMock(return_value=line_bytes))}

        writer = _make_writer()
        writer._client = mock_client

        captured: list[pd.DataFrame] = []

        def _capture_df(df, **kwargs):
            captured.append(df.copy())

        with (
            patch("scripts.ops_writer._AWR_AVAILABLE", True),
            patch("scripts.ops_writer._BOTO3_AVAILABLE", True),
            patch.object(writer, "_bucket", return_value="my-bucket"),
            patch.object(writer, "_is_test_env", return_value=False),
            patch.object(writer, "_get_boto3_session", return_value=MagicMock()),
            patch("scripts.ops_writer.wr") as mock_wr,
        ):
            mock_wr.athena.to_iceberg.side_effect = _capture_df
            writer.compact("ops_execution_plans", "2026-04-20")

        assert len(captured) == 1
        df = captured[0]
        assert "_rn" not in df.columns, "_rn must be stripped before to_iceberg"
        assert "row_num" not in df.columns, "row_num must be stripped before to_iceberg"


class TestOpsWriterCompactAll:
    """Tests for OpsWriter.compact_all()."""

    def test_compact_all_calls_compact_for_all_tables(self):
        """compact_all() calls compact() for each table in TABLE_NAMES (excludes ops_recommendations)."""
        from scripts.ops_writer import TABLE_NAMES

        writer = _make_writer()
        compact_calls: list[str] = []

        def _fake_compact(table, trade_date=None):
            compact_calls.append(table)
            return 0

        with patch.object(writer, "compact", side_effect=_fake_compact):
            result = writer.compact_all()

        assert sorted(compact_calls) == sorted(TABLE_NAMES)
        assert set(result.keys()) == set(TABLE_NAMES)

    def test_compact_all_returns_dict_of_row_counts(self):
        """compact_all() returns a dict mapping table name to rows compacted."""
        from scripts.ops_writer import TABLE_NAMES

        writer = _make_writer()
        call_seq = iter(range(len(TABLE_NAMES)))

        with patch.object(writer, "compact", side_effect=lambda t, trade_date=None: next(call_seq)):
            result = writer.compact_all()

        assert set(result.keys()) == set(TABLE_NAMES)
        assert sum(result.values()) == sum(range(len(TABLE_NAMES)))


class TestOpsWriterCompactAllIncludesTelemetry:
    """compact_all() covers all ops + telemetry tables (ops_recommendations excluded post-T2.19)."""

    def test_compact_all_includes_telemetry_tables(self):
        from scripts.ops_writer import TABLE_NAMES

        writer = _make_writer()
        compact_calls: list[str] = []

        def _fake_compact(table, trade_date=None):
            compact_calls.append(table)
            return 0

        with patch.object(writer, "compact", side_effect=_fake_compact):
            result = writer.compact_all()

        assert sorted(compact_calls) == sorted(TABLE_NAMES)
        assert len(TABLE_NAMES) == len(set(TABLE_NAMES))  # no duplicate table names
        required_tables = {
            "ops_execution_plans",
            "ops_session_log",
            "ops_decisions",
            "ops_priority_queue",
            "telemetry_sessions",
            "telemetry_phases",
            "telemetry_steps",
            "telemetry_process_events",
            "telemetry_model_calls",
            "telemetry_transcripts",
            "telemetry_agent_invocations",
        }
        assert required_tables.issubset(TABLE_NAMES)  # membership floor -- grows by addition only
        assert "ops_recommendations" not in TABLE_NAMES  # recs excluded (Decision 81 cl.7)
        assert "telemetry_sessions" in compact_calls
        assert "telemetry_agent_invocations" in compact_calls
        assert set(result.keys()) == set(TABLE_NAMES)


class TestOpsWriterCompactTimestampHandling:
    """compact() correctly converts timestamp columns and pre-fills missing ones.

    Covers the awswrangler + pandas 2.x datetime64 precision bug:
    - athena2pandas("timestamp") returns bare "datetime64", rejected by pandas 2.x.
    - compact() must convert ISO string timestamps to datetime64[ns] AFTER the
      null-col drop, so that pre-filled NaT columns survive to be seen by
      awswrangler as already-present (not missing).
    """

    def _make_mock_client_with_staging(self, entries: list[dict], table: str = "telemetry_sessions") -> MagicMock:
        import json as _json

        line_bytes = b"\n".join(_json.dumps(e).encode() for e in entries)
        mock_client = MagicMock()
        mock_paginator = MagicMock()
        mock_page = {"Contents": [{"Key": f"staging/{table}/trade_date=2026-04-24/batch-abc.jsonl"}]}
        mock_paginator.paginate.return_value = [mock_page]
        mock_client.get_paginator.return_value = mock_paginator
        mock_client.get_object.return_value = {"Body": MagicMock(read=MagicMock(return_value=line_bytes))}
        return mock_client

    def test_compact_converts_ingested_at_string_to_datetime(self):
        """compact() converts ingested_at from ISO string to datetime64[ns] before to_iceberg."""
        import pandas as pd

        entries = [
            {
                "session_id": "s1",
                "workflow": "executor",
                "outcome": "success",
                "started_at": "2026-04-24T10:00:00+00:00",
                "ingested_at": "2026-04-24T10:00:00+00:00",
                "trade_date": "2026-04-24",
                "process_event_count": 0,
                "rework_count": 0,
                "exception_count": 0,
                "execution_attempt": 1,
            }
        ]
        mock_client = self._make_mock_client_with_staging(entries)
        writer = _make_writer()
        writer._client = mock_client

        captured_df = {}

        def _capture_to_iceberg(df, **kwargs):
            captured_df["df"] = df.copy()

        with (
            patch("scripts.ops_writer._AWR_AVAILABLE", True),
            patch("scripts.ops_writer._BOTO3_AVAILABLE", True),
            patch.object(writer, "_bucket", return_value="my-bucket"),
            patch.object(writer, "_is_test_env", return_value=False),
            patch.object(writer, "_get_boto3_session", return_value=MagicMock()),
            patch("scripts.ops_writer.wr") as mock_wr,
        ):
            mock_wr.athena.to_iceberg.side_effect = _capture_to_iceberg
            writer.compact("telemetry_sessions", "2026-04-24")

        df = captured_df["df"]
        assert "ingested_at" in df.columns
        assert pd.api.types.is_datetime64_any_dtype(df["ingested_at"]), f"Expected datetime64, got {df['ingested_at'].dtype}"
        assert "started_at" in df.columns
        assert pd.api.types.is_datetime64_any_dtype(df["started_at"]), f"Expected datetime64, got {df['started_at'].dtype}"

    def test_compact_prefills_missing_timestamp_cols_with_nat_after_null_drop(self):
        """compact() pre-fills missing timestamp columns with NaT after the null-col drop.

        If NaT pre-fill happened before the null-col drop, the all-null columns would
        be dropped again and awswrangler would trigger the pandas 2.x datetime64
        precision error.
        """
        import pandas as pd

        # Record without ended_at (optional field)
        entries = [
            {
                "session_id": "s1",
                "workflow": "executor",
                "outcome": "success",
                "started_at": "2026-04-24T10:00:00+00:00",
                "ingested_at": "2026-04-24T10:00:00+00:00",
                "trade_date": "2026-04-24",
                "process_event_count": 0,
                "rework_count": 0,
                "exception_count": 0,
                "execution_attempt": 1,
            }
        ]
        mock_client = self._make_mock_client_with_staging(entries)
        writer = _make_writer()
        writer._client = mock_client

        captured_df = {}

        def _capture_to_iceberg(df, **kwargs):
            captured_df["df"] = df.copy()

        with (
            patch("scripts.ops_writer._AWR_AVAILABLE", True),
            patch("scripts.ops_writer._BOTO3_AVAILABLE", True),
            patch.object(writer, "_bucket", return_value="my-bucket"),
            patch.object(writer, "_is_test_env", return_value=False),
            patch.object(writer, "_get_boto3_session", return_value=MagicMock()),
            patch("scripts.ops_writer.wr") as mock_wr,
        ):
            mock_wr.athena.to_iceberg.side_effect = _capture_to_iceberg
            writer.compact("telemetry_sessions", "2026-04-24")

        df = captured_df["df"]
        # ended_at was missing from the record -- must be present as NaT (not absent)
        assert "ended_at" in df.columns, "ended_at should be pre-filled with NaT"
        assert pd.api.types.is_datetime64_any_dtype(df["ended_at"]), f"Expected datetime64, got {df['ended_at'].dtype}"
        assert df["ended_at"].isna().all(), "ended_at should be all-NaT for this batch"
