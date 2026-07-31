"""Tests for scripts/ops_writer.py -- client/boundary helper concern.

PLAN-coverage-paydown-ops-writer-sync-ops: covers the remaining 19 statements across
_get_boto3_session (6), _refresh_view (6), _bucket (4), write (3). NOTE _parse_list is NOT
here -- it is a closure inside compact() and belongs to test_compact_paths.py. Collision-free
(existing module is test_client_bucket.py).

rec-2931/rec-2932 note: two sibling test modules (test_compact_edge_cases.py,
test_outbox_emit.py) have tests that pass table="ops_recommendations" to compact()/write() when
probing guards below that call's own DuckLake-boundary early-return, making those assertions
vacuously true. This module drives the same guards with a real table (ops_decisions /
ops_priority_queue) so the assertions are genuine.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from tests.fixtures.ops_writer_helpers import VALID_REC as _VALID_REC
from tests.fixtures.ops_writer_helpers import make_writer as _make_writer


class TestGetBoto3Session:
    """Tests for OpsWriter._get_boto3_session()."""

    def test_returns_none_when_boto3_unavailable(self):
        """_get_boto3_session() returns None when _BOTO3_AVAILABLE is False."""
        writer = _make_writer()
        with patch("scripts.ops_writer._BOTO3_AVAILABLE", False):
            assert writer._get_boto3_session() is None

    def test_returns_session_with_profile_when_resolved(self):
        """_get_boto3_session() returns Session(profile_name=...) when a profile resolves."""
        writer = _make_writer()
        with (
            patch("scripts.ops_writer._BOTO3_AVAILABLE", True),
            patch("scripts.ops_writer.resolve_aws_profile", return_value="agent_platform"),
            patch("scripts.ops_writer._boto3") as mock_boto3,
        ):
            writer._get_boto3_session()
        mock_boto3.Session.assert_called_once_with(profile_name="agent_platform")

    def test_returns_bare_session_when_no_profile_resolved(self):
        """_get_boto3_session() returns a bare Session() when no profile resolves (e.g. Lambda)."""
        writer = _make_writer()
        with (
            patch("scripts.ops_writer._BOTO3_AVAILABLE", True),
            patch("scripts.ops_writer.resolve_aws_profile", return_value=None),
            patch("scripts.ops_writer._boto3") as mock_boto3,
        ):
            writer._get_boto3_session()
        mock_boto3.Session.assert_called_once_with()


class TestBucketFallbackPaths:
    """The remaining _bucket() statements: the sys.path insert guard and fallback-2's own dead-ends."""

    def test_bucket_inserts_root_into_syspath_when_absent(self):
        """_bucket() inserts str(ROOT) into sys.path when it is not already present."""
        import os
        import sys

        from scripts.ops_writer import ROOT

        writer = _make_writer()
        root_str = str(ROOT)
        had_root = root_str in sys.path
        original_path = list(sys.path)
        if had_root:
            sys.path = [p for p in sys.path if p != root_str]
        env_without_bucket = {k: v for k, v in os.environ.items() if k != "S3_LOG_BUCKET"}
        try:
            with patch.dict("os.environ", env_without_bucket, clear=True):
                writer._bucket()
            assert root_str in sys.path
        finally:
            sys.path = original_path

    def test_bucket_returns_empty_when_both_fallbacks_exhausted(self):
        """_bucket() returns '' when Config() raises AND config.personal.yaml itself errors out."""
        import os

        writer = _make_writer()
        env_without_bucket = {k: v for k, v in os.environ.items() if k != "S3_LOG_BUCKET"}
        with (
            patch.dict("os.environ", env_without_bucket, clear=True),
            patch("src.common.config.Config", side_effect=RuntimeError("config unavailable")),
            patch("pathlib.Path.exists", return_value=True),
            patch("yaml.safe_load", side_effect=RuntimeError("malformed yaml")),
        ):
            result = writer._bucket()
        assert result == ""


class TestWriteBucketAndBoto3Guards:
    """write()'s bucket-empty/test-env guard and boto3-unavailable guard, via a real table.

    rec-2932: the sibling assertions in test_outbox_emit.py use table="ops_recommendations",
    which never reaches these guards (write()'s own DuckLake-boundary rejection fires first).
    """

    def test_write_returns_early_when_bucket_empty(self):
        """write() returns without staging when _bucket() is empty, for a real table."""
        writer = _make_writer()
        with (
            patch.object(writer, "_bucket", return_value=""),
            patch.object(writer, "_is_test_env", return_value=False),
            patch.object(writer, "_get_client") as mock_get_client,
        ):
            writer.write("ops_decisions", {**_VALID_REC, "id": "dec-100"})
        mock_get_client.assert_not_called()

    def test_write_returns_early_when_test_env_true_despite_bucket(self):
        """write() returns without staging when _is_test_env() is True, even with a real bucket."""
        writer = _make_writer()
        with (
            patch.object(writer, "_bucket", return_value="my-bucket"),
            patch.object(writer, "_is_test_env", return_value=True),
            patch.object(writer, "_get_client") as mock_get_client,
        ):
            writer.write("ops_decisions", {**_VALID_REC, "id": "dec-101"})
        mock_get_client.assert_not_called()

    def test_write_returns_early_when_boto3_unavailable(self):
        """write() logs and returns when _BOTO3_AVAILABLE is False, for a real table."""
        writer = _make_writer()
        with (
            patch.object(writer, "_bucket", return_value="my-bucket"),
            patch.object(writer, "_is_test_env", return_value=False),
            patch("scripts.ops_writer._BOTO3_AVAILABLE", False),
            patch.object(writer, "_get_client") as mock_get_client,
        ):
            writer.write("ops_decisions", {**_VALID_REC, "id": "dec-102"})
        mock_get_client.assert_not_called()


class TestRefreshView:
    """Tests for OpsWriter._refresh_view()."""

    def test_refresh_view_noop_when_boto3_unavailable(self):
        """_refresh_view() returns immediately when _BOTO3_AVAILABLE is False."""
        writer = _make_writer()
        with (
            patch("scripts.ops_writer._BOTO3_AVAILABLE", False),
            patch("scripts.ops_writer._boto3") as mock_boto3,
        ):
            writer._refresh_view("ops_decisions")
        mock_boto3.Session.assert_not_called()
        mock_boto3.client.assert_not_called()

    def test_refresh_view_noop_for_table_with_no_view_sql(self):
        """_refresh_view() is a no-op for a table absent from the view_sqls map."""
        writer = _make_writer()
        with (
            patch("scripts.ops_writer._BOTO3_AVAILABLE", True),
            patch("scripts.ops_writer._boto3") as mock_boto3,
        ):
            writer._refresh_view("not_a_mapped_table")
        mock_boto3.Session.assert_not_called()
        mock_boto3.client.assert_not_called()

    def test_refresh_view_triggers_athena_query_with_profile(self):
        """_refresh_view() starts an Athena query via a profiled Session for a mapped table."""
        writer = _make_writer()
        mock_athena = MagicMock()
        mock_session = MagicMock()
        mock_session.client.return_value = mock_athena

        with (
            patch("scripts.ops_writer._BOTO3_AVAILABLE", True),
            patch("scripts.ops_writer.resolve_aws_profile", return_value="agent_platform"),
            patch("scripts.ops_writer._boto3") as mock_boto3,
        ):
            mock_boto3.Session.return_value = mock_session
            writer._refresh_view("ops_decisions")

        mock_boto3.Session.assert_called_once_with(profile_name="agent_platform")
        mock_session.client.assert_called_once_with("athena", region_name="eu-west-2")
        mock_athena.start_query_execution.assert_called_once()
        call_kwargs = mock_athena.start_query_execution.call_args[1]
        assert "ops_decisions_current" in call_kwargs["QueryString"]
        assert call_kwargs["QueryExecutionContext"] == {"Database": "agent_platform"}
        assert call_kwargs["WorkGroup"] == "agent-platform-production"

    def test_refresh_view_uses_default_chain_without_profile(self):
        """_refresh_view() uses boto3.client() directly when no profile resolves (Lambda)."""
        writer = _make_writer()
        mock_athena = MagicMock()

        with (
            patch("scripts.ops_writer._BOTO3_AVAILABLE", True),
            patch("scripts.ops_writer.resolve_aws_profile", return_value=None),
            patch("scripts.ops_writer._boto3") as mock_boto3,
        ):
            mock_boto3.client.return_value = mock_athena
            writer._refresh_view("ops_priority_queue")

        mock_boto3.Session.assert_not_called()
        mock_boto3.client.assert_called_once_with("athena", region_name="eu-west-2")
        mock_athena.start_query_execution.assert_called_once()

    def test_refresh_view_swallows_athena_failure(self):
        """_refresh_view() logs a warning and does not raise when start_query_execution fails."""
        writer = _make_writer()
        mock_athena = MagicMock()
        mock_athena.start_query_execution.side_effect = RuntimeError("Athena unavailable")

        with (
            patch("scripts.ops_writer._BOTO3_AVAILABLE", True),
            patch("scripts.ops_writer.resolve_aws_profile", return_value=None),
            patch("scripts.ops_writer._boto3") as mock_boto3,
        ):
            mock_boto3.client.return_value = mock_athena
            writer._refresh_view("telemetry_sessions")  # must not raise
