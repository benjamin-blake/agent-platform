"""Unit tests for scripts/executor/telemetry.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reset_ctx() -> None:
    """Reset the module-level context between tests."""
    from scripts.executor.telemetry import _ctx

    _ctx.reset()


# ---------------------------------------------------------------------------
# TestTelemetryContext
# ---------------------------------------------------------------------------


class TestTelemetryContext:
    """Tests for TelemetryContext dataclass and get_context()."""

    def test_reset_clears_all_fields(self) -> None:
        from scripts.executor.telemetry import _ctx

        _ctx.session_id = "sid"
        _ctx.phase_id = "pid"
        _ctx.step_id = "stepid"
        _ctx.rec_id = "rec-001"
        _ctx.branch = "agent/rec-001"
        _ctx.session_started_at = "2026-01-01T00:00:00+00:00"
        _ctx.phase_started_at = "2026-01-01T00:00:01+00:00"
        _ctx.phase_order = 3
        _ctx.phase_attempt_number = 2
        _ctx.execution_attempt = 2

        _ctx.reset()

        assert _ctx.session_id is None
        assert _ctx.phase_id is None
        assert _ctx.step_id is None
        assert _ctx.rec_id is None
        assert _ctx.branch is None
        assert _ctx.session_started_at is None
        assert _ctx.phase_started_at is None
        assert _ctx.phase_order == 0
        assert _ctx.phase_attempt_number == 1
        assert _ctx.execution_attempt == 1
        assert _ctx.workflow == "executor"

    def test_get_context_returns_singleton(self) -> None:
        from scripts.executor.telemetry import _ctx, get_context

        ctx = get_context()
        assert ctx is _ctx

    def setup_method(self) -> None:
        _reset_ctx()


# ---------------------------------------------------------------------------
# TestOpenCloseSession
# ---------------------------------------------------------------------------


class TestOpenCloseSession:
    """Tests for open_session() and close_session()."""

    def setup_method(self) -> None:
        _reset_ctx()

    def test_open_session_generates_uuid_and_stores_in_ctx(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("_TELEMETRY_FORCE_EMIT", "1")
        with patch("scripts.executor.telemetry._OpsWriter") as mock_writer_cls:
            mock_writer_cls.return_value = MagicMock()
            from scripts.executor.telemetry import _ctx, open_session

            sid = open_session(workflow="executor", rec_ids=["rec-001"], branch="agent/rec-001")

        assert sid is not None
        assert len(sid) == 36  # UUID format
        assert _ctx.session_id == sid
        assert _ctx.branch == "agent/rec-001"
        assert _ctx.rec_id == "rec-001"
        assert _ctx.rec_ids == ["rec-001"]

    def test_open_session_emits_running_record(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("_TELEMETRY_FORCE_EMIT", "1")
        with patch("scripts.executor.telemetry._OpsWriter") as mock_writer_cls:
            mock_instance = MagicMock()
            mock_writer_cls.return_value = mock_instance
            from scripts.executor.telemetry import open_session

            open_session(workflow="executor", rec_ids=["rec-001"], branch="agent/rec-001")

        assert mock_instance.emit.called
        table, record = mock_instance.emit.call_args[0]
        assert table == "telemetry_sessions"
        assert record["outcome"] == "running"
        assert record["workflow"] == "executor"
        assert record["ended_at"] is None

    def test_close_session_emits_complete_record(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("_TELEMETRY_FORCE_EMIT", "1")
        with patch("scripts.executor.telemetry._OpsWriter") as mock_writer_cls:
            mock_instance = MagicMock()
            mock_writer_cls.return_value = mock_instance
            from scripts.executor.telemetry import close_session, open_session

            open_session(workflow="executor", rec_ids=["rec-001"], branch="b")
            close_session(outcome="success")

        calls = mock_instance.emit.call_args_list
        assert len(calls) == 2
        _table_open, rec_open = calls[0][0]
        _table_close, rec_close = calls[1][0]
        assert rec_open["outcome"] == "running"
        assert rec_close["outcome"] == "success"
        assert rec_close["ended_at"] is not None
        assert rec_close["duration_seconds"] is not None

    def test_close_session_resets_context(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("_TELEMETRY_FORCE_EMIT", "1")
        with patch("scripts.executor.telemetry._OpsWriter") as mock_writer_cls:
            mock_writer_cls.return_value = MagicMock()
            from scripts.executor.telemetry import _ctx, close_session, open_session

            open_session(workflow="executor")
            assert _ctx.session_id is not None
            close_session(outcome="failed")

        assert _ctx.session_id is None
        assert _ctx.branch is None

    def test_close_session_passes_failure_fields(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("_TELEMETRY_FORCE_EMIT", "1")
        with patch("scripts.executor.telemetry._OpsWriter") as mock_writer_cls:
            mock_instance = MagicMock()
            mock_writer_cls.return_value = mock_instance
            from scripts.executor.telemetry import close_session, open_session

            open_session(workflow="executor")
            close_session(
                outcome="failed",
                failure_reason="branch setup failed",
                failure_phase="preflight",
            )

        _table, record = mock_instance.emit.call_args_list[-1][0]
        assert record["failure_reason"] == "branch setup failed"
        assert record["failure_phase"] == "preflight"


# ---------------------------------------------------------------------------
# TestOpenClosePhase
# ---------------------------------------------------------------------------


class TestOpenClosePhase:
    """Tests for open_phase() and close_phase()."""

    def setup_method(self) -> None:
        _reset_ctx()

    def test_open_phase_generates_uuid_and_stores_in_ctx(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("_TELEMETRY_FORCE_EMIT", "1")
        with patch("scripts.executor.telemetry._OpsWriter") as mock_writer_cls:
            mock_writer_cls.return_value = MagicMock()
            from scripts.executor.telemetry import _ctx, open_phase, open_session

            open_session(workflow="executor")
            pid = open_phase(phase="preflight", phase_order=1)

        assert pid is not None
        assert _ctx.phase_id == pid
        assert _ctx.phase == "preflight"
        assert _ctx.phase_order == 1

    def test_open_phase_emits_running_record(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("_TELEMETRY_FORCE_EMIT", "1")
        with patch("scripts.executor.telemetry._OpsWriter") as mock_writer_cls:
            mock_instance = MagicMock()
            mock_writer_cls.return_value = mock_instance
            from scripts.executor.telemetry import open_phase, open_session

            open_session(workflow="executor")
            open_phase(phase="preflight", phase_order=1)

        phase_calls = [c for c in mock_instance.emit.call_args_list if c[0][0] == "telemetry_phases"]
        assert len(phase_calls) == 1
        _table, record = phase_calls[0][0]
        assert record["outcome"] == "running"
        assert record["phase"] == "preflight"
        assert record["phase_order"] == 1

    def test_close_phase_emits_complete_record(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("_TELEMETRY_FORCE_EMIT", "1")
        with patch("scripts.executor.telemetry._OpsWriter") as mock_writer_cls:
            mock_instance = MagicMock()
            mock_writer_cls.return_value = mock_instance
            from scripts.executor.telemetry import close_phase, open_phase, open_session

            open_session(workflow="executor")
            open_phase(phase="preflight", phase_order=1)
            close_phase(outcome="success")

        phase_calls = [c for c in mock_instance.emit.call_args_list if c[0][0] == "telemetry_phases"]
        assert len(phase_calls) == 2
        _table, rec_close = phase_calls[1][0]
        assert rec_close["outcome"] == "success"
        assert rec_close["ended_at"] is not None

    def test_close_phase_clears_phase_ctx_fields(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("_TELEMETRY_FORCE_EMIT", "1")
        with patch("scripts.executor.telemetry._OpsWriter") as mock_writer_cls:
            mock_writer_cls.return_value = MagicMock()
            from scripts.executor.telemetry import _ctx, close_phase, open_phase, open_session

            open_session(workflow="executor")
            open_phase(phase="preflight", phase_order=1)
            close_phase(outcome="failed")

        assert _ctx.phase_id is None
        assert _ctx.phase is None
        assert _ctx.phase_started_at is None
        # session_id should still be set
        assert _ctx.session_id is not None

    def test_close_phase_without_open_phase_logs_warning(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.setenv("_TELEMETRY_FORCE_EMIT", "1")
        import logging

        with patch("scripts.executor.telemetry._OpsWriter") as mock_writer_cls:
            mock_instance = MagicMock()
            mock_writer_cls.return_value = mock_instance
            from scripts.executor.telemetry import close_phase, open_session

            open_session(workflow="executor")
            with caplog.at_level(logging.WARNING, logger="scripts.executor.telemetry"):
                close_phase(outcome="failed")

        assert "no open phase" in caplog.text
        # Should not have emitted a phase record
        phase_calls = [c for c in mock_instance.emit.call_args_list if c[0][0] == "telemetry_phases"]
        assert len(phase_calls) == 0


# ---------------------------------------------------------------------------
# TestEmitStep
# ---------------------------------------------------------------------------


class TestEmitStep:
    """Tests for emit_step()."""

    def setup_method(self) -> None:
        _reset_ctx()

    def test_emit_step_generates_uuid_and_stores_in_ctx(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("_TELEMETRY_FORCE_EMIT", "1")
        with patch("scripts.executor.telemetry._OpsWriter") as mock_writer_cls:
            mock_writer_cls.return_value = MagicMock()
            from scripts.executor.telemetry import _ctx, emit_step, open_phase, open_session

            open_session(workflow="executor")
            open_phase(phase="implementation", phase_order=4)
            step_id = emit_step(
                step_number=1,
                total_steps=3,
                title="Create file",
                outcome="success",
                started_at="2026-01-01T00:00:00+00:00",
            )

        assert step_id is not None
        assert _ctx.step_id == step_id

    def test_emit_step_populates_fks_from_context(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("_TELEMETRY_FORCE_EMIT", "1")
        with patch("scripts.executor.telemetry._OpsWriter") as mock_writer_cls:
            mock_instance = MagicMock()
            mock_writer_cls.return_value = mock_instance
            from scripts.executor.telemetry import emit_step, open_phase, open_session

            open_session(workflow="executor", rec_ids=["rec-001"])
            open_phase(phase="implementation", phase_order=4)
            emit_step(
                step_number=1,
                total_steps=3,
                title="Test step",
                outcome="success",
                started_at="2026-01-01T00:00:00+00:00",
            )

        step_calls = [c for c in mock_instance.emit.call_args_list if c[0][0] == "telemetry_steps"]
        assert len(step_calls) == 1
        _table, record = step_calls[0][0]
        assert record["session_id"] is not None
        assert record["phase_id"] is not None
        assert record["step_number"] == 1
        assert record["total_steps"] == 3
        assert record["outcome"] == "success"

    def test_emit_step_with_all_optional_fields(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("_TELEMETRY_FORCE_EMIT", "1")
        with patch("scripts.executor.telemetry._OpsWriter") as mock_writer_cls:
            mock_instance = MagicMock()
            mock_writer_cls.return_value = mock_instance
            from scripts.executor.telemetry import emit_step, open_phase, open_session

            open_session(workflow="executor")
            open_phase(phase="implementation", phase_order=4)
            emit_step(
                step_number=2,
                total_steps=5,
                title="Modify file",
                outcome="acceptance_failed",
                retry_count=1,
                target_file="src/main.py",
                action="modify",
                started_at="2026-01-01T00:00:00+00:00",
                ended_at="2026-01-01T00:00:05+00:00",
                acceptance_command="grep -q 'def foo' src/main.py",
                acceptance_passed=False,
                lines_added=5,
                lines_removed=2,
            )

        step_calls = [c for c in mock_instance.emit.call_args_list if c[0][0] == "telemetry_steps"]
        _table, record = step_calls[0][0]
        assert record["target_file"] == "src/main.py"
        assert record["acceptance_passed"] is False
        assert record["lines_added"] == 5
        assert record["duration_seconds"] == 5


# ---------------------------------------------------------------------------
# TestEmitModelCall
# ---------------------------------------------------------------------------


class TestEmitModelCall:
    """Tests for emit_model_call()."""

    def setup_method(self) -> None:
        _reset_ctx()

    def test_emit_model_call_populates_fks_from_context(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("_TELEMETRY_FORCE_EMIT", "1")
        with patch("scripts.executor.telemetry._OpsWriter") as mock_writer_cls:
            mock_instance = MagicMock()
            mock_writer_cls.return_value = mock_instance
            from scripts.executor.telemetry import emit_model_call, open_phase, open_session

            open_session(workflow="executor")
            open_phase(phase="plan_generation", phase_order=2)
            call_id = emit_model_call(
                provider="copilot_cli",
                model="gpt-5.4",
                purpose="planning",
            )

        assert call_id is not None
        calls = [c for c in mock_instance.emit.call_args_list if c[0][0] == "telemetry_model_calls"]
        assert len(calls) == 1
        _table, record = calls[0][0]
        assert record["provider"] == "copilot_cli"
        assert record["model"] == "gpt-5.4"
        assert record["purpose"] == "planning"
        assert record["session_id"] is not None
        assert record["phase_id"] is not None

    def test_emit_model_call_with_error_field(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("_TELEMETRY_FORCE_EMIT", "1")
        with patch("scripts.executor.telemetry._OpsWriter") as mock_writer_cls:
            mock_instance = MagicMock()
            mock_writer_cls.return_value = mock_instance
            from scripts.executor.telemetry import emit_model_call, open_phase, open_session

            open_session(workflow="executor")
            open_phase(phase="postflight", phase_order=5)
            emit_model_call(
                provider="copilot_cli",
                model="gpt-5.4",
                purpose="code_review",
                exit_code=1,
                error="timeout",
            )

        calls = [c for c in mock_instance.emit.call_args_list if c[0][0] == "telemetry_model_calls"]
        _table, record = calls[0][0]
        assert record["exit_code"] == 1
        assert record["error"] == "timeout"


# ---------------------------------------------------------------------------
# TestEmitProcessEvent
# ---------------------------------------------------------------------------


class TestEmitProcessEvent:
    """Tests for emit_process_event() across all tiers."""

    def setup_method(self) -> None:
        _reset_ctx()

    def test_emit_process_event_decision_tier(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("_TELEMETRY_FORCE_EMIT", "1")
        with patch("scripts.executor.telemetry._OpsWriter") as mock_writer_cls:
            mock_instance = MagicMock()
            mock_writer_cls.return_value = mock_instance
            from scripts.executor.telemetry import emit_process_event, open_session

            open_session(workflow="executor")
            emit_process_event(
                tier="decision",
                category="already_implemented",
                severity="info",
                description="Acceptance passes on main",
            )

        calls = [c for c in mock_instance.emit.call_args_list if c[0][0] == "telemetry_process_events"]
        assert len(calls) == 1
        _table, record = calls[0][0]
        assert record["tier"] == "decision"
        assert record["category"] == "already_implemented"
        assert record["severity"] == "info"

    def test_emit_process_event_rework_tier(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("_TELEMETRY_FORCE_EMIT", "1")
        with patch("scripts.executor.telemetry._OpsWriter") as mock_writer_cls:
            mock_instance = MagicMock()
            mock_writer_cls.return_value = mock_instance
            from scripts.executor.telemetry import emit_process_event, open_session

            open_session(workflow="executor")
            emit_process_event(
                tier="rework",
                category="critique_needs_revision",
                severity="info",
                description="Critique iteration 1",
            )

        calls = [c for c in mock_instance.emit.call_args_list if c[0][0] == "telemetry_process_events"]
        _table, record = calls[0][0]
        assert record["tier"] == "rework"

    def test_emit_process_event_exception_tier(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("_TELEMETRY_FORCE_EMIT", "1")
        with patch("scripts.executor.telemetry._OpsWriter") as mock_writer_cls:
            mock_instance = MagicMock()
            mock_writer_cls.return_value = mock_instance
            from scripts.executor.telemetry import emit_process_event, open_session

            open_session(workflow="executor")
            emit_process_event(
                tier="exception",
                category="critique_cycling_detected",
                severity="warning",
                description="Cycling detected, auto-approving",
            )

        calls = [c for c in mock_instance.emit.call_args_list if c[0][0] == "telemetry_process_events"]
        _table, record = calls[0][0]
        assert record["tier"] == "exception"

    def test_emit_process_event_uses_rec_id_from_context(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("_TELEMETRY_FORCE_EMIT", "1")
        with patch("scripts.executor.telemetry._OpsWriter") as mock_writer_cls:
            mock_instance = MagicMock()
            mock_writer_cls.return_value = mock_instance
            from scripts.executor.telemetry import emit_process_event, open_session

            open_session(workflow="executor", rec_ids=["rec-999"])
            emit_process_event(
                tier="decision",
                category="scope_drift_detected",
                severity="warning",
                description="1 unplanned file",
            )

        calls = [c for c in mock_instance.emit.call_args_list if c[0][0] == "telemetry_process_events"]
        _table, record = calls[0][0]
        assert record["rec_id"] == "rec-999"


# ---------------------------------------------------------------------------
# TestEmitTranscript
# ---------------------------------------------------------------------------


class TestEmitTranscript:
    """Tests for emit_transcript()."""

    def setup_method(self) -> None:
        _reset_ctx()

    def test_emit_transcript_populates_fks(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("_TELEMETRY_FORCE_EMIT", "1")
        with patch("scripts.executor.telemetry._OpsWriter") as mock_writer_cls:
            mock_instance = MagicMock()
            mock_writer_cls.return_value = mock_instance
            from scripts.executor.telemetry import emit_transcript, open_phase, open_session

            open_session(workflow="executor", rec_ids=["rec-001"])
            open_phase(phase="implementation", phase_order=4)
            transcript_id = emit_transcript(
                purpose="implementation",
                local_path="logs/transcripts/impl-rec-001-step1-123.md",
                size_bytes=4096,
                model_used="gpt-5.4",
                rec_id="rec-001",
            )

        assert transcript_id is not None
        calls = [c for c in mock_instance.emit.call_args_list if c[0][0] == "telemetry_transcripts"]
        assert len(calls) == 1
        _table, record = calls[0][0]
        assert record["purpose"] == "implementation"
        assert record["size_bytes"] == 4096
        assert record["session_id"] is not None
        assert record["phase_id"] is not None


# ---------------------------------------------------------------------------
# TestNoOpInPytest
# ---------------------------------------------------------------------------


class TestNoOpInPytest:
    """Tests verifying the PYTEST_CURRENT_TEST no-op guard."""

    def setup_method(self) -> None:
        _reset_ctx()

    def test_emit_skipped_when_pytest_current_test_set_no_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # PYTEST_CURRENT_TEST is always set during pytest.
        # Do NOT set _TELEMETRY_FORCE_EMIT -- should be a no-op.
        monkeypatch.delenv("_TELEMETRY_FORCE_EMIT", raising=False)
        with patch("scripts.executor.telemetry._OpsWriter") as mock_writer_cls:
            mock_instance = MagicMock()
            mock_writer_cls.return_value = mock_instance
            from scripts.executor.telemetry import open_session

            open_session(workflow="executor")

        # emit should not have been called
        mock_instance.emit.assert_not_called()

    def test_emit_runs_when_force_emit_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # With _TELEMETRY_FORCE_EMIT=1, even under pytest the emit should run.
        monkeypatch.setenv("_TELEMETRY_FORCE_EMIT", "1")
        with patch("scripts.executor.telemetry._OpsWriter") as mock_writer_cls:
            mock_instance = MagicMock()
            mock_writer_cls.return_value = mock_instance
            from scripts.executor.telemetry import open_session

            open_session(workflow="executor")

        mock_instance.emit.assert_called_once()

    def test_close_session_no_op_skips_emit_but_still_resets_ctx(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("_TELEMETRY_FORCE_EMIT", raising=False)
        with patch("scripts.executor.telemetry._OpsWriter") as mock_writer_cls:
            mock_instance = MagicMock()
            mock_writer_cls.return_value = mock_instance
            from scripts.executor.telemetry import _ctx, close_session

            # Manually set ctx (simulating state from open_session no-op)
            _ctx.session_id = "test-sid"
            _ctx.session_started_at = "2026-01-01T00:00:00+00:00"
            close_session(outcome="failed")

        # emit should not have been called
        mock_instance.emit.assert_not_called()
        # but ctx should be reset
        assert _ctx.session_id is None


# ---------------------------------------------------------------------------
# TestErrorHandling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """Test that telemetry helpers catch exceptions from OpsWriter and never propagate."""

    def setup_method(self) -> None:
        _reset_ctx()

    def test_open_session_survives_ops_writer_exception(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging

        monkeypatch.setenv("_TELEMETRY_FORCE_EMIT", "1")
        with patch("scripts.executor.telemetry._OpsWriter") as mock_writer_cls:
            mock_instance = MagicMock()
            mock_instance.emit.side_effect = RuntimeError("disk full")
            mock_writer_cls.return_value = mock_instance
            from scripts.executor.telemetry import open_session

            with caplog.at_level(logging.WARNING, logger="scripts.executor.telemetry"):
                sid = open_session(workflow="executor")

        # Should return a UUID, not raise
        assert sid is not None
        assert "unexpected error" in caplog.text

    def test_close_session_survives_ops_writer_exception(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging

        monkeypatch.setenv("_TELEMETRY_FORCE_EMIT", "1")
        with patch("scripts.executor.telemetry._OpsWriter") as mock_writer_cls:
            mock_instance = MagicMock()
            # First call (open) succeeds, second (close) raises
            mock_instance.emit.side_effect = [None, RuntimeError("timeout")]
            mock_writer_cls.return_value = mock_instance
            from scripts.executor.telemetry import _ctx, close_session, open_session

            open_session(workflow="executor")
            with caplog.at_level(logging.WARNING, logger="scripts.executor.telemetry"):
                close_session(outcome="success")  # should not raise

        # ctx reset should still happen even after error
        assert _ctx.session_id is None

    def test_emit_step_survives_ops_writer_exception(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("_TELEMETRY_FORCE_EMIT", "1")
        with patch("scripts.executor.telemetry._OpsWriter") as mock_writer_cls:
            mock_instance = MagicMock()
            mock_instance.emit.side_effect = RuntimeError("network error")
            mock_writer_cls.return_value = mock_instance
            from scripts.executor.telemetry import emit_step, open_phase, open_session

            open_session(workflow="executor")
            open_phase(phase="implementation", phase_order=4)
            # Should not raise
            step_id = emit_step(
                step_number=1,
                total_steps=1,
                title="step",
                outcome="success",
                started_at="2026-01-01T00:00:00+00:00",
            )

        assert step_id is not None

    def test_emit_process_event_survives_ops_writer_exception(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("_TELEMETRY_FORCE_EMIT", "1")
        with patch("scripts.executor.telemetry._OpsWriter") as mock_writer_cls:
            mock_instance = MagicMock()
            mock_instance.emit.side_effect = RuntimeError("boom")
            mock_writer_cls.return_value = mock_instance
            from scripts.executor.telemetry import emit_process_event, open_session

            open_session(workflow="executor")
            event_id = emit_process_event(
                tier="exception",
                category="test",
                severity="error",
                description="test event",
            )

        assert event_id is not None
