"""Tests for the OutboxHealthVerifier."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.verifiers.harness import VerifierStatus
from scripts.verifiers.outbox_health import OutboxHealthVerifier


@pytest.mark.asyncio
async def test_outbox_health_no_dir():
    with patch("pathlib.Path.exists", return_value=False):
        verifier = OutboxHealthVerifier()
        result = await verifier.verify()
        assert result.status == VerifierStatus.PASS
        assert "does not exist" in result.message


@pytest.mark.asyncio
async def test_outbox_health_empty():
    with patch("pathlib.Path.exists", return_value=True):
        with patch("pathlib.Path.rglob", return_value=[]):
            verifier = OutboxHealthVerifier()
            result = await verifier.verify()
            assert result.status == VerifierStatus.PASS
            assert "empty" in result.message


@pytest.mark.asyncio
async def test_outbox_health_pending_files():
    mock_file = MagicMock(spec=Path)
    mock_file.parent.name = "ops_recommendations"

    mock_file.stat.return_value.st_mtime = 0  # Very old
    with patch("pathlib.Path.exists", return_value=True):
        with patch("pathlib.Path.rglob", return_value=[mock_file, mock_file]):
            verifier = OutboxHealthVerifier()
            result = await verifier.verify()
            assert result.status == VerifierStatus.FAIL
            assert "contains 2 stale files" in result.message
            assert "ops_recommendations: 2" in result.message
