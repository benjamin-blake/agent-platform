"""Tests for scripts/ops_writer.py -- write() core + T2.19 recs-rejection concern.

rec-2709 Wave 9: split from the former tests/test_ops_writer.py monolith.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

# boto3 is required at RUNTIME by scripts.ops_writer.write() (the S3-staging path). Import it at
# MODULE scope -- even though it is only used indirectly -- so the fast tier's cheap --collect-only
# probe defers this file to the full tier (boto3 is excluded from requirements-fast.txt). Without
# this marker the S3-staging assertions fail in the fast tier ("boto3 unavailable -- staging
# skipped"), because ops_writer.write() short-circuits when boto3 cannot be imported.
import boto3  # noqa: F401

from tests.fixtures.ops_writer_helpers import VALID_REC as _VALID_REC
from tests.fixtures.ops_writer_helpers import make_writer as _make_writer


class TestOpsWriterWrite:
    """Tests for OpsWriter.write()."""

    def test_write_adds_created_timestamp_and_last_updated_timestamp(self):
        """write() injects created_timestamp and last_updated_timestamp into the staged entry."""
        mock_client = MagicMock()
        writer = _make_writer()
        writer._client = mock_client

        with (
            patch.dict("os.environ", {"S3_LOG_BUCKET": "test-bucket"}, clear=False),
            patch(
                "os.environ.get",
                side_effect=lambda k, d="": {
                    "S3_LOG_BUCKET": "test-bucket",
                    "PYTEST_CURRENT_TEST": "",
                    "AWS_PROFILE": "",
                }.get(k, d),
            ),
        ):
            # More direct approach: patch _bucket and _is_test_env
            pass

        # Use a simpler patch strategy
        writer2 = _make_writer()
        writer2._client = MagicMock()

        captured: list[dict] = []

        def _capture_put(**kwargs):
            captured.append(json.loads(kwargs["Body"].decode("utf-8")))

        writer2._client.put_object.side_effect = _capture_put

        with (
            patch.object(writer2, "_bucket", return_value="test-bucket"),
            patch.object(writer2, "_is_test_env", return_value=False),
        ):
            writer2.write("ops_decisions", {"id": "dec-042"})

        assert len(captured) == 1
        entry = captured[0]
        assert entry["id"] == "dec-042"
        assert "created_timestamp" in entry
        assert "last_updated_timestamp" in entry

    def test_write_maps_date_field_to_created_timestamp(self):
        """write() maps caller's 'date' field to 'created_timestamp' for ops tables."""
        writer = _make_writer()
        writer._client = MagicMock()

        captured: list[dict] = []

        def _capture_put(**kwargs):
            captured.append(json.loads(kwargs["Body"].decode("utf-8")))

        writer._client.put_object.side_effect = _capture_put

        with (
            patch.object(writer, "_bucket", return_value="test-bucket"),
            patch.object(writer, "_is_test_env", return_value=False),
        ):
            writer.write("ops_decisions", {"id": "dec-042", "date": "2026-04-01"})

        assert len(captured) == 1
        entry = captured[0]
        assert "date" not in entry, "date field should be removed from staged entry"
        assert entry.get("created_timestamp") == "2026-04-01", (
            f"expected created_timestamp='2026-04-01', got {entry.get('created_timestamp')}"
        )
        assert "last_updated_timestamp" in entry

    def test_write_calls_s3_put_object_with_correct_bucket_and_key_prefix(self):
        """write() calls put_object with correct bucket, staging key prefix."""
        writer = _make_writer()
        writer._client = MagicMock()

        with (
            patch.object(writer, "_bucket", return_value="my-bucket"),
            patch.object(writer, "_is_test_env", return_value=False),
        ):
            writer.write("ops_priority_queue", {"rec_id": "rec-1"})

        call_kwargs = writer._client.put_object.call_args[1]
        assert call_kwargs["Bucket"] == "my-bucket"
        key = call_kwargs["Key"]
        assert key.startswith("staging/ops_priority_queue/dt=")
        assert key.endswith(".jsonl")
        assert call_kwargs["ContentType"] == "application/x-ndjson"

    def test_write_skips_s3_when_bucket_unset(self):
        """write() is a no-op when S3_LOG_BUCKET is not set."""
        writer = _make_writer()
        writer._client = MagicMock()

        with (
            patch.object(writer, "_bucket", return_value=""),
            patch.object(writer, "_is_test_env", return_value=False),
        ):
            writer.write("ops_recommendations", {"id": "rec-001"})

        writer._client.put_object.assert_not_called()

    def test_write_skips_s3_when_pytest_current_test_set(self):
        """write() is a no-op when PYTEST_CURRENT_TEST env var is set."""
        writer = _make_writer()
        writer._client = MagicMock()

        with (
            patch.object(writer, "_bucket", return_value="my-bucket"),
            patch.object(writer, "_is_test_env", return_value=True),
        ):
            writer.write("ops_recommendations", {"id": "rec-001"})

        writer._client.put_object.assert_not_called()

    def test_write_handles_s3_upload_failure_gracefully(self):
        """write() logs warning and does not raise when S3 put_object fails."""
        writer = _make_writer()
        writer._client = MagicMock()
        writer._client.put_object.side_effect = RuntimeError("S3 error")

        with (
            patch.object(writer, "_bucket", return_value="my-bucket"),
            patch.object(writer, "_is_test_env", return_value=False),
        ):
            # Must not raise
            writer.write("ops_recommendations", {**_VALID_REC})

    def test_write_rejects_invalid_table_name(self):
        """write() logs warning and does not call S3 for unknown table names."""
        writer = _make_writer()
        writer._client = MagicMock()

        with (
            patch.object(writer, "_bucket", return_value="my-bucket"),
            patch.object(writer, "_is_test_env", return_value=False),
        ):
            writer.write("not_a_real_table", {"id": "x"})

        writer._client.put_object.assert_not_called()

    def test_write_skips_when_boto3_unavailable(self):
        """write() logs warning and returns when boto3 is not importable."""
        writer = _make_writer()

        with (
            patch("scripts.ops_writer._BOTO3_AVAILABLE", False),
            patch.object(writer, "_bucket", return_value="my-bucket"),
            patch.object(writer, "_is_test_env", return_value=False),
        ):
            # Must not raise
            writer.write("ops_recommendations", {"id": "rec-001"})

    def test_write_rejects_ops_recommendations_with_missing_id(self):
        """write() does not stage ops_recommendations records with a missing id."""
        writer = _make_writer()
        writer._client = MagicMock()

        entry = {k: v for k, v in _VALID_REC.items() if k != "id"}
        with (
            patch.object(writer, "_bucket", return_value="my-bucket"),
            patch.object(writer, "_is_test_env", return_value=False),
        ):
            writer.write("ops_recommendations", entry)

        writer._client.put_object.assert_not_called()

    def test_write_rejects_ops_recommendations_with_invalid_id_format(self):
        """write() does not stage ops_recommendations records with a non-rec-NNN id."""
        writer = _make_writer()
        writer._client = MagicMock()

        with (
            patch.object(writer, "_bucket", return_value="my-bucket"),
            patch.object(writer, "_is_test_env", return_value=False),
        ):
            writer.write("ops_recommendations", {**_VALID_REC, "id": "dec-001"})

        writer._client.put_object.assert_not_called()

    def test_write_rejects_ops_recommendations_regardless_of_id(self):
        """T2.19: write() hard-rejects ALL ops_recommendations writes (Decision 81 cl.7).

        Pre-T2.19 this test verified that rec-NNN format was accepted. After T2.19 the hard-reject
        fires before any table-name or ID validation -- no staging occurs even for valid rec IDs.
        Recs transit the DuckLake closed boundary via ops_data_portal.file_rec / update_rec.
        """
        writer = _make_writer()
        writer._client = MagicMock()

        with (
            patch.object(writer, "_bucket", return_value="my-bucket"),
            patch.object(writer, "_is_test_env", return_value=False),
        ):
            writer.write("ops_recommendations", {**_VALID_REC, "id": "rec-042"})

        writer._client.put_object.assert_not_called()


class TestRecsT219Rejection:
    """T2.19 -- ops_recommendations rejected at the OpsWriter boundary (Decision 81 cl.7).

    Acceptance-criteria locks from docs/plans/PLAN-ducklake-recs-cutover-completion.md:
    - recs not in TABLE_NAMES
    - write() hard-rejects without staging
    - compact() hard-rejects returning 0 (no paginator call)
    """

    def test_ops_recommendations_not_in_table_names(self) -> None:
        """ops_recommendations is excluded from TABLE_NAMES post-T2.19."""
        from scripts.ops_writer import TABLE_NAMES

        assert "ops_recommendations" not in TABLE_NAMES, (
            "ops_recommendations must NOT be in OpsWriter TABLE_NAMES after T2.19 (Decision 81 cl.7)"
        )

    def test_write_hard_rejects_recs_no_s3_call(self) -> None:
        """write() hard-rejects ops_recommendations -- S3 put_object is never called."""
        writer = _make_writer()
        writer._client = MagicMock()

        with (
            patch.object(writer, "_bucket", return_value="my-bucket"),
            patch.object(writer, "_is_test_env", return_value=False),
        ):
            writer.write("ops_recommendations", {**_VALID_REC})

        writer._client.put_object.assert_not_called()

    def test_write_hard_rejects_recs_does_not_raise(self) -> None:
        """write() hard-rejects ops_recommendations silently -- no exception raised."""
        writer = _make_writer()
        writer._client = MagicMock()

        with (
            patch.object(writer, "_bucket", return_value="my-bucket"),
            patch.object(writer, "_is_test_env", return_value=False),
        ):
            result = writer.write("ops_recommendations", {**_VALID_REC})

        assert result is None

    def test_write_hard_rejects_recs_no_outbox_call(self) -> None:
        """write() hard-rejects ops_recommendations before outbox -- outbox is never invoked."""
        writer = _make_writer()
        outbox_calls: list[tuple] = []

        with (
            patch.object(writer, "_bucket", return_value="my-bucket"),
            patch.object(writer, "_is_test_env", return_value=False),
            patch.object(writer, "_write_to_outbox", side_effect=lambda t, e: outbox_calls.append((t, e))),
        ):
            writer.write("ops_recommendations", {**_VALID_REC})

        assert len(outbox_calls) == 0, "outbox must NOT be called for ops_recommendations (hard-reject fires first)"

    def test_compact_hard_rejects_recs_returns_zero(self) -> None:
        """compact() hard-rejects ops_recommendations, returns 0 without touching S3."""
        writer = _make_writer()
        writer._client = MagicMock()

        with (
            patch("scripts.ops_writer._AWR_AVAILABLE", True),
            patch("scripts.ops_writer._BOTO3_AVAILABLE", True),
            patch.object(writer, "_bucket", return_value="my-bucket"),
            patch.object(writer, "_is_test_env", return_value=False),
        ):
            count = writer.compact("ops_recommendations", "2026-06-09")

        assert count == 0
        writer._client.get_paginator.assert_not_called()
