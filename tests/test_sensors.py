"""Unit tests for the verifier sensor suite."""

import itertools
import time
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from scripts.verifiers.causal_chain import CausalChainVerifier
from scripts.verifiers.harness import VerifierSeverity, VerifierStatus
from scripts.verifiers.outbox_health import OutboxHealthVerifier
from scripts.verifiers.schema_integrity import SchemaIntegrityVerifier


@pytest.fixture
def mock_outbox_dir(tmp_path):
    outbox = tmp_path / "logs" / ".ops-outbox"
    outbox.mkdir(parents=True)
    return outbox


@pytest.mark.asyncio
async def test_outbox_health_fresh(mock_outbox_dir):
    table_dir = mock_outbox_dir / "test_table"
    table_dir.mkdir()
    f = table_dir / "fresh.jsonl"
    f.write_text("{}")

    # Just patch the specific line that finds the outbox_dir
    with patch("scripts.verifiers.outbox_health.Path.exists", return_value=True):
        with patch("scripts.verifiers.outbox_health.Path.rglob", return_value=[f]):
            with patch("scripts.verifiers.outbox_health.Path.stat") as mock_stat_func:
                ms = MagicMock()
                ms.st_mtime = time.time()
                mock_stat_func.return_value = ms

                verifier = OutboxHealthVerifier()
                result = await verifier.run()
                assert result.status == VerifierStatus.PASS
                assert "fresh files" in result.message


@pytest.mark.asyncio
async def test_outbox_health_stale_advisory(mock_outbox_dir):
    table_dir = mock_outbox_dir / "test_table"
    table_dir.mkdir()
    f = table_dir / "stale.jsonl"
    f.write_text("{}")

    stale_time = time.time() - (3 * 3600)
    with patch("scripts.verifiers.outbox_health.Path.exists", return_value=True):
        with patch("scripts.verifiers.outbox_health.Path.rglob", return_value=[f]):
            with patch("scripts.verifiers.outbox_health.Path.stat") as mock_stat_func:
                ms = MagicMock()
                ms.st_mtime = stale_time
                mock_stat_func.return_value = ms

                verifier = OutboxHealthVerifier()
                result = await verifier.run()
                assert result.status == VerifierStatus.FAIL
                assert result.severity == VerifierSeverity.ADVISORY
                assert ">2h" in result.message


@pytest.mark.asyncio
async def test_outbox_health_stale_hard(mock_outbox_dir):
    table_dir = mock_outbox_dir / "test_table"
    table_dir.mkdir()
    f = table_dir / "dead.jsonl"
    f.write_text("{}")

    stale_time = time.time() - (25 * 3600)
    with patch("scripts.verifiers.outbox_health.Path.exists", return_value=True):
        with patch("scripts.verifiers.outbox_health.Path.rglob", return_value=[f]):
            with patch("scripts.verifiers.outbox_health.Path.stat") as mock_stat_func:
                ms = MagicMock()
                ms.st_mtime = stale_time
                mock_stat_func.return_value = ms

                verifier = OutboxHealthVerifier()
                result = await verifier.run()
                assert result.status == VerifierStatus.FAIL
                assert result.severity == VerifierSeverity.HARD_GATE
                assert ">24h" in result.message


@pytest.mark.asyncio
async def test_schema_integrity_pass():
    with patch("awswrangler.catalog.get_table_types") as mock_get_cols:
        with patch("scripts.ops_writer.OpsWriter._bucket", return_value="test-bucket"):
            mock_get_cols.return_value = {
                "id": "string",
                "status": "string",
                "created_timestamp": "timestamp",
                "last_updated_timestamp": "timestamp",
                "ingested_at": "timestamp",
                "trade_date": "date",
            }

            with patch("scripts.verifiers.schema_integrity.MODEL_MAP", {"ops_recommendations": RecommendationMock}):
                verifier = SchemaIntegrityVerifier()
                result = await verifier.run()
                assert result.status == VerifierStatus.PASS


@pytest.mark.asyncio
async def test_schema_integrity_fail_drift():
    with patch("awswrangler.catalog.get_table_types") as mock_get_cols:
        with patch("scripts.ops_writer.OpsWriter._bucket", return_value="test-bucket"):
            mock_get_cols.return_value = {
                "id": "string",
                "created_timestamp": "timestamp",
                "last_updated_timestamp": "timestamp",
                "ingested_at": "timestamp",
                "trade_date": "date",
            }

            with patch("scripts.verifiers.schema_integrity.MODEL_MAP", {"ops_recommendations": RecommendationMock}):
                verifier = SchemaIntegrityVerifier()
                result = await verifier.run()
                assert result.status == VerifierStatus.FAIL
                assert "Missing columns in Athena: ['status']" in result.message


@pytest.mark.asyncio
async def test_causal_chain_pass():
    with (
        patch("awswrangler.athena.read_sql_query") as mock_query,
        patch("scripts.ops_writer.OpsWriter._bucket", return_value="test-bucket"),
        patch("scripts.ops_writer.OpsWriter.compact"),
        patch("scripts.verifiers.causal_chain.emit_process_event"),
        patch("boto3.Session"),
    ):
        mock_query.return_value = pd.DataFrame([{"count": 1}])
        verifier = CausalChainVerifier()
        result = await verifier.run()
    assert result.status == VerifierStatus.PASS
    assert "verified" in result.message


@pytest.mark.asyncio
async def test_causal_chain_fail_timeout():
    with (
        patch("awswrangler.athena.read_sql_query") as mock_query,
        patch("scripts.ops_writer.OpsWriter._bucket", return_value="test-bucket"),
        patch("scripts.ops_writer.OpsWriter.compact"),
        patch("scripts.verifiers.causal_chain.emit_process_event"),
        patch("boto3.Session"),
        patch("asyncio.sleep", return_value=None),
        # itertools.count with a step (200) larger than max_wait (180): guarantees elapsed exceeds
        # max_wait between ANY two distinct time.time() calls, regardless of how many incidental
        # extra calls (e.g. logging.LogRecord's own timestamp, per log line emitted) land before
        # start_time is captured -- an exhaustible fixed-length side_effect list is fragile to that.
        patch("time.time", side_effect=itertools.count(0, 200)),
    ):
        mock_query.return_value = pd.DataFrame([{"count": 0}])
        verifier = CausalChainVerifier()
        result = await verifier.run()
    assert result.status == VerifierStatus.FAIL
    assert "broken" in result.message


class RecommendationMock:
    model_fields = {"id": MagicMock(), "status": MagicMock()}
    __name__ = "Recommendation"
