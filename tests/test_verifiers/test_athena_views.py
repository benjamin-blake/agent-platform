"""Tests for the AthenaViewsVerifier (VF-03: repointed at live DuckLake ops_decisions)."""

from unittest.mock import patch

import pytest

from scripts.verifiers.athena_views import AthenaViewsVerifier
from scripts.verifiers.harness import Hermeticity, VerifierStatus, VerifierTier


@pytest.mark.asyncio
async def test_athena_views_no_imports():
    with patch.dict("sys.modules", {"src.common.iceberg_reader": None}):
        verifier = AthenaViewsVerifier()
        result = await verifier.verify()
        assert result.status == VerifierStatus.SKIPPED
        assert "not available" in result.message


@pytest.mark.asyncio
async def test_athena_views_reader_unreachable_skips():
    with patch("src.common.iceberg_reader.DuckLakeReader") as mock_reader_cls:
        mock_reader_cls.return_value.named.side_effect = RuntimeError(
            "DUCKLAKE_READER_URL not set, SSM '/agent-platform/ducklake/reader_url' unavailable, "
            "terraform output 'ducklake_reader_function_url' unavailable, and "
            "lambda:GetFunctionUrlConfig fallback failed -- cannot reach the DuckLake reader "
            "(Decision 84: DuckLake is the sole ops backend)."
        )
        verifier = AthenaViewsVerifier()
        result = await verifier.verify()
        assert result.status == VerifierStatus.SKIPPED
        assert "unreachable" in result.message


@pytest.mark.asyncio
async def test_athena_views_pass():
    with patch("src.common.iceberg_reader.DuckLakeReader") as mock_reader_cls:
        mock_reader_cls.return_value.named.return_value = [{"ts": "2026-07-01T00:00:00+00:00"}]
        verifier = AthenaViewsVerifier()
        result = await verifier.verify()
        assert result.status == VerifierStatus.PASS
        assert "Live ops_decisions reachable" in result.message
        assert "fresh" not in result.message.lower()


@pytest.mark.asyncio
async def test_athena_views_query_fail():
    with patch("src.common.iceberg_reader.DuckLakeReader") as mock_reader_cls:
        mock_reader_cls.return_value.named.side_effect = RuntimeError(
            "ducklake_reader 'named_read' failed (HTTP 500): unknown verb"
        )
        verifier = AthenaViewsVerifier()
        result = await verifier.verify()
        assert result.status == VerifierStatus.FAIL
        assert "read failed" in result.message


@pytest.mark.asyncio
async def test_athena_views_unexpected_error_fails():
    with patch("src.common.iceberg_reader.DuckLakeReader") as mock_reader_cls:
        mock_reader_cls.return_value.named.side_effect = ValueError("boom")
        verifier = AthenaViewsVerifier()
        result = await verifier.verify()
        assert result.status == VerifierStatus.FAIL
        assert "unexpected error" in result.message


def test_athena_views_tier_v3():
    """AthenaViewsVerifier must declare tier V3 (corrected from inherited V1 default)."""
    assert AthenaViewsVerifier().tier == VerifierTier.V3


def test_athena_views_disposition():
    """AthenaViewsVerifier must declare NON_HERMETIC_BY_CONSTRUCTION."""
    assert AthenaViewsVerifier.hermeticity == Hermeticity.NON_HERMETIC_BY_CONSTRUCTION


def test_athena_views_covers_is_explicit():
    """(T3.16:c3) covers must be a narrow explicit list, never the "**" catch-all default."""
    covers = AthenaViewsVerifier.covers
    assert covers != ["**"]
    assert "**" not in covers
    assert covers  # non-empty


def test_athena_views_no_freshness_claim_in_source():
    """(T3.16:c3) the module must not assert a freshness claim it does not measure."""
    import pathlib

    src = pathlib.Path("scripts/verifiers/athena_views.py").read_text()
    assert "fresh" not in src.lower()
