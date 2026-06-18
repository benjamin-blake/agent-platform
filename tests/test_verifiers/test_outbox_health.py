"""Tests for the OutboxHealthVerifier."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.verifiers.harness import Hermeticity, VerifierSeverity, VerifierStatus
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


def _make_mock_file(table: str, mtime: float) -> MagicMock:
    """Return a mock Path with a fixed mtime under a named parent directory."""
    mock_file = MagicMock(spec=Path)
    mock_file.parent.name = table
    mock_file.stat.return_value.st_mtime = mtime
    return mock_file


@pytest.mark.asyncio
async def test_outbox_health_hard_gate_over_24h():
    """Files older than 24 h trigger HARD_GATE (injected clock, deterministic)."""
    base_time = 1_000_000.0
    mock_file = _make_mock_file("ops_recommendations", base_time - 25 * 3600)

    with patch("pathlib.Path.exists", return_value=True):
        with patch("pathlib.Path.rglob", return_value=[mock_file, mock_file]):
            verifier = OutboxHealthVerifier(now_fn=lambda: base_time)
            result = await verifier.verify()
            assert result.status == VerifierStatus.FAIL
            assert result.severity == VerifierSeverity.HARD_GATE
            assert ">24h" in result.message
            assert "ops_recommendations: 2" in result.message


@pytest.mark.asyncio
async def test_outbox_health_advisory_between_2h_and_24h():
    """Files 3 h old trigger ADVISORY (injected clock, deterministic)."""
    base_time = 1_000_000.0
    mock_file = _make_mock_file("ops_recommendations", base_time - 3 * 3600)

    with patch("pathlib.Path.exists", return_value=True):
        with patch("pathlib.Path.rglob", return_value=[mock_file]):
            verifier = OutboxHealthVerifier(now_fn=lambda: base_time)
            result = await verifier.verify()
            assert result.status == VerifierStatus.FAIL
            assert result.severity == VerifierSeverity.ADVISORY
            assert ">2h" in result.message


@pytest.mark.asyncio
async def test_outbox_health_fresh_under_2h():
    """Files under 2 h old pass (injected clock, deterministic)."""
    base_time = 1_000_000.0
    mock_file = _make_mock_file("ops_recommendations", base_time - 1 * 3600)

    with patch("pathlib.Path.exists", return_value=True):
        with patch("pathlib.Path.rglob", return_value=[mock_file]):
            verifier = OutboxHealthVerifier(now_fn=lambda: base_time)
            result = await verifier.verify()
            assert result.status == VerifierStatus.PASS
            assert "fresh" in result.message


def test_outbox_health_disposition():
    """OutboxHealthVerifier declares NON_HERMETIC_BY_CONSTRUCTION."""
    assert OutboxHealthVerifier.hermeticity == Hermeticity.NON_HERMETIC_BY_CONSTRUCTION
