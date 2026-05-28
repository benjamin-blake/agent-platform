"""Unit tests for src/data/handlers/agent_telemetry.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import src.data.handlers.agent_telemetry as telemetry_mod
from src.data.handlers.agent_telemetry import (
    _reset_context,
    close_invocation,
    open_invocation,
    record_model_call,
)


@pytest.fixture(autouse=True)
def _reset_module_context():
    """Reset module-level _ctx before and after every test."""
    _reset_context()
    yield
    _reset_context()


@pytest.fixture(autouse=True)
def _force_emit(monkeypatch: pytest.MonkeyPatch):
    """Force-enable telemetry so no-op guard doesn't suppress test emissions."""
    monkeypatch.setenv("_TELEMETRY_FORCE_EMIT", "1")


class TestOpenInvocation:
    """Tests for open_invocation()."""

    def test_open_invocation_emits_record(self) -> None:
        mock_writer = MagicMock()
        with patch.object(telemetry_mod, "_OpsWriter", return_value=mock_writer):
            invocation_id = open_invocation(
                agent_name="doc-freshness",
                trigger="eventbridge",
                model="gemini-2.5-flash",
                provider="gemini",
            )

        assert invocation_id != ""
        mock_writer.emit.assert_called_once()
        table_name, record = mock_writer.emit.call_args.args
        assert table_name == "telemetry_agent_invocations"
        assert record["invocation_id"] == invocation_id
        assert record["agent_name"] == "doc-freshness"
        assert record["trigger"] == "eventbridge"
        assert record["outcome"] == "running"
        assert record["started_at"] is not None

    def test_open_invocation_returns_uuid_string(self) -> None:
        with patch.object(telemetry_mod, "_OpsWriter", return_value=MagicMock()):
            result = open_invocation(agent_name="test", trigger="manual", model="gpt-4o", provider="github_models")
        assert isinstance(result, str)
        assert len(result) == 36  # UUID format

    def test_open_invocation_normalises_provider_hyphens(self) -> None:
        mock_writer = MagicMock()
        with patch.object(telemetry_mod, "_OpsWriter", return_value=mock_writer):
            open_invocation(agent_name="test", trigger="manual", model="m", provider="copilot-sdk")
        _, record = mock_writer.emit.call_args.args
        assert record["provider"] == "copilot_sdk"

    def test_open_invocation_stores_context(self) -> None:
        with patch.object(telemetry_mod, "_OpsWriter", return_value=MagicMock()):
            inv_id = open_invocation(agent_name="doc-freshness", trigger="manual", model="gemini-2.5-flash", provider="gemini")
        assert telemetry_mod._ctx.invocation_id == inv_id
        assert telemetry_mod._ctx.agent_name == "doc-freshness"
        assert telemetry_mod._ctx.started_at is not None


class TestCloseInvocation:
    """Tests for close_invocation()."""

    def test_close_invocation_emits_complete_record(self) -> None:
        mock_writer = MagicMock()
        with patch.object(telemetry_mod, "_OpsWriter", return_value=mock_writer):
            open_invocation(
                agent_name="doc-freshness",
                trigger="eventbridge",
                model="gemini-2.5-flash",
                provider="gemini",
            )
            close_invocation(outcome="success", findings_count=3)

        assert mock_writer.emit.call_count == 2
        table_name, record = mock_writer.emit.call_args.args
        assert table_name == "telemetry_agent_invocations"
        assert record["outcome"] == "success"
        assert record["findings_count"] == 3
        assert record["ended_at"] is not None
        assert record["duration_seconds"] is not None
        assert record["duration_seconds"] >= 0

    def test_close_invocation_resets_context(self) -> None:
        with patch.object(telemetry_mod, "_OpsWriter", return_value=MagicMock()):
            open_invocation(
                agent_name="doc-freshness",
                trigger="manual",
                model="gemini-2.5-flash",
                provider="gemini",
            )
            close_invocation(outcome="success")

        assert telemetry_mod._ctx.invocation_id is None

    def test_close_invocation_carries_invocation_id(self) -> None:
        mock_writer = MagicMock()
        with patch.object(telemetry_mod, "_OpsWriter", return_value=mock_writer):
            inv_id = open_invocation(agent_name="agent-x", trigger="manual", model="m", provider="gemini")
            close_invocation(outcome="failed", error="API timeout")

        _, record = mock_writer.emit.call_args.args
        assert record["invocation_id"] == inv_id
        assert record["error"] == "API timeout"

    def test_close_invocation_resets_context_on_emit_error(self) -> None:
        mock_writer = MagicMock()
        mock_writer.emit.side_effect = [None, RuntimeError("S3 write failed")]
        with patch.object(telemetry_mod, "_OpsWriter", return_value=mock_writer):
            open_invocation(agent_name="x", trigger="manual", model="m", provider="gemini")
            close_invocation(outcome="success")

        # Context must be reset even if emit raised
        assert telemetry_mod._ctx.invocation_id is None


class TestRecordModelCall:
    """Tests for record_model_call()."""

    def test_record_model_call_with_invocation_id(self) -> None:
        mock_writer = MagicMock()
        with patch.object(telemetry_mod, "_OpsWriter", return_value=mock_writer):
            inv_id = open_invocation(
                agent_name="doc-freshness",
                trigger="eventbridge",
                model="gemini-2.5-flash",
                provider="gemini",
            )
            record_model_call(
                provider="gemini",
                model="gemini-2.5-flash",
                purpose="findings",
            )

        # emit called twice: open_invocation + record_model_call
        assert mock_writer.emit.call_count == 2
        table_name, record = mock_writer.emit.call_args.args
        assert table_name == "telemetry_model_calls"
        assert record["invocation_id"] == inv_id
        assert record["provider"] == "gemini"
        assert record["model"] == "gemini-2.5-flash"
        assert record["purpose"] == "findings"

    def test_record_model_call_without_invocation(self) -> None:
        mock_writer = MagicMock()
        with patch.object(telemetry_mod, "_OpsWriter", return_value=mock_writer):
            record_model_call(
                provider="github_models",
                model="gpt-4.1-mini",
                purpose="comparison",
            )

        mock_writer.emit.assert_called_once()
        _, record = mock_writer.emit.call_args.args
        assert record["invocation_id"] is None

    def test_normalises_provider_hyphens_in_model_call(self) -> None:
        mock_writer = MagicMock()
        with patch.object(telemetry_mod, "_OpsWriter", return_value=mock_writer):
            record_model_call(
                provider="copilot-sdk",
                model="claude-haiku-4.5",
                purpose="findings",
            )

        _, record = mock_writer.emit.call_args.args
        assert record["provider"] == "copilot_sdk"

    def test_record_model_call_passes_optional_fields(self) -> None:
        mock_writer = MagicMock()
        with patch.object(telemetry_mod, "_OpsWriter", return_value=mock_writer):
            record_model_call(
                provider="gemini",
                model="gemini-2.5-pro",
                purpose="findings",
                duration_seconds=15,
                tokens_input=500,
                tokens_output=200,
                error=None,
            )

        _, record = mock_writer.emit.call_args.args
        assert record["duration_seconds"] == 15
        assert record["tokens_input"] == 500
        assert record["tokens_output"] == 200


class TestNoopGuard:
    """Tests for PYTEST_CURRENT_TEST suppression."""

    def test_noop_under_pytest_without_force_emit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Override the autouse fixture's force-emit
        monkeypatch.setenv("PYTEST_CURRENT_TEST", "test_noop_under_pytest_without_force_emit")
        monkeypatch.delenv("_TELEMETRY_FORCE_EMIT", raising=False)

        mock_writer = MagicMock()
        with patch.object(telemetry_mod, "_OpsWriter", return_value=mock_writer):
            open_invocation(
                agent_name="doc-freshness",
                trigger="manual",
                model="gemini-2.5-flash",
                provider="gemini",
            )

        mock_writer.emit.assert_not_called()

    def test_not_noop_when_force_emit_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PYTEST_CURRENT_TEST", "test_not_noop_when_force_emit_set")
        monkeypatch.setenv("_TELEMETRY_FORCE_EMIT", "1")

        mock_writer = MagicMock()
        with patch.object(telemetry_mod, "_OpsWriter", return_value=mock_writer):
            open_invocation(
                agent_name="doc-freshness",
                trigger="manual",
                model="gemini-2.5-flash",
                provider="gemini",
            )

        mock_writer.emit.assert_called_once()


class TestErrorSafety:
    """Tests that all public functions are error-safe."""

    def test_open_invocation_does_not_raise_on_emit_error(self) -> None:
        mock_writer = MagicMock()
        mock_writer.emit.side_effect = RuntimeError("S3 unavailable")
        with patch.object(telemetry_mod, "_OpsWriter", return_value=mock_writer):
            result = open_invocation(agent_name="test", trigger="manual", model="m", provider="gemini")
        # Must not raise; returns empty string on error
        assert isinstance(result, str)

    def test_close_invocation_does_not_raise_on_emit_error(self) -> None:
        mock_writer = MagicMock()
        mock_writer.emit.side_effect = RuntimeError("S3 unavailable")
        with patch.object(telemetry_mod, "_OpsWriter", return_value=mock_writer):
            close_invocation(outcome="success")
        # Must not raise; context reset happens in finally

    def test_record_model_call_does_not_raise_on_emit_error(self) -> None:
        mock_writer = MagicMock()
        mock_writer.emit.side_effect = RuntimeError("S3 unavailable")
        with patch.object(telemetry_mod, "_OpsWriter", return_value=mock_writer):
            record_model_call(provider="gemini", model="m", purpose="findings")
        # Must not raise
