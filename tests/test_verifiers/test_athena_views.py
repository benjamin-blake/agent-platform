"""Tests for the AthenaViewsVerifier."""

from unittest.mock import patch

import pandas as pd
import pytest

from scripts.verifiers.athena_views import AthenaViewsVerifier
from scripts.verifiers.harness import VerifierStatus


@pytest.mark.asyncio
async def test_athena_views_no_imports():
    with patch.dict("sys.modules", {"boto3": None, "awswrangler": None}):
        verifier = AthenaViewsVerifier()
        # We need to bypass the local import in the file if it already happened,
        # but since we are running in a fresh test process or mocking sys.modules before import:
        # Actually, the import is inside verify().
        result = await verifier.verify()
        assert result.status == VerifierStatus.SKIPPED
        assert "not available" in result.message


@pytest.mark.asyncio
async def test_athena_views_no_auth():
    with patch("boto3.Session") as mock_session:
        mock_session.return_value.client.return_value.get_caller_identity.side_effect = Exception("No auth")
        verifier = AthenaViewsVerifier()
        result = await verifier.verify()
        assert result.status == VerifierStatus.SKIPPED
        assert "session inactive" in result.message


@pytest.mark.asyncio
async def test_athena_views_pass():
    with patch("boto3.Session"):
        with patch("awswrangler.athena.read_sql_query") as mock_query:
            mock_query.return_value = pd.DataFrame({"cnt": [42]})
            verifier = AthenaViewsVerifier()
            result = await verifier.verify()
            assert result.status == VerifierStatus.PASS
            assert "Found 42 decisions" in result.message


@pytest.mark.asyncio
async def test_athena_views_query_fail():
    with patch("boto3.Session"):
        with patch("awswrangler.athena.read_sql_query") as mock_query:
            mock_query.side_effect = Exception("Query error")
            verifier = AthenaViewsVerifier()
            result = await verifier.verify()
            assert result.status == VerifierStatus.FAIL
            assert "Athena query failed" in result.message
