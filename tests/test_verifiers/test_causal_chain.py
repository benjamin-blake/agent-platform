"""Tests for the CausalChainVerifier."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pandas as pd
import pytest

from scripts.verifiers.causal_chain import CausalChainVerifier
from scripts.verifiers.harness import VerifierStatus


@pytest.fixture
def verifier():
    return CausalChainVerifier()


@pytest.mark.asyncio
async def test_verify_awswrangler_missing(verifier):
    """ImportError for awswrangler → SKIP."""
    with patch.dict("sys.modules", {"awswrangler": None}):
        result = await verifier.verify()
    assert result.status == VerifierStatus.SKIPPED
    assert "not available" in result.message


@pytest.mark.asyncio
async def test_verify_no_s3_bucket(verifier):
    """S3_LOG_BUCKET not set → SKIP before any AWS calls."""
    with patch("scripts.verifiers.causal_chain.OpsWriter") as mock_writer_cls:
        mock_writer_cls.return_value._bucket.return_value = None
        result = await verifier.verify()
    assert result.status == VerifierStatus.SKIPPED
    assert "S3_LOG_BUCKET" in result.message


@pytest.mark.asyncio
async def test_verify_credentials_unavailable(verifier):
    """STS get_caller_identity fails → SKIP before emitting heartbeat."""
    with (
        patch("scripts.verifiers.causal_chain.OpsWriter") as mock_writer_cls,
        patch("boto3.Session") as mock_session,
    ):
        mock_writer_cls.return_value._bucket.return_value = "test-bucket"
        mock_session.return_value.client.return_value.get_caller_identity.side_effect = Exception("No creds")
        result = await verifier.verify()
    assert result.status == VerifierStatus.SKIPPED
    assert "credential" in result.message.lower()


@pytest.mark.asyncio
async def test_verify_heartbeat_found(verifier):
    """Heartbeat nonce appears in Athena within timeout → PASS."""
    with (
        patch("scripts.verifiers.causal_chain.OpsWriter") as mock_writer_cls,
        patch("boto3.Session"),
        patch("scripts.verifiers.causal_chain.emit_process_event"),
        patch("awswrangler.athena.read_sql_query") as mock_query,
    ):
        mock_writer_cls.return_value._bucket.return_value = "test-bucket"
        mock_query.return_value = pd.DataFrame({"count": [1]})
        result = await verifier.verify()
    assert result.status == VerifierStatus.PASS
    assert "Causal chain verified" in result.message


@pytest.mark.asyncio
async def test_verify_timeout(verifier):
    """Heartbeat never appears in Athena → FAIL after timeout."""
    with (
        patch("scripts.verifiers.causal_chain.OpsWriter") as mock_writer_cls,
        patch("boto3.Session"),
        patch("scripts.verifiers.causal_chain.emit_process_event"),
        patch("awswrangler.athena.read_sql_query") as mock_query,
        patch("asyncio.sleep", new_callable=AsyncMock),
        patch("time.time") as mock_time,
    ):
        mock_writer_cls.return_value._bucket.return_value = "test-bucket"
        mock_query.return_value = pd.DataFrame({"count": [0]})
        # start_time=0, first loop check=0 (enters), second loop check=200 (exits; max_wait=180)
        mock_time.side_effect = [0, 0, 200]
        result = await verifier.verify()
    assert result.status == VerifierStatus.FAIL
    assert "Causal chain broken" in result.message
