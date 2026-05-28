"""Tests for the SchemaIntegrityVerifier."""

import dataclasses
from typing import ClassVar
from unittest.mock import patch

import pytest

from scripts.verifiers.harness import VerifierStatus
from scripts.verifiers.schema_integrity import SchemaIntegrityVerifier


@dataclasses.dataclass
class MockTelemetryModel:
    TABLE_NAME: ClassVar[str] = "telemetry_mock"
    id: str
    value: float


@dataclasses.dataclass
class MockOpsModel:
    id: str
    status: str


@pytest.mark.asyncio
async def test_schema_integrity_classvar_exclusion():
    """Verify that ClassVar fields are excluded from comparison."""
    # We mock MODEL_MAP to use our mock models
    table_map = {"telemetry_mock": MockTelemetryModel}

    with (
        patch("boto3.Session"),
        patch("scripts.ops_writer.OpsWriter._bucket", return_value="test-bucket"),
        patch("awswrangler.catalog.get_table_types") as mock_get_types,
        patch("scripts.verifiers.schema_integrity.MODEL_MAP", table_map),
    ):
        # Mock Athena to return only 'id', 'value', 'ingested_at', 'trade_date'
        # (TABLE_NAME should NOT be expected)
        mock_get_types.return_value = {"id": "string", "value": "double", "ingested_at": "timestamp", "trade_date": "date"}

        verifier = SchemaIntegrityVerifier()
        result = await verifier.verify()

        assert result.status == VerifierStatus.PASS
        assert "TABLE_NAME" not in result.message


@pytest.mark.asyncio
async def test_schema_integrity_injected_cols_ops():
    """Verify injected_cols for ops tables."""
    table_map = {"ops_mock": MockOpsModel}

    with (
        patch("boto3.Session"),
        patch("scripts.ops_writer.OpsWriter._bucket", return_value="test-bucket"),
        patch("awswrangler.catalog.get_table_types") as mock_get_types,
        patch("scripts.verifiers.schema_integrity.MODEL_MAP", table_map),
    ):
        # Missing created_timestamp and last_updated_timestamp
        mock_get_types.return_value = {"id": "string", "status": "string"}

        verifier = SchemaIntegrityVerifier()
        result = await verifier.verify()

        assert result.status == VerifierStatus.FAIL
        assert "created_timestamp" in result.message
        assert "last_updated_timestamp" in result.message
        # trade_date should NOT be in the message for ops table (not expected)
        assert "trade_date" not in result.message


@pytest.mark.asyncio
async def test_schema_integrity_injected_cols_telemetry():
    """Verify injected_cols for telemetry tables."""
    table_map = {"telemetry_mock": MockOpsModel}  # Just use same model

    with (
        patch("boto3.Session"),
        patch("scripts.ops_writer.OpsWriter._bucket", return_value="test-bucket"),
        patch("awswrangler.catalog.get_table_types") as mock_get_types,
        patch("scripts.verifiers.schema_integrity.MODEL_MAP", table_map),
    ):
        # Missing ingested_at and trade_date
        mock_get_types.return_value = {"id": "string", "status": "string"}

        verifier = SchemaIntegrityVerifier()
        result = await verifier.verify()

        assert result.status == VerifierStatus.FAIL
        assert "ingested_at" in result.message
        assert "trade_date" in result.message
        # created_timestamp should NOT be in the message for telemetry
        assert "created_timestamp" not in result.message


@pytest.mark.asyncio
async def test_schema_integrity_severity_is_warn():
    """Verify that failures produce WARN status and use WARN severity."""
    table_map = {"ops_mock": MockOpsModel}

    with (
        patch("boto3.Session"),
        patch("scripts.ops_writer.OpsWriter._bucket", return_value="test-bucket"),
        patch("awswrangler.catalog.get_table_types") as mock_get_types,
        patch("scripts.verifiers.schema_integrity.MODEL_MAP", table_map),
    ):
        # Force a drift
        mock_get_types.return_value = {"id": "string"}

        verifier = SchemaIntegrityVerifier()
        result = await verifier.verify()

        assert result.status == VerifierStatus.FAIL
        from scripts.verifiers.harness import VerifierSeverity

        assert result.severity == VerifierSeverity.WARN
