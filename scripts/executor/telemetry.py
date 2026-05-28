"""Telemetry helpers for the recommendation executor workflow.

Wraps OpsWriter.emit() with executor-specific lifecycle logic for session,
phase, step, model call, process event, and transcript records.

Usage pattern (dual-write):
    open_session(workflow="executor", rec_ids=["rec-001"], branch="agent/rec-001")
    open_phase(phase="preflight", phase_order=1)
    # ... phase work ...
    close_phase(outcome="success")
    # ...
    close_session(outcome="success")

No-op contract:
    All emit functions are no-ops when os.environ["PYTEST_CURRENT_TEST"] is set,
    UNLESS os.environ["_TELEMETRY_FORCE_EMIT"] is also set (used by telemetry
    unit tests to bypass the guard while still under pytest).

Error safety:
    Every public function is wrapped in try/except -- telemetry must never
    raise or break the call path.
"""

from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional dependency sentinel -- gracefully degrade if schemas unavailable
# ---------------------------------------------------------------------------

try:
    from scripts.ops_writer import OpsWriter as _OpsWriter
    from scripts.telemetry_schemas import (
        TelemetryModelCalls,
        TelemetryPhases,
        TelemetryProcessEvents,
        TelemetrySessions,
        TelemetrySteps,
        TelemetryTranscripts,
    )

    _SCHEMAS_AVAILABLE = True
except ImportError:
    _OpsWriter = None  # type: ignore[assignment, misc]
    _SCHEMAS_AVAILABLE = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_noop() -> bool:
    """Return True when telemetry should be suppressed.

    Suppressed whenever pytest is running (PYTEST_CURRENT_TEST is set), unless
    _TELEMETRY_FORCE_EMIT is also set (used by unit tests that explicitly test
    the telemetry write path).
    """
    return bool(os.environ.get("PYTEST_CURRENT_TEST")) and not bool(os.environ.get("_TELEMETRY_FORCE_EMIT"))


def _duration_secs(started_at: str | None, ended_at: str) -> int | None:
    """Compute duration in whole seconds between two ISO timestamps."""
    if not started_at:
        return None
    try:
        start = datetime.fromisoformat(started_at)
        end = datetime.fromisoformat(ended_at)
        return max(0, int((end - start).total_seconds()))
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------------


@dataclass
class TelemetryContext:
    """Module-level singleton that carries FK correlation IDs between calls.

    Updated by open_session / open_phase / emit_step so that subsequent
    emit calls can automatically populate session_id, phase_id, step_id
    without requiring callers to thread IDs explicitly.
    """

    # Session-level fields
    session_id: str | None = None
    workflow: str = "executor"
    execution_attempt: int = 1
    model_primary: str | None = None
    parent_session_id: str | None = None
    rec_ids: list | None = None
    rec_id: str | None = None
    branch: str | None = None
    session_started_at: str | None = None

    # Phase-level fields
    phase_id: str | None = None
    phase: str | None = None
    phase_order: int = 0
    phase_attempt_number: int = 1
    phase_model_used: str | None = None
    phase_started_at: str | None = None

    # Step-level field
    step_id: str | None = None

    def reset(self) -> None:
        """Reset all fields to defaults (called by close_session)."""
        self.session_id = None
        self.workflow = "executor"
        self.execution_attempt = 1
        self.model_primary = None
        self.parent_session_id = None
        self.rec_ids = None
        self.rec_id = None
        self.branch = None
        self.session_started_at = None
        self.phase_id = None
        self.phase = None
        self.phase_order = 0
        self.phase_attempt_number = 1
        self.phase_model_used = None
        self.phase_started_at = None
        self.step_id = None


_ctx = TelemetryContext()


def get_context() -> TelemetryContext:
    """Return the module-level singleton TelemetryContext.

    Callers can read session_id, phase_id, step_id etc. without importing
    the private _ctx directly.
    """
    return _ctx


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------


def open_session(
    *,
    workflow: str,
    rec_ids: list[str] | None = None,
    branch: str | None = None,
    model_primary: str | None = None,
    execution_attempt: int = 1,
    parent_session_id: str | None = None,
) -> str:
    """Open a telemetry session -- emit partial record with outcome='running'.

    Returns the new session_id UUID.  On any error returns a UUID (possibly
    already stored in _ctx from a previous partial call).
    """
    try:
        session_id = str(uuid.uuid4())
        started_at = _now_iso()

        _ctx.session_id = session_id
        _ctx.workflow = workflow
        _ctx.execution_attempt = execution_attempt
        _ctx.model_primary = model_primary
        _ctx.parent_session_id = parent_session_id
        _ctx.rec_ids = rec_ids
        _ctx.rec_id = rec_ids[0] if rec_ids and len(rec_ids) == 1 else None
        _ctx.branch = branch
        _ctx.session_started_at = started_at

        if not _is_noop() and _SCHEMAS_AVAILABLE:
            record = TelemetrySessions(
                session_id=session_id,
                workflow=workflow,
                outcome="running",
                started_at=started_at,
                process_event_count=0,
                rework_count=0,
                exception_count=0,
                execution_attempt=execution_attempt,
                branch=branch,
                rec_ids=rec_ids,
                model_primary=model_primary,
                parent_session_id=parent_session_id,
            )
            _OpsWriter().emit(TelemetrySessions.TABLE_NAME, record.to_dict())

        return session_id

    except Exception:
        logger.warning("telemetry.open_session: unexpected error", exc_info=True)
        return _ctx.session_id or str(uuid.uuid4())


def close_session(
    *,
    outcome: str,
    failure_reason: str | None = None,
    failure_phase: str | None = None,
    steps_total: int | None = None,
    steps_completed: int | None = None,
    files_changed: int | None = None,
    lines_added: int | None = None,
    lines_removed: int | None = None,
    scope_drift_files: list[str] | None = None,
    pr_url: str | None = None,
    ci_outcome: str | None = None,
    process_event_count: int = 0,
    rework_count: int = 0,
    exception_count: int = 0,
) -> None:
    """Close a telemetry session -- emit complete record with ended_at.

    Always resets _ctx (via finally) even if the emit fails.
    """
    try:
        session_id = _ctx.session_id
        started_at = _ctx.session_started_at
        ended_at = _now_iso()

        if not _is_noop() and _SCHEMAS_AVAILABLE and session_id:
            record = TelemetrySessions(
                session_id=session_id,
                workflow=_ctx.workflow,
                outcome=outcome,
                started_at=started_at or ended_at,
                ended_at=ended_at,
                duration_seconds=_duration_secs(started_at, ended_at),
                process_event_count=process_event_count,
                rework_count=rework_count,
                exception_count=exception_count,
                execution_attempt=_ctx.execution_attempt,
                branch=_ctx.branch,
                rec_ids=_ctx.rec_ids,
                model_primary=_ctx.model_primary,
                parent_session_id=_ctx.parent_session_id,
                failure_reason=failure_reason,
                failure_phase=failure_phase,
                steps_total=steps_total,
                steps_completed=steps_completed,
                files_changed=files_changed,
                lines_added=lines_added,
                lines_removed=lines_removed,
                scope_drift_files=scope_drift_files,
                pr_url=pr_url,
                ci_outcome=ci_outcome,
            )
            _OpsWriter().emit(TelemetrySessions.TABLE_NAME, record.to_dict())

    except Exception:
        logger.warning("telemetry.close_session: unexpected error", exc_info=True)
    finally:
        _ctx.reset()


# ---------------------------------------------------------------------------
# Phase lifecycle
# ---------------------------------------------------------------------------


def open_phase(
    *,
    phase: str,
    phase_order: int,
    attempt_number: int = 1,
    max_attempts: int | None = None,
    model_used: str | None = None,
) -> str:
    """Open a telemetry phase -- emit partial record with outcome='running'.

    Returns the new phase_id UUID.
    """
    try:
        phase_id = str(uuid.uuid4())
        started_at = _now_iso()

        _ctx.phase_id = phase_id
        _ctx.phase = phase
        _ctx.phase_order = phase_order
        _ctx.phase_attempt_number = attempt_number
        _ctx.phase_model_used = model_used
        _ctx.phase_started_at = started_at

        if not _is_noop() and _SCHEMAS_AVAILABLE and _ctx.session_id:
            record = TelemetryPhases(
                phase_id=phase_id,
                session_id=_ctx.session_id,
                phase=phase,
                phase_order=phase_order,
                started_at=started_at,
                outcome="running",
                attempt_number=attempt_number,
                max_attempts=max_attempts,
                model_used=model_used,
            )
            _OpsWriter().emit(TelemetryPhases.TABLE_NAME, record.to_dict())

        return phase_id

    except Exception:
        logger.warning("telemetry.open_phase: unexpected error", exc_info=True)
        return _ctx.phase_id or str(uuid.uuid4())


def close_phase(
    *,
    outcome: str,
    tokens_input: int | None = None,
    tokens_output: int | None = None,
    revision_count: int | None = None,
    blocking_findings_count: int | None = None,
    plan_steps_json: str | None = None,
    metadata_json: str | None = None,
) -> None:
    """Close the current telemetry phase -- emit complete record with ended_at.

    Logs a warning if called when no phase is open. Always clears
    phase-level fields from _ctx (via finally).
    """
    try:
        phase_id = _ctx.phase_id
        session_id = _ctx.session_id
        phase = _ctx.phase
        phase_order = _ctx.phase_order
        started_at = _ctx.phase_started_at

        if phase_id is None:
            logger.warning("telemetry.close_phase: no open phase to close (outcome=%r)", outcome)
            return

        ended_at = _now_iso()

        if not _is_noop() and _SCHEMAS_AVAILABLE and session_id:
            record = TelemetryPhases(
                phase_id=phase_id,
                session_id=session_id,
                phase=phase or "unknown",
                phase_order=phase_order,
                started_at=started_at or ended_at,
                ended_at=ended_at,
                duration_seconds=_duration_secs(started_at, ended_at),
                outcome=outcome,
                attempt_number=_ctx.phase_attempt_number,
                model_used=_ctx.phase_model_used,
                tokens_input=tokens_input,
                tokens_output=tokens_output,
                revision_count=revision_count,
                blocking_findings_count=blocking_findings_count,
                plan_steps_json=plan_steps_json,
                metadata_json=metadata_json,
            )
            _OpsWriter().emit(TelemetryPhases.TABLE_NAME, record.to_dict())

    except Exception:
        logger.warning("telemetry.close_phase: unexpected error", exc_info=True)
    finally:
        _ctx.phase_id = None
        _ctx.phase = None
        _ctx.phase_started_at = None


# ---------------------------------------------------------------------------
# Single-write emitters
# ---------------------------------------------------------------------------


def emit_step(
    *,
    step_number: int,
    total_steps: int,
    title: str,
    outcome: str,
    retry_count: int = 0,
    target_file: str | None = None,
    action: str | None = None,
    started_at: str,
    ended_at: str | None = None,
    model_used: str | None = None,
    tokens_input: int | None = None,
    tokens_output: int | None = None,
    acceptance_command: str | None = None,
    acceptance_passed: bool | None = None,
    diff_stat: str | None = None,
    lines_added: int | None = None,
    lines_removed: int | None = None,
    prompt_hash: str | None = None,
    transcript_path: str | None = None,
) -> str:
    """Emit a single step telemetry record.  Returns the generated step_id."""
    try:
        step_id = str(uuid.uuid4())
        _ctx.step_id = step_id

        if not _is_noop() and _SCHEMAS_AVAILABLE and _ctx.session_id and _ctx.phase_id:
            record = TelemetrySteps(
                step_id=step_id,
                session_id=_ctx.session_id,
                phase_id=_ctx.phase_id,
                step_number=step_number,
                total_steps=total_steps,
                title=title,
                started_at=started_at,
                ended_at=ended_at,
                duration_seconds=(_duration_secs(started_at, ended_at) if ended_at else None),
                outcome=outcome,
                retry_count=retry_count,
                target_file=target_file,
                action=action,
                model_used=model_used,
                tokens_input=tokens_input,
                tokens_output=tokens_output,
                acceptance_command=acceptance_command,
                acceptance_passed=acceptance_passed,
                diff_stat=diff_stat,
                lines_added=lines_added,
                lines_removed=lines_removed,
                prompt_hash=prompt_hash,
                transcript_path=transcript_path,
            )
            _OpsWriter().emit(TelemetrySteps.TABLE_NAME, record.to_dict())

        return step_id

    except Exception:
        logger.warning("telemetry.emit_step: unexpected error", exc_info=True)
        return str(uuid.uuid4())


def emit_model_call(
    *,
    provider: str,
    model: str,
    purpose: str,
    timestamp: str | None = None,
    duration_seconds: int | None = None,
    tokens_input: int | None = None,
    tokens_output: int | None = None,
    exit_code: int | None = None,
    copilot_session_id: str | None = None,
    prompt_hash: str | None = None,
    error: str | None = None,
    step_id: str | None = None,
    invocation_id: str | None = None,
) -> str:
    """Emit a single model call telemetry record.  Returns the generated call_id."""
    try:
        call_id = str(uuid.uuid4())
        _ts = timestamp or _now_iso()

        if not _is_noop() and _SCHEMAS_AVAILABLE and _ctx.session_id:
            record = TelemetryModelCalls(
                call_id=call_id,
                timestamp=_ts,
                provider=provider,
                model=model,
                purpose=purpose,
                session_id=_ctx.session_id,
                phase_id=_ctx.phase_id,
                step_id=step_id or _ctx.step_id,
                invocation_id=invocation_id,
                duration_seconds=duration_seconds,
                tokens_input=tokens_input,
                tokens_output=tokens_output,
                exit_code=exit_code,
                copilot_session_id=copilot_session_id,
                prompt_hash=prompt_hash,
                error=error,
            )
            _OpsWriter().emit(TelemetryModelCalls.TABLE_NAME, record.to_dict())

        return call_id

    except Exception:
        logger.warning("telemetry.emit_model_call: unexpected error", exc_info=True)
        return str(uuid.uuid4())


def emit_process_event(
    *,
    tier: str,
    category: str,
    severity: str,
    description: str,
    detected_by: str = "executor_script",
    rec_id: str | None = None,
    root_cause: str | None = None,
    resolution: str | None = None,
    time_lost_seconds: int | None = None,
    rec_filed: str | None = None,
    step_id: str | None = None,
) -> str:
    """Emit a single process event telemetry record.  Returns the generated event_id."""
    try:
        event_id = str(uuid.uuid4())
        timestamp = _now_iso()

        if not _is_noop() and _SCHEMAS_AVAILABLE:
            record = TelemetryProcessEvents(
                event_id=event_id,
                timestamp=timestamp,
                tier=tier,
                category=category,
                severity=severity,
                description=description,
                detected_by=detected_by,
                session_id=_ctx.session_id,
                phase_id=_ctx.phase_id,
                step_id=step_id or _ctx.step_id,
                rec_id=rec_id or _ctx.rec_id,
                root_cause=root_cause,
                resolution=resolution,
                time_lost_seconds=time_lost_seconds,
                rec_filed=rec_filed,
            )
            _OpsWriter().emit(TelemetryProcessEvents.TABLE_NAME, record.to_dict())

        return event_id

    except Exception:
        logger.warning("telemetry.emit_process_event: unexpected error", exc_info=True)
        return str(uuid.uuid4())


def emit_transcript(
    *,
    purpose: str,
    local_path: str,
    size_bytes: int,
    model_used: str | None = None,
    rec_id: str | None = None,
    token_count: int | None = None,
    s3_key: str | None = None,
    step_id: str | None = None,
) -> str:
    """Emit a single transcript index telemetry record.  Returns the transcript_id."""
    try:
        transcript_id = str(uuid.uuid4())
        timestamp = _now_iso()

        if not _is_noop() and _SCHEMAS_AVAILABLE:
            record = TelemetryTranscripts(
                transcript_id=transcript_id,
                timestamp=timestamp,
                purpose=purpose,
                local_path=local_path,
                size_bytes=size_bytes,
                session_id=_ctx.session_id,
                phase_id=_ctx.phase_id,
                step_id=step_id or _ctx.step_id,
                model_used=model_used,
                rec_id=rec_id or _ctx.rec_id,
                token_count=token_count,
                s3_key=s3_key,
            )
            _OpsWriter().emit(TelemetryTranscripts.TABLE_NAME, record.to_dict())

        return transcript_id

    except Exception:
        logger.warning("telemetry.emit_transcript: unexpected error", exc_info=True)
        return str(uuid.uuid4())
