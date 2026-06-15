"""Tests for the DataQualityVerifier (Athena-based)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from scripts.verifiers.data_quality import DataQualityVerifier
from scripts.verifiers.harness import VerifierSeverity, VerifierStatus


@pytest.fixture
def verifier():
    return DataQualityVerifier()


def _make_check_result(
    verdict: str,
    table: str = "ops_recommendations",
    column: str | None = None,
    test_type: str = "not_null",
    violation_count: int = 0,
) -> MagicMock:
    cr = MagicMock()
    cr.verdict = verdict
    cr.violation_count = violation_count
    cr.check = MagicMock()
    cr.check.table = table
    cr.check.column = column
    cr.check.test_type = test_type
    return cr


def _run_result(
    verdict: str,
    passed: int = 0,
    failed: int = 0,
    warned: int = 0,
    errored: int = 0,
    hard_gated: int = 0,
    unavailable: int = 0,
    table: str = "ops_recommendations",
    test_type: str = "current_merge_key_unique",
) -> MagicMock:
    r = MagicMock()
    r.verdict = verdict
    r.passed = passed
    r.failed = failed
    r.warned = warned
    r.errored = errored
    r.hard_gated = hard_gated
    r.unavailable = unavailable
    results: list[MagicMock] = []
    results.extend(_make_check_result("PASS", table=table, test_type="not_null") for _ in range(passed))
    results.extend(
        _make_check_result("HARD_GATE", table=table, test_type=test_type, violation_count=1) for _ in range(hard_gated)
    )
    results.extend(
        _make_check_result("FAIL", table=table, test_type=test_type, violation_count=1) for _ in range(failed - hard_gated)
    )
    results.extend(_make_check_result("WARN", table=table, test_type="recency") for _ in range(warned))
    results.extend(_make_check_result("ERROR", table=table, test_type="row_count") for _ in range(errored))
    results.extend(_make_check_result("UNAVAILABLE", table=table, test_type=test_type) for _ in range(unavailable))
    r.results = results
    return r


def _dq_patches(run_result: MagicMock | None = None, yaml_count: int = 1):
    """Return a context manager stack for standard DQ verifier test patches."""
    mock_check = MagicMock()
    patches = [
        patch("boto3.Session"),
        patch("scripts.verifiers.data_quality._DQ_DIR"),
        patch("scripts.data_quality_runner.load_checks", return_value=([mock_check], {})),
        patch("scripts.data_quality_runner.load_tombstones", return_value=[]),
        patch("scripts.data_quality_runner.build_tombstone_checks", return_value=[]),
    ]
    if run_result is not None:
        patches.append(patch("scripts.data_quality_runner.run_checks", return_value=run_result))
    return patches


@pytest.mark.asyncio
async def test_verify_import_error(verifier):
    """Missing data_quality_runner → SKIP."""
    with patch.dict("sys.modules", {"scripts.data_quality_runner": None}):
        result = await verifier.verify()
    assert result.status == VerifierStatus.SKIPPED


@pytest.mark.asyncio
async def test_verify_credentials_unavailable(verifier):
    """Failed STS call → SKIP, not FAIL."""
    with patch("boto3.Session") as mock_session:
        mock_session.return_value.client.return_value.get_caller_identity.side_effect = Exception("No creds")
        result = await verifier.verify()
    assert result.status == VerifierStatus.SKIPPED
    assert "credentials unavailable" in result.message


@pytest.mark.asyncio
async def test_verify_no_yaml_files(verifier):
    """Empty DQ YAML dir → FAIL HARD_GATE."""
    with (
        patch("boto3.Session"),
        patch("scripts.verifiers.data_quality._DQ_DIR") as mock_dir,
    ):
        mock_dir.glob.return_value = []
        result = await verifier.verify()
    assert result.status == VerifierStatus.FAIL
    assert result.severity == VerifierSeverity.HARD_GATE


@pytest.mark.asyncio
async def test_verify_total_zero_fails(verifier):
    """run_checks returns 0 results → FAIL HARD_GATE."""
    run_result = MagicMock()
    run_result.verdict = "PASS"
    run_result.results = []

    with (
        patch("boto3.Session"),
        patch("scripts.verifiers.data_quality._DQ_DIR") as mock_dir,
        patch("scripts.data_quality_runner.load_checks", return_value=([MagicMock()], {})),
        patch("scripts.data_quality_runner.load_tombstones", return_value=[]),
        patch("scripts.data_quality_runner.build_tombstone_checks", return_value=[]),
        patch("scripts.data_quality_runner.run_checks", return_value=run_result),
    ):
        mock_dir.glob.return_value = [MagicMock()]
        result = await verifier.verify()
    assert result.status == VerifierStatus.FAIL
    assert result.severity == VerifierSeverity.HARD_GATE
    assert "0 checks" in result.message


@pytest.mark.asyncio
async def test_verify_pass(verifier):
    """run_checks returns PASS → VerifierStatus.PASS."""
    with (
        patch("boto3.Session"),
        patch("scripts.verifiers.data_quality._DQ_DIR") as mock_dir,
        patch("scripts.data_quality_runner.load_checks", return_value=([MagicMock()], {})),
        patch("scripts.data_quality_runner.load_tombstones", return_value=[]),
        patch("scripts.data_quality_runner.build_tombstone_checks", return_value=[]),
        patch("scripts.data_quality_runner.run_checks", return_value=_run_result("PASS", passed=10, warned=1)),
    ):
        mock_dir.glob.return_value = [MagicMock()]
        result = await verifier.verify()
    assert result.status == VerifierStatus.PASS
    assert "passed" in result.message


@pytest.mark.asyncio
async def test_verify_fail(verifier):
    """run_checks returns HARD_GATE → VerifierStatus.FAIL HARD_GATE with per-check breakdown."""
    run_result = _run_result(
        "HARD_GATE",
        failed=5,
        passed=5,
        hard_gated=5,
        table="ops_recommendations",
        test_type="current_merge_key_unique",
    )
    with (
        patch("boto3.Session"),
        patch("scripts.verifiers.data_quality._DQ_DIR") as mock_dir,
        patch("scripts.data_quality_runner.load_checks", return_value=([MagicMock()], {})),
        patch("scripts.data_quality_runner.load_tombstones", return_value=[]),
        patch("scripts.data_quality_runner.build_tombstone_checks", return_value=[]),
        patch("scripts.data_quality_runner.run_checks", return_value=run_result),
    ):
        mock_dir.glob.return_value = [MagicMock()]
        result = await verifier.verify()
    assert result.status == VerifierStatus.FAIL
    assert result.severity == VerifierSeverity.HARD_GATE
    assert "HARD_GATE" in result.message
    assert "ops_recommendations" in result.message
    assert "current_merge_key_unique" in result.message


@pytest.mark.asyncio
async def test_verify_skip_when_run_checks_returns_skip(verifier):
    """run_checks returns SKIP (boto3 unavailable) → VerifierStatus.SKIPPED."""
    run_result = MagicMock()
    run_result.verdict = "SKIP"
    run_result.results = []

    with (
        patch("boto3.Session"),
        patch("scripts.verifiers.data_quality._DQ_DIR") as mock_dir,
        patch("scripts.data_quality_runner.load_checks", return_value=([MagicMock()], {})),
        patch("scripts.data_quality_runner.load_tombstones", return_value=[]),
        patch("scripts.data_quality_runner.build_tombstone_checks", return_value=[]),
        patch("scripts.data_quality_runner.run_checks", return_value=run_result),
    ):
        mock_dir.glob.return_value = [MagicMock()]
        result = await verifier.verify()
    assert result.status == VerifierStatus.SKIPPED


@pytest.mark.asyncio
async def test_verify_degraded_returns_skipped_with_named_checks(verifier):
    """DEGRADED aggregate (reader unavailable) -> VerifierStatus.SKIPPED with unavailable checks named."""
    run_result = _run_result(
        "DEGRADED",
        unavailable=2,
        table="ops_recommendations",
        test_type="current_merge_key_unique",
    )
    with (
        patch("boto3.Session"),
        patch("scripts.verifiers.data_quality._DQ_DIR") as mock_dir,
        patch("scripts.data_quality_runner.load_checks", return_value=([MagicMock()], {})),
        patch("scripts.data_quality_runner.load_tombstones", return_value=[]),
        patch("scripts.data_quality_runner.build_tombstone_checks", return_value=[]),
        patch("scripts.data_quality_runner.run_checks", return_value=run_result),
    ):
        mock_dir.glob.return_value = [MagicMock()]
        result = await verifier.verify()
    assert result.status == VerifierStatus.SKIPPED
    assert "degraded" in result.message.lower()
    assert "backend unavailable" in result.message.lower()
    assert "ops_recommendations" in result.message


@pytest.mark.asyncio
async def test_verify_mixed_hard_gate_and_unavailable_returns_fail(verifier):
    """Mixed HARD_GATE + UNAVAILABLE -> FAIL at HARD_GATE severity (real failure dominates)."""
    run_result = _run_result(
        "HARD_GATE",
        hard_gated=1,
        unavailable=1,
        table="ops_recommendations",
        test_type="current_merge_key_unique",
    )
    with (
        patch("boto3.Session"),
        patch("scripts.verifiers.data_quality._DQ_DIR") as mock_dir,
        patch("scripts.data_quality_runner.load_checks", return_value=([MagicMock()], {})),
        patch("scripts.data_quality_runner.load_tombstones", return_value=[]),
        patch("scripts.data_quality_runner.build_tombstone_checks", return_value=[]),
        patch("scripts.data_quality_runner.run_checks", return_value=run_result),
    ):
        mock_dir.glob.return_value = [MagicMock()]
        result = await verifier.verify()
    assert result.status == VerifierStatus.FAIL
    assert result.severity == VerifierSeverity.HARD_GATE
