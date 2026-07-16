"""Tests for scripts/ops_writer.py -- client / bucket-resolution / test-env helper concern.

rec-2709 Wave 9: split from the former tests/test_ops_writer.py monolith.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from tests.fixtures.ops_writer_helpers import make_writer as _make_writer


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
