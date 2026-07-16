"""Tests for scripts/ops_writer.py -- compact() edge-case + split-error-path concern.

rec-2709 Wave 9: split from the former tests/test_ops_writer.py monolith.
"""

from __future__ import annotations

import datetime
import json
from unittest.mock import MagicMock, patch

from tests.fixtures.ops_writer_helpers import VALID_REC as _VALID_REC
from tests.fixtures.ops_writer_helpers import make_writer as _make_writer


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
            writer.compact("ops_execution_plans")  # trade_date=None

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
            {"Contents": [{"Key": "staging/ops_execution_plans/dt=2026-04-20/batch-abc.jsonl"}]}
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
            patch.object(writer, "_get_boto3_session", return_value=MagicMock()),
            patch("scripts.ops_writer.wr"),
        ):
            count = writer.compact("ops_execution_plans", "2026-04-20")

        # Should still return 1 (row compacted), delete failure is non-fatal
        assert count == 1


class TestCompactErrorPaths:
    """Tests for the split compact() error paths introduced by the pipeline consolidation."""

    def _make_staging_client(self, tmp_path, records, table: str = "ops_execution_plans"):
        """Return a mock S3 client that serves one staging file with *records*."""
        import io

        body = "\n".join(json.dumps(r) for r in records).encode("utf-8")

        mock_client = MagicMock()
        mock_client.get_paginator.return_value.paginate.return_value = [
            {"Contents": [{"Key": f"staging/{table}/dt=2026-05-09/f.jsonl"}]}
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
            result = writer.compact("ops_execution_plans", "2026-05-09")

        assert result == 0

    def test_compact_infra_error_raises(self):
        """compact() raises RuntimeError when to_iceberg hits a credential/infra error."""
        import pytest

        writer = _make_writer()
        mock_client = self._make_staging_client(None, [{"id": "ep-001"}])

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
            with pytest.raises(RuntimeError, match="infrastructure failure for ops_execution_plans"):
                writer.compact("ops_execution_plans", "2026-05-09")

    def test_compact_passes_boto3_session_to_to_iceberg(self):
        """compact() forwards _get_boto3_session() to wr.athena.to_iceberg."""

        writer = _make_writer()
        fake_session = MagicMock(name="boto3_session")
        mock_client = self._make_staging_client(None, [{"id": "ep-001"}])

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
            writer.compact("ops_execution_plans", "2026-05-09")

        assert captured_kwargs.get("boto3_session") is fake_session

    def test_compact_uses_isolated_temp_path_per_call(self):
        """compact() uses a per-call UUID subfolder for temp_path so awswrangler's
        external temp table cannot scan parquets from other compact calls or
        other tables. Without this, two compacts sharing s3://bucket/tmp/ as
        temp_path produce a temp Glue table whose LOCATION is the directory
        root -- INSERT INTO ... SELECT FROM that temp_table reads ALL parquets
        in tmp/ regardless of which call wrote them."""
        import io

        writer = _make_writer()

        def make_fresh_client():
            body = json.dumps({"id": "ep-001"}).encode("utf-8")
            mc = MagicMock()
            mc.get_paginator.return_value.paginate.return_value = [
                {"Contents": [{"Key": "staging/ops_execution_plans/dt=2026-05-09/f.jsonl"}]}
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
            writer.compact("ops_execution_plans", "2026-05-09")
            writer.compact("ops_execution_plans", "2026-05-09")

        assert len(seen_paths) == 2
        assert seen_paths[0] != seen_paths[1], "two compact calls must use distinct temp_paths"
        for p in seen_paths:
            assert p.startswith("s3://my-bucket/tmp/compact-ops_execution_plans-")
            assert p.endswith("/")
            assert p != "s3://my-bucket/tmp/", "temp_path must not be the bare tmp/ directory"
