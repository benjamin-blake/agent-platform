"""Tests for feature_engine module."""

from unittest.mock import MagicMock, patch

import pytest

from src.data.feature_engine import FeatureEngine

pytestmark = pytest.mark.unit


def test_fetch_fear_greed_index_retries_on_malformed_json():
    """Test that _fetch_fear_greed_index retries when JSON lacks score field.

    Verifies that when the API response is valid JSON but missing the
    'score' field, the function logs a warning and retries (does not break).
    After all retries are exhausted, it returns None.
    """
    with patch("requests.get") as mock_get:
        # Configure the mock to return valid JSON but without a score field
        mock_response = MagicMock()
        mock_response.json.return_value = {"fear_and_greed": {}}  # Missing 'score' key
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        with patch("src.data.feature_engine.logger") as mock_logger:
            result = FeatureEngine._fetch_fear_greed_index()

            # Should return None after exhausting retries
            assert result is None

            # Verify that requests.get was called 3 times (for 3 retries)
            assert mock_get.call_count == 3

            # Verify that warning about malformed response was logged
            warning_calls = [call for call in mock_logger.warning.call_args_list if "Malformed response" in str(call)]
            assert len(warning_calls) == 3, f"Expected 3 malformed response warnings, got {len(warning_calls)}"


def test_fetch_fear_greed_index_returns_score_on_success():
    """Test that _fetch_fear_greed_index returns score when present."""
    with patch("requests.get") as mock_get:
        # Configure the mock to return valid JSON with score field
        mock_response = MagicMock()
        mock_response.json.return_value = {"fear_and_greed": {"score": 42.5}}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        result = FeatureEngine._fetch_fear_greed_index()

        # Should return the score
        assert result == 42.5

        # Verify requests.get was called only once (no retries needed)
        assert mock_get.call_count == 1
