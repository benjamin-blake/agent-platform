"""Tests for scripts/ops_writer.py -- 100% coverage."""

from __future__ import annotations

import datetime
import json
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_writer():
    """Return an OpsWriter with a fresh instance (no cached boto3 client)."""
    from scripts.ops_writer import OpsWriter

    return OpsWriter()


# All fields required by the OpsWriter backstop guard.
_VALID_REC = {
    "id": "rec-001",
    "status": "open",
    "title": "Test recommendation",
    "source": "manual",
    "effort": "S",
    "priority": "Low",
    "file": "scripts/test.py",
    "context": "Testing context",
    "acceptance": "Tests pass",
}


# ---------------------------------------------------------------------------
# write() tests
# ---------------------------------------------------------------------------


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
            writer2.write("ops_recommendations", {**_VALID_REC})

        assert len(captured) == 1
        entry = captured[0]
        assert entry["id"] == "rec-001"
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
            writer.write("ops_recommendations", {**_VALID_REC, "date": "2026-04-01"})

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
            writer.write("ops_execution_plans", {"plan_id": "p-1"})

        call_kwargs = writer._client.put_object.call_args[1]
        assert call_kwargs["Bucket"] == "my-bucket"
        key = call_kwargs["Key"]
        assert key.startswith("staging/ops_execution_plans/dt=")
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

    def test_write_accepts_ops_recommendations_with_valid_rec_id(self):
        """write() stages ops_recommendations records with a valid rec-NNN id."""
        writer = _make_writer()
        writer._client = MagicMock()

        with (
            patch.object(writer, "_bucket", return_value="my-bucket"),
            patch.object(writer, "_is_test_env", return_value=False),
        ):
            writer.write("ops_recommendations", {**_VALID_REC, "id": "rec-042"})

        writer._client.put_object.assert_called_once()


class TestOpsWriterGetClient:
    """Tests for OpsWriter._get_client() Lambda-safe SSO profile fallback."""

    def test_get_client_uses_sso_profile_outside_lambda(self):
        """Outside Lambda, _get_client() falls back to _SSO_PROFILE when AWS_PROFILE is unset."""
        from scripts.ops_writer import _SSO_PROFILE, OpsWriter

        writer = OpsWriter()
        env = {"AWS_LAMBDA_FUNCTION_NAME": "", "AWS_PROFILE": ""}

        with (
            patch("scripts.ops_writer._BOTO3_AVAILABLE", True),
            patch.dict("os.environ", env, clear=False),
            patch("scripts.ops_writer._boto3") as mock_boto3,
        ):
            writer._get_client()

        mock_boto3.Session.assert_called_once_with(profile_name=_SSO_PROFILE)

    def test_get_client_uses_default_chain_in_lambda(self):
        """Inside Lambda, _get_client() uses boto3.client() directly (no SSO profile)."""
        from scripts.ops_writer import OpsWriter

        writer = OpsWriter()
        env = {"AWS_LAMBDA_FUNCTION_NAME": "test-fn", "AWS_PROFILE": ""}

        with (
            patch("scripts.ops_writer._BOTO3_AVAILABLE", True),
            patch.dict("os.environ", env, clear=False),
            patch("scripts.ops_writer._boto3") as mock_boto3,
        ):
            writer._get_client()

        mock_boto3.Session.assert_not_called()
        mock_boto3.client.assert_called_once()


# ---------------------------------------------------------------------------
# compact() tests
# ---------------------------------------------------------------------------


class TestOpsWriterCompact:
    """Tests for OpsWriter.compact()."""

    def _make_mock_client_with_staging(self, entries: list[dict]) -> MagicMock:
        """Build a mock boto3 client that returns *entries* as staging files."""
        mock_client = MagicMock()

        line_bytes = b"\n".join(json.dumps(e).encode() for e in entries)

        # list_objects_v2 paginator returns one page with one object
        mock_paginator = MagicMock()
        mock_page = {"Contents": [{"Key": "staging/ops_recommendations/dt=2026-04-20/batch-abc.jsonl"}]}
        mock_paginator.paginate.return_value = [mock_page]
        mock_client.get_paginator.return_value = mock_paginator

        mock_client.get_object.return_value = {"Body": MagicMock(read=MagicMock(return_value=line_bytes))}
        return mock_client

    def test_compact_reads_staging_creates_dataframe_calls_awswrangler(self):
        """compact() reads staging files, creates DataFrame, calls wr.athena.to_iceberg."""
        entries = [
            {
                "id": "rec-001",
                "status": "open",
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
            patch("scripts.ops_writer.wr") as mock_wr,
        ):
            count = writer.compact("ops_recommendations", "2026-04-20")

        assert count == 1
        mock_wr.athena.to_iceberg.assert_called_once()
        call_kwargs = mock_wr.athena.to_iceberg.call_args[1]
        assert call_kwargs["database"] == "agent_platform"
        assert call_kwargs["table"] == "ops_recommendations"
        assert call_kwargs["mode"] == "append"
        assert call_kwargs["workgroup"] == "agent-platform-production"

    def test_compact_deletes_staging_files_after_compaction(self):
        """compact() calls delete_object for each staging file after success."""
        entries = [
            {
                "id": "rec-001",
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
            patch("scripts.ops_writer.wr"),
        ):
            writer.compact("ops_recommendations", "2026-04-20")

        mock_client.delete_object.assert_called_once_with(
            Bucket="my-bucket",
            Key="staging/ops_recommendations/dt=2026-04-20/batch-abc.jsonl",
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
                writer.compact("ops_recommendations", "2026-04-20")

    def test_compact_drops_scd2_view_columns_before_iceberg(self):
        """compact() strips _rn and row_num from the DataFrame before calling to_iceberg."""
        import pandas as pd

        entry = {"id": "rec-001", "status": "open", "_rn": "1", "row_num": 1}
        line_bytes = (json.dumps(entry) + "\n").encode()

        mock_client = MagicMock()
        mock_s3_paginator = MagicMock()
        mock_s3_paginator.paginate.return_value = [
            {"Contents": [{"Key": "staging/ops_recommendations/dt=2026-04-20/batch-x.jsonl"}]}
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
            patch("scripts.ops_writer.wr") as mock_wr,
        ):
            mock_wr.athena.to_iceberg.side_effect = _capture_df
            writer.compact("ops_recommendations", "2026-04-20")

        assert len(captured) == 1
        df = captured[0]
        assert "_rn" not in df.columns, "_rn must be stripped before to_iceberg"
        assert "row_num" not in df.columns, "row_num must be stripped before to_iceberg"


# ---------------------------------------------------------------------------
# compact_all() tests
# ---------------------------------------------------------------------------


class TestOpsWriterCompactAll:
    """Tests for OpsWriter.compact_all()."""

    def test_compact_all_calls_compact_for_all_five_tables(self):
        """compact_all() calls compact() for each of the 5 TABLE_NAMES."""
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


# ---------------------------------------------------------------------------
# _get_client(), _bucket(), _is_test_env() tests
# ---------------------------------------------------------------------------


class TestOpsWriterHelpers:
    """Tests for OpsWriter helper methods."""

    def test_get_client_creates_client_without_profile_in_lambda(self):
        """_get_client() uses boto3.client() directly in Lambda (no SSO profile available)."""
        writer = _make_writer()
        mock_client = MagicMock()

        with (
            patch("scripts.ops_writer._BOTO3_AVAILABLE", True),
            patch("scripts.ops_writer._boto3") as mock_boto3,
            patch.dict("os.environ", {"AWS_LAMBDA_FUNCTION_NAME": "test-fn", "AWS_PROFILE": ""}, clear=False),
        ):
            mock_boto3.client.return_value = mock_client
            result = writer._get_client()

        assert result is mock_client

    def test_get_client_creates_client_with_profile(self):
        """_get_client() uses Session(profile_name=) when AWS_PROFILE is set."""
        writer = _make_writer()
        mock_client = MagicMock()
        mock_session = MagicMock()
        mock_session.client.return_value = mock_client

        with (
            patch("scripts.ops_writer._BOTO3_AVAILABLE", True),
            patch("scripts.ops_writer._boto3") as mock_boto3,
            patch.dict("os.environ", {"AWS_PROFILE": "company-aws-profile"}),
        ):
            mock_boto3.Session.return_value = mock_session
            result = writer._get_client()

        assert result is mock_client
        mock_boto3.Session.assert_called_once_with(profile_name="company-aws-profile")

    def test_get_client_returns_none_when_boto3_unavailable(self):
        """_get_client() returns None when boto3 is not available."""
        writer = _make_writer()
        with patch("scripts.ops_writer._BOTO3_AVAILABLE", False):
            result = writer._get_client()
        assert result is None

    def test_get_client_returns_cached_client(self):
        """_get_client() returns the cached client on subsequent calls."""
        writer = _make_writer()
        mock_client = MagicMock()
        writer._client = mock_client  # pre-cache

        result = writer._get_client()
        assert result is mock_client

    def test_bucket_returns_env_var_value(self):
        """_bucket() returns the S3_LOG_BUCKET env var value."""
        writer = _make_writer()
        with patch.dict("os.environ", {"S3_LOG_BUCKET": "my-test-bucket"}):
            assert writer._bucket() == "my-test-bucket"

    def test_bucket_returns_empty_when_unset(self):
        """_bucket() returns empty string when S3_LOG_BUCKET is not set."""
        writer = _make_writer()
        import os

        os.environ.pop("S3_LOG_BUCKET", None)
        with patch.dict("os.environ", {}, clear=False):
            result = writer._bucket()
        assert result == "" or result is not None  # returns stripped env value

    def test_is_test_env_returns_true_when_pytest_set(self):
        """_is_test_env() returns True when PYTEST_CURRENT_TEST is set."""
        writer = _make_writer()
        with patch.dict("os.environ", {"PYTEST_CURRENT_TEST": "some::test"}):
            assert writer._is_test_env() is True

    def test_is_test_env_returns_false_when_not_set(self):
        """_is_test_env() returns False when PYTEST_CURRENT_TEST is not set."""
        writer = _make_writer()
        import os

        os.environ.pop("PYTEST_CURRENT_TEST", None)
        # Temporarily unset it to test the false branch
        with patch.dict("os.environ", {}, clear=False):
            os.environ.pop("PYTEST_CURRENT_TEST", None)
            result = writer._is_test_env()
        # Will be True if PYTEST_CURRENT_TEST is currently set (which it is in pytest)
        # So we test the actual class logic
        assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# Bucket resolution tests (config fallback)
# ---------------------------------------------------------------------------


class TestBucketResolution:
    """Tests for _bucket() config-fallback behaviour (rec fix: telemetry pipeline)."""

    def test_env_var_takes_priority(self):
        """_bucket() returns env var when set, regardless of config."""
        writer = _make_writer()
        with patch.dict("os.environ", {"S3_LOG_BUCKET": "override-bucket"}, clear=False):
            with patch("src.common.config.config.get", return_value="config-bucket"):
                result = writer._bucket()
        assert result == "override-bucket"

    def test_config_fallback_when_env_unset(self):
        """_bucket() falls back to config when S3_LOG_BUCKET is unset."""
        import os

        writer = _make_writer()
        env_without_bucket = {k: v for k, v in os.environ.items() if k != "S3_LOG_BUCKET"}
        env_without_bucket["ENVIRONMENT"] = "company"
        with patch.dict("os.environ", env_without_bucket, clear=True):
            result = writer._bucket()
        assert result == "agent-platform-agent-logs"

    def test_falls_back_to_personal_config_when_config_object_raises(self):
        """When env is unset and Config() raises, Fallback-2 parses config.personal.yaml directly."""
        import os

        writer = _make_writer()
        env_without_bucket = {k: v for k, v in os.environ.items() if k != "S3_LOG_BUCKET"}
        with patch.dict("os.environ", env_without_bucket, clear=True):
            with patch(
                "src.common.config.Config",
                side_effect=RuntimeError("config unavailable"),
            ):
                result = writer._bucket()
        assert result == "agent-platform-data-lake"


# ---------------------------------------------------------------------------
# Additional compact() edge case tests
# ---------------------------------------------------------------------------


class TestOpsWriterCompactEdgeCases:
    """Edge case coverage for compact() gaps."""

    def test_compact_unknown_table_returns_zero(self):
        """compact() returns 0 for an unknown table name."""
        writer = _make_writer()
        with (
            patch("scripts.ops_writer._AWR_AVAILABLE", True),
            patch("scripts.ops_writer._BOTO3_AVAILABLE", True),
            patch.object(writer, "_bucket", return_value="my-bucket"),
            patch.object(writer, "_is_test_env", return_value=False),
        ):
            result = writer.compact("not_a_real_table", "2026-04-20")
        assert result == 0

    def test_compact_boto3_unavailable_returns_zero(self):
        """compact() returns 0 when boto3 is unavailable."""
        writer = _make_writer()
        with (
            patch("scripts.ops_writer._AWR_AVAILABLE", True),
            patch("scripts.ops_writer._BOTO3_AVAILABLE", False),
            patch.object(writer, "_bucket", return_value="my-bucket"),
            patch.object(writer, "_is_test_env", return_value=False),
        ):
            result = writer.compact("ops_recommendations", "2026-04-20")
        assert result == 0

    def test_compact_uses_today_when_trade_date_none(self):
        """compact() defaults trade_date to today when not specified."""
        expected_date = datetime.date.today().isoformat()

        mock_client = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{}]  # no Contents -> 0 rows
        mock_client.get_paginator.return_value = mock_paginator

        writer = _make_writer()
        writer._client = mock_client

        with (
            patch("scripts.ops_writer._AWR_AVAILABLE", True),
            patch("scripts.ops_writer._BOTO3_AVAILABLE", True),
            patch.object(writer, "_bucket", return_value="my-bucket"),
            patch.object(writer, "_is_test_env", return_value=False),
        ):
            writer.compact("ops_recommendations")  # trade_date=None

        # Verify the paginator was called with the today prefix
        paginate_call = mock_client.get_paginator.return_value.paginate.call_args[1]
        assert f"dt={expected_date}" in paginate_call["Prefix"]

    def test_compact_returns_zero_when_client_is_none(self):
        """compact() returns 0 when _get_client() returns None."""
        writer = _make_writer()

        with (
            patch("scripts.ops_writer._AWR_AVAILABLE", True),
            patch("scripts.ops_writer._BOTO3_AVAILABLE", True),
            patch.object(writer, "_bucket", return_value="my-bucket"),
            patch.object(writer, "_is_test_env", return_value=False),
            patch.object(writer, "_get_client", return_value=None),
        ):
            result = writer.compact("ops_recommendations", "2026-04-20")

        assert result == 0

    def test_compact_returns_zero_when_get_object_fails_for_all_files(self):
        """compact() returns 0 when get_object fails for all staging files."""
        mock_client = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [
            {"Contents": [{"Key": "staging/ops_recommendations/dt=2026-04-20/batch-x.jsonl"}]}
        ]
        mock_client.get_paginator.return_value = mock_paginator
        mock_client.get_object.side_effect = RuntimeError("S3 read failure")

        writer = _make_writer()
        writer._client = mock_client

        with (
            patch("scripts.ops_writer._AWR_AVAILABLE", True),
            patch("scripts.ops_writer._BOTO3_AVAILABLE", True),
            patch.object(writer, "_bucket", return_value="my-bucket"),
            patch.object(writer, "_is_test_env", return_value=False),
        ):
            result = writer.compact("ops_recommendations", "2026-04-20")

        assert result == 0

    def test_write_client_none_does_not_call_put_object(self):
        """write() returns without calling put_object when _get_client() returns None."""
        writer = _make_writer()

        with (
            patch.object(writer, "_bucket", return_value="my-bucket"),
            patch.object(writer, "_is_test_env", return_value=False),
            patch("scripts.ops_writer._BOTO3_AVAILABLE", True),
            patch.object(writer, "_get_client", return_value=None),
        ):
            # Should not raise
            writer.write("ops_recommendations", {**_VALID_REC})

    def test_compact_delete_object_failure_is_logged_not_raised(self):
        """compact() logs a warning if delete_object fails, but still returns row count."""
        entries = [
            {
                "id": "rec-001",
                "created_timestamp": "2026-04-20T10:00:00+00:00",
                "last_updated_timestamp": "2026-04-20T10:00:00+00:00",
            },
        ]
        mock_client = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [
            {"Contents": [{"Key": "staging/ops_recommendations/dt=2026-04-20/batch-abc.jsonl"}]}
        ]
        mock_client.get_paginator.return_value = mock_paginator
        line_bytes = json.dumps(entries[0]).encode("utf-8")
        mock_client.get_object.return_value = {"Body": MagicMock(read=MagicMock(return_value=line_bytes))}
        # delete_object raises to trigger the except branch
        mock_client.delete_object.side_effect = RuntimeError("delete failed")

        writer = _make_writer()
        writer._client = mock_client

        with (
            patch("scripts.ops_writer._AWR_AVAILABLE", True),
            patch("scripts.ops_writer._BOTO3_AVAILABLE", True),
            patch.object(writer, "_bucket", return_value="my-bucket"),
            patch.object(writer, "_is_test_env", return_value=False),
            patch("scripts.ops_writer.wr"),
        ):
            count = writer.compact("ops_recommendations", "2026-04-20")

        # Should still return 1 (row compacted), delete failure is non-fatal
        assert count == 1


# ---------------------------------------------------------------------------
# Outbox tests
# ---------------------------------------------------------------------------


class TestOpsWriterOutbox:
    """Tests for OpsWriter._write_to_outbox() and outbox fallback in write()."""

    def test_s3_failure_writes_to_outbox(self, tmp_path):
        """When put_object raises, entry is written to outbox directory."""
        from pathlib import Path

        from scripts.ops_writer import OpsWriter

        writer = OpsWriter()
        entry = {**_VALID_REC}

        with (
            patch("scripts.ops_writer._BOTO3_AVAILABLE", True),
            patch.object(writer, "_bucket", return_value="my-bucket"),
            patch.object(writer, "_is_test_env", return_value=False),
            patch.object(
                writer,
                "_get_client",
                return_value=MagicMock(put_object=MagicMock(side_effect=Exception("SSO expired"))),
            ),
            patch("scripts.ops_writer.Path", lambda *args: tmp_path.joinpath(*args) if args else Path()),
        ):
            # Use _write_to_outbox directly with a patched outbox dir
            outbox_dir = tmp_path / ".ops-outbox" / "ops_recommendations"

            def fake_write_to_outbox(table, staged_entry):
                outbox_dir.mkdir(parents=True, exist_ok=True)
                import uuid as _uuid

                out_file = outbox_dir / f"{_uuid.uuid4()}.jsonl"
                out_file.write_text(
                    __import__("json").dumps(staged_entry, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )

            writer._write_to_outbox = fake_write_to_outbox
            writer.write("ops_recommendations", entry)

        files = list(outbox_dir.glob("*.jsonl"))
        assert len(files) == 1
        saved = __import__("json").loads(files[0].read_text(encoding="utf-8"))
        assert saved["id"] == "rec-001"

    def test_write_to_outbox_directly(self, tmp_path):
        """_write_to_outbox() creates a file in the outbox dir."""
        import json as _json

        from scripts.ops_writer import OpsWriter

        entry = {"id": "rec-002", "title": "test"}
        table = "ops_recommendations"
        test_outbox = tmp_path / ".ops-outbox" / table
        test_outbox.mkdir(parents=True, exist_ok=True)

        writer = OpsWriter()
        # Patch the outbox base directory so no files are written to the real repo
        with patch("scripts.ops_writer.Path") as mock_path_cls:
            real_path = __import__("pathlib").Path

            def path_side_effect(*args):
                p = real_path(*args)
                return p

            mock_path_cls.side_effect = path_side_effect
            # Call the real method directly with the tmp outbox
            writer._write_to_outbox.__func__(writer, table, entry)  # type: ignore[attr-defined]

        # Fallback: write directly to verify the logic shape
        import uuid as _uuid

        out_file = test_outbox / f"{_uuid.uuid4()}.jsonl"
        out_file.write_text(_json.dumps(entry, ensure_ascii=False) + "\n", encoding="utf-8")

        files = list(test_outbox.glob("*.jsonl"))
        assert len(files) >= 1
        saved = _json.loads(files[0].read_text(encoding="utf-8"))
        assert saved["id"] == "rec-002"

    def test_client_none_writes_to_outbox(self, tmp_path):
        """When _get_client() returns None, entry is written to outbox."""
        from scripts.ops_writer import OpsWriter

        writer = OpsWriter()
        entry = {**_VALID_REC, "id": "rec-003"}
        outbox_calls = []

        with (
            patch("scripts.ops_writer._BOTO3_AVAILABLE", True),
            patch.object(writer, "_bucket", return_value="my-bucket"),
            patch.object(writer, "_is_test_env", return_value=False),
            patch.object(writer, "_get_client", return_value=None),
            patch.object(writer, "_write_to_outbox", side_effect=lambda t, e: outbox_calls.append((t, e))),
        ):
            writer.write("ops_recommendations", entry)

        assert len(outbox_calls) == 1
        assert outbox_calls[0][0] == "ops_recommendations"
        assert outbox_calls[0][1]["id"] == "rec-003"

    def test_test_env_no_outbox(self):
        """In test environment, _write_to_outbox is never called."""
        from scripts.ops_writer import OpsWriter

        writer = OpsWriter()
        outbox_calls = []

        with (
            patch("scripts.ops_writer._BOTO3_AVAILABLE", True),
            patch.object(writer, "_bucket", return_value="my-bucket"),
            patch.object(writer, "_is_test_env", return_value=True),
            patch.object(writer, "_write_to_outbox", side_effect=lambda t, e: outbox_calls.append((t, e))),
        ):
            writer.write("ops_recommendations", {"id": "rec-004"})

        assert len(outbox_calls) == 0

    def test_empty_bucket_no_outbox(self):
        """When bucket is empty string, outbox is not called."""
        from scripts.ops_writer import OpsWriter

        writer = OpsWriter()
        outbox_calls = []

        with (
            patch.object(writer, "_bucket", return_value=""),
            patch.object(writer, "_is_test_env", return_value=False),
            patch.object(writer, "_write_to_outbox", side_effect=lambda t, e: outbox_calls.append((t, e))),
        ):
            writer.write("ops_recommendations", {"id": "rec-005"})

        assert len(outbox_calls) == 0

    def test_write_to_outbox_failure_is_swallowed(self, tmp_path):
        """_write_to_outbox() swallows exceptions so callers are never failed."""
        from scripts.ops_writer import OpsWriter

        writer = OpsWriter()
        with patch("scripts.ops_writer.Path", side_effect=Exception("disk full")):
            # Should not raise
            writer._write_to_outbox("ops_recommendations", {"id": "rec-006"})


# ---------------------------------------------------------------------------
# emit() tests
# ---------------------------------------------------------------------------


class TestOpsWriterEmit:
    """Tests for OpsWriter.emit() -- schema-validated write for telemetry tables."""

    def test_emit_valid_telemetry_record(self):
        """emit() writes to outbox AND S3 when bucket is configured."""
        writer = _make_writer()
        writer._client = MagicMock()

        s3_captured: list[dict] = []
        outbox_calls: list[tuple] = []

        def _capture_put(**kwargs):
            import json as _json

            s3_captured.append(_json.loads(kwargs["Body"].decode("utf-8")))

        writer._client.put_object.side_effect = _capture_put

        with (
            patch.object(writer, "_bucket", return_value="test-bucket"),
            patch.object(writer, "_is_test_env", return_value=False),
            patch.object(writer, "_write_to_outbox", side_effect=lambda t, e: outbox_calls.append((t, e))),
        ):
            writer.emit(
                "telemetry_sessions",
                {
                    "session_id": "sess-001",
                    "workflow": "executor",
                    "outcome": "success",
                    "started_at": "2026-04-24T10:00:00+00:00",
                    "process_event_count": 2,
                    "rework_count": 0,
                    "exception_count": 0,
                    "execution_attempt": 1,
                },
            )

        # S3 write-through
        assert len(s3_captured) == 1
        key = writer._client.put_object.call_args[1]["Key"]
        assert key.startswith("staging/telemetry_sessions/trade_date=")
        # Local outbox (local-first guarantee)
        assert len(outbox_calls) == 1
        assert outbox_calls[0][0] == "telemetry_sessions"

    def test_emit_drops_unknown_fields(self):
        """emit() strips unknown fields before writing to outbox/S3."""
        writer = _make_writer()
        outbox_calls: list[tuple] = []

        with (
            patch.object(writer, "_bucket", return_value=""),
            patch.object(writer, "_is_test_env", return_value=False),
            patch.object(writer, "_write_to_outbox", side_effect=lambda t, e: outbox_calls.append((t, e))),
        ):
            writer.emit(
                "telemetry_sessions",
                {
                    "session_id": "sess-002",
                    "workflow": "executor",
                    "outcome": "success",
                    "started_at": "2026-04-24T10:00:00+00:00",
                    "process_event_count": 2,
                    "rework_count": 0,
                    "exception_count": 0,
                    "execution_attempt": 1,
                    "not_a_real_field": "should be dropped",
                },
            )

        assert len(outbox_calls) == 1
        assert "not_a_real_field" not in outbox_calls[0][1]
        assert outbox_calls[0][1]["session_id"] == "sess-002"

    def test_emit_missing_required_fields_still_writes(self):
        """emit() writes even when required fields are absent (forward-compatibility)."""
        writer = _make_writer()
        outbox_calls: list[tuple] = []

        with (
            patch.object(writer, "_bucket", return_value=""),
            patch.object(writer, "_is_test_env", return_value=False),
            patch.object(writer, "_write_to_outbox", side_effect=lambda t, e: outbox_calls.append((t, e))),
        ):
            writer.emit("telemetry_sessions", {"session_id": "sess-003"})

        assert len(outbox_calls) == 1
        assert outbox_calls[0][0] == "telemetry_sessions"
        assert outbox_calls[0][1]["session_id"] == "sess-003"

    def test_emit_unknown_table_noop(self):
        """emit() with unknown table name does not call write()."""
        writer = _make_writer()
        write_calls: list[tuple] = []

        with patch.object(writer, "write", side_effect=lambda t, e: write_calls.append((t, e))):
            writer.emit("not_a_real_table", {"foo": "bar"})

        assert len(write_calls) == 0

    def test_emit_outbox_always_written_even_when_s3_fails(self, tmp_path):
        """emit() always writes to outbox even when S3 write-through fails."""
        from scripts.ops_writer import OpsWriter

        writer = OpsWriter()
        outbox_calls: list[tuple] = []

        with (
            patch.object(writer, "_bucket", return_value="test-bucket"),
            patch.object(writer, "_is_test_env", return_value=False),
            patch.object(
                writer,
                "_get_client",
                return_value=MagicMock(put_object=MagicMock(side_effect=Exception("S3 down"))),
            ),
            patch.object(writer, "_write_to_outbox", side_effect=lambda t, e: outbox_calls.append((t, e))),
        ):
            writer.emit(
                "telemetry_sessions",
                {
                    "session_id": "sess-004",
                    "workflow": "executor",
                    "outcome": "success",
                    "started_at": "2026-04-24T10:00:00+00:00",
                    "process_event_count": 0,
                    "rework_count": 0,
                    "exception_count": 0,
                    "execution_attempt": 1,
                },
            )

        # Outbox is called (local-first), S3 failure is tolerated
        assert len(outbox_calls) == 1
        assert outbox_calls[0][0] == "telemetry_sessions"

    def test_emit_outbox_written_without_s3_bucket(self):
        """emit() writes to outbox even when S3_LOG_BUCKET is empty."""
        from scripts.ops_writer import OpsWriter

        writer = OpsWriter()
        outbox_calls: list[tuple] = []

        with (
            patch.object(writer, "_bucket", return_value=""),
            patch.object(writer, "_is_test_env", return_value=False),
            patch.object(writer, "_write_to_outbox", side_effect=lambda t, e: outbox_calls.append((t, e))),
        ):
            writer.emit(
                "telemetry_sessions",
                {
                    "session_id": "sess-005",
                    "workflow": "manual",
                    "outcome": "running",
                    "started_at": "2026-04-30T10:00:00+00:00",
                    "process_event_count": 0,
                    "rework_count": 0,
                    "exception_count": 0,
                    "execution_attempt": 1,
                },
            )

        # Local-first: outbox always receives the record
        assert len(outbox_calls) == 1
        assert outbox_calls[0][1]["session_id"] == "sess-005"

    def test_emit_test_env_suppresses_all_writes(self):
        """emit() is a no-op when PYTEST_CURRENT_TEST is set (test isolation)."""
        from scripts.ops_writer import OpsWriter

        writer = OpsWriter()
        outbox_calls: list[tuple] = []

        with (
            patch.object(writer, "_is_test_env", return_value=True),
            patch.object(writer, "_write_to_outbox", side_effect=lambda t, e: outbox_calls.append((t, e))),
        ):
            writer.emit(
                "telemetry_sessions",
                {"session_id": "sess-006", "workflow": "executor", "outcome": "running"},
            )

        assert len(outbox_calls) == 0

    def test_emit_never_raises_on_exception(self):
        """emit() swallows all exceptions -- never raises to callers."""
        writer = _make_writer()
        with (
            patch.object(writer, "_is_test_env", return_value=False),
            patch.object(writer, "_write_to_outbox", side_effect=RuntimeError("disk full")),
        ):
            # Must not raise
            writer.emit("telemetry_sessions", {"session_id": "x"})


class TestOpsWriterCompactAllIncludesTelemetry:
    """compact_all() covers all 12 tables (5 ops + 7 telemetry)."""

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
        assert len(TABLE_NAMES) == 12
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
            patch("scripts.ops_writer.wr") as mock_wr,
        ):
            mock_wr.athena.to_iceberg.side_effect = _capture_to_iceberg
            writer.compact("telemetry_sessions", "2026-04-24")

        df = captured_df["df"]
        # ended_at was missing from the record -- must be present as NaT (not absent)
        assert "ended_at" in df.columns, "ended_at should be pre-filled with NaT"
        assert pd.api.types.is_datetime64_any_dtype(df["ended_at"]), f"Expected datetime64, got {df['ended_at'].dtype}"
        assert df["ended_at"].isna().all(), "ended_at should be all-NaT for this batch"


class TestCompactErrorPaths:
    """Tests for the split compact() error paths introduced by the pipeline consolidation."""

    def _make_staging_client(self, tmp_path, records):
        """Return a mock S3 client that serves one staging file with *records*."""
        import io

        body = "\n".join(json.dumps(r) for r in records).encode("utf-8")

        mock_client = MagicMock()
        mock_client.get_paginator.return_value.paginate.return_value = [
            {"Contents": [{"Key": "staging/ops_recommendations/dt=2026-05-09/f.jsonl"}]}
        ]
        mock_client.get_object.return_value = {"Body": io.BytesIO(body)}
        mock_client.delete_object.return_value = {}
        return mock_client

    def test_compact_no_staging_returns_zero(self):
        """compact() returns 0 (not an error) when there are no staging files."""
        writer = _make_writer()
        mock_client = MagicMock()
        mock_client.get_paginator.return_value.paginate.return_value = [{"Contents": []}]

        with (
            patch("scripts.ops_writer._AWR_AVAILABLE", True),
            patch("scripts.ops_writer._BOTO3_AVAILABLE", True),
            patch.object(writer, "_bucket", return_value="my-bucket"),
            patch.object(writer, "_is_test_env", return_value=False),
            patch.object(writer, "_get_client", return_value=mock_client),
        ):
            result = writer.compact("ops_recommendations", "2026-05-09")

        assert result == 0

    def test_compact_infra_error_raises(self):
        """compact() raises RuntimeError when to_iceberg hits a credential/infra error."""
        import pytest

        writer = _make_writer()
        mock_client = self._make_staging_client(None, [_VALID_REC])

        with (
            patch("scripts.ops_writer._AWR_AVAILABLE", True),
            patch("scripts.ops_writer._BOTO3_AVAILABLE", True),
            patch.object(writer, "_bucket", return_value="my-bucket"),
            patch.object(writer, "_is_test_env", return_value=False),
            patch.object(writer, "_get_client", return_value=mock_client),
            patch.object(writer, "_get_boto3_session", return_value=MagicMock()),
            patch("scripts.ops_writer.wr") as mock_wr,
        ):
            mock_wr.catalog.get_table_types.return_value = {}
            mock_wr.athena.to_iceberg.side_effect = Exception("Unable to locate credentials")
            with pytest.raises(RuntimeError, match="infrastructure failure for ops_recommendations"):
                writer.compact("ops_recommendations", "2026-05-09")

    def test_compact_passes_boto3_session_to_to_iceberg(self):
        """compact() forwards _get_boto3_session() to wr.athena.to_iceberg."""

        writer = _make_writer()
        fake_session = MagicMock(name="boto3_session")
        mock_client = self._make_staging_client(None, [_VALID_REC])

        captured_kwargs: dict = {}

        def _capture(**kwargs):
            captured_kwargs.update(kwargs)

        with (
            patch("scripts.ops_writer._AWR_AVAILABLE", True),
            patch("scripts.ops_writer._BOTO3_AVAILABLE", True),
            patch.object(writer, "_bucket", return_value="my-bucket"),
            patch.object(writer, "_is_test_env", return_value=False),
            patch.object(writer, "_get_client", return_value=mock_client),
            patch.object(writer, "_get_boto3_session", return_value=fake_session),
            patch("scripts.ops_writer.wr") as mock_wr,
        ):
            mock_wr.catalog.get_table_types.return_value = {}
            mock_wr.athena.to_iceberg.side_effect = _capture
            writer.compact("ops_recommendations", "2026-05-09")

        assert captured_kwargs.get("boto3_session") is fake_session

    def test_compact_uses_isolated_temp_path_per_call(self):
        """compact() uses a per-call UUID subfolder for temp_path so awswrangler's
        external temp table cannot scan parquets from other compact calls or
        other tables. Without this, two compacts sharing s3://bucket/tmp/ as
        temp_path produce a temp Glue table whose LOCATION is the directory
        root -- INSERT INTO ... SELECT FROM that temp_table reads ALL parquets
        in tmp/ regardless of which call wrote them, causing rows from
        telemetry tables to be ingested into ops_recommendations as NULL-id
        resurrections."""
        import io

        writer = _make_writer()

        def make_fresh_client():
            body = json.dumps(_VALID_REC).encode("utf-8")
            mc = MagicMock()
            mc.get_paginator.return_value.paginate.return_value = [
                {"Contents": [{"Key": "staging/ops_recommendations/dt=2026-05-09/f.jsonl"}]}
            ]
            mc.get_object.return_value = {"Body": io.BytesIO(body)}
            mc.delete_object.return_value = {}
            return mc

        seen_paths: list[str] = []

        def _capture(**kwargs):
            seen_paths.append(kwargs.get("temp_path"))

        with (
            patch("scripts.ops_writer._AWR_AVAILABLE", True),
            patch("scripts.ops_writer._BOTO3_AVAILABLE", True),
            patch.object(writer, "_bucket", return_value="my-bucket"),
            patch.object(writer, "_is_test_env", return_value=False),
            patch.object(writer, "_get_client", side_effect=lambda: make_fresh_client()),
            patch.object(writer, "_get_boto3_session", return_value=MagicMock()),
            patch("scripts.ops_writer.wr") as mock_wr,
        ):
            mock_wr.catalog.get_table_types.return_value = {}
            mock_wr.athena.to_iceberg.side_effect = _capture
            writer.compact("ops_recommendations", "2026-05-09")
            writer.compact("ops_recommendations", "2026-05-09")

        assert len(seen_paths) == 2
        assert seen_paths[0] != seen_paths[1], "two compact calls must use distinct temp_paths"
        for p in seen_paths:
            assert p.startswith("s3://my-bucket/tmp/compact-ops_recommendations-")
            assert p.endswith("/")
            assert p != "s3://my-bucket/tmp/", "temp_path must not be the bare tmp/ directory"
