"""Unit tests for postflight verification gates."""

from unittest.mock import MagicMock, patch

import pytest

from scripts.executor.postflight import _run_verifiers_gate, finalize
from scripts.verifiers.harness import VerifierResult, VerifierSeverity, VerifierStatus


@pytest.fixture
def mock_v3_plan():
    plan = MagicMock()
    plan.verification_tier = "V3"
    return plan


@pytest.fixture
def mock_v2_plan():
    plan = MagicMock()
    plan.verification_tier = "V2"
    return plan


@patch("scripts.executor.plan.ExecutionPlan.load")
@patch("scripts.verifiers.run_all_verifiers")
@pytest.mark.asyncio
async def test_run_verifiers_gate_blocks_v3_hard_fail(mock_run_all, mock_load_plan, mock_v3_plan):
    mock_load_plan.return_value = mock_v3_plan
    mock_run_all.return_value = [
        VerifierResult(name="TestVerifier", status=VerifierStatus.FAIL, severity=VerifierSeverity.HARD_GATE, message="Fail")
    ]

    # _run_verifiers_gate uses asyncio.run, which we need to handle or mock.
    # Actually, _run_verifiers_gate is a sync function that calls asyncio.run.
    # So we don't need pytest-asyncio for the top-level call if we mock the internal run_all_verifiers.

    with patch("asyncio.run", return_value=mock_run_all.return_value):
        assert _run_verifiers_gate("rec-123") is False


@patch("scripts.executor.plan.ExecutionPlan.load")
@patch("scripts.verifiers.run_all_verifiers")
def test_run_verifiers_gate_allows_v3_advisory_fail(mock_run_all, mock_load_plan, mock_v3_plan):
    mock_load_plan.return_value = mock_v3_plan
    results = [
        VerifierResult(name="TestVerifier", status=VerifierStatus.FAIL, severity=VerifierSeverity.ADVISORY, message="Minor")
    ]

    with patch("asyncio.run", return_value=results):
        assert _run_verifiers_gate("rec-123") is True


@patch("scripts.executor.plan.ExecutionPlan.load")
@patch("scripts.verifiers.run_all_verifiers")
def test_run_verifiers_gate_allows_v2_hard_fail(mock_run_all, mock_load_plan, mock_v2_plan):
    mock_load_plan.return_value = mock_v2_plan
    results = [
        VerifierResult(name="TestVerifier", status=VerifierStatus.FAIL, severity=VerifierSeverity.HARD_GATE, message="Fail")
    ]

    with patch("asyncio.run", return_value=results):
        assert _run_verifiers_gate("rec-123") is True


@patch("scripts.executor.plan.ExecutionPlan.load")
def test_run_verifiers_gate_exception_returns_false(mock_load_plan):
    """Gap 5: an unexpected exception in the verifier harness must return False (fail-closed)."""
    mock_load_plan.side_effect = Exception("no plan on disk")
    with patch("asyncio.run", side_effect=RuntimeError("harness exploded")):
        with patch("scripts.executor.postflight.emit_process_event") as mock_emit:
            assert _run_verifiers_gate("rec-123") is False
            mock_emit.assert_called_once_with("verification_gate_error", {"error": "harness exploded"})


@patch("scripts.executor.postflight._run_verifiers_gate")
@patch("scripts.executor.postflight.subprocess.run")
@patch("scripts.executor.postflight.wait_for_ci")
@patch("scripts.executor.postflight._safe_merge_origin_main")
def test_finalize_aborts_on_gate_failure(mock_safe_merge, mock_wait_ci, mock_git_run, mock_gate):
    mock_gate.return_value = False
    mock_wait_ci.return_value = (True, "success")
    mock_git_run.return_value = MagicMock(returncode=0, stdout="http://pr-url")
    mock_safe_merge.return_value = True

    # Need to bypass a lot of gh calls
    with patch("scripts.executor.jsonl_store.load_recommendation", return_value={"id": "rec-123", "title": "Test"}):
        with patch("scripts.executor.plan.ExecutionPlan.load", return_value=MagicMock()):
            result = finalize("rec-123")
            assert result is None
            mock_gate.assert_called_once_with("rec-123")
