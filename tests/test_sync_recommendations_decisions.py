"""Tests for reseed_decisions_counter() in scripts/sync_recommendations.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from scripts.sync_recommendations import reseed_decisions_counter


class _FakeConditionalCheckFailed(Exception):
    """Stand-in for ddb.exceptions.ConditionalCheckFailedException in mock DDB clients."""


def _make_mock_ddb(*, reject: bool = False) -> MagicMock:
    """Return a MagicMock DynamoDB client with a catchable ConditionalCheckFailed exception class."""
    mock_ddb = MagicMock()
    mock_ddb.exceptions.ConditionalCheckFailedException = _FakeConditionalCheckFailed
    if reject:
        mock_ddb.update_item.side_effect = _FakeConditionalCheckFailed("condition failed")
    return mock_ddb


class TestReseedDecisionsCounter:
    """Tests for reseed_decisions_counter() (D2)."""

    def test_idempotent_same_max_is_noop(self) -> None:
        """Calling with same max_id is swallowed when DynamoDB rejects (already at that value)."""
        mock_ddb = _make_mock_ddb(reject=True)

        with patch("scripts.sync_recommendations.boto3") as mock_boto3:
            mock_boto3.Session.return_value.client.return_value = mock_ddb
            reseed_decisions_counter(50)

        mock_ddb.update_item.assert_called_once_with(
            TableName="agent-platform-counters",
            Key={"counter_name": {"S": "decisions"}},
            UpdateExpression="SET current_value = :max",
            ConditionExpression="attribute_not_exists(current_value) OR current_value < :max",
            ExpressionAttributeValues={":max": {"N": "50"}},
        )

    def test_monotonic_higher_max_advances_counter(self) -> None:
        """update_item is called with the correct value when counter advances."""
        mock_ddb = _make_mock_ddb(reject=False)

        with patch("scripts.sync_recommendations.boto3") as mock_boto3:
            mock_boto3.Session.return_value.client.return_value = mock_ddb
            reseed_decisions_counter(100)

        mock_ddb.update_item.assert_called_once()
        kwargs = mock_ddb.update_item.call_args.kwargs
        assert kwargs["ExpressionAttributeValues"] == {":max": {"N": "100"}}
        assert kwargs["UpdateExpression"] == "SET current_value = :max"

    def test_rejected_lower_max_is_noop(self) -> None:
        """ConditionalCheckFailed from a lower max_id is swallowed; no exception propagates."""
        mock_ddb = _make_mock_ddb(reject=True)

        with patch("scripts.sync_recommendations.boto3") as mock_boto3:
            mock_boto3.Session.return_value.client.return_value = mock_ddb
            reseed_decisions_counter(5)

    def test_boto3_unavailable_raises_runtime_error(self) -> None:
        """RuntimeError is raised when boto3 is not available."""
        with patch("scripts.sync_recommendations._BOTO3_AVAILABLE", False):
            with pytest.raises(RuntimeError, match="boto3 not available"):
                reseed_decisions_counter(10)
