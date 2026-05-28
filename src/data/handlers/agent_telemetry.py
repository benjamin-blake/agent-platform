"""Telemetry helpers for scheduled agent Lambda handlers and local runner.

Wraps OpsWriter.emit() with scheduled-agent lifecycle logic for invocation
and model call records.

Usage pattern::

    invocation_id = open_invocation(
        agent_name="doc-freshness", trigger="eventbridge",
        model="gemini-2.5-flash", provider="gemini",
    )
    # ... agent work ...
    record_model_call(
        provider="gemini", model="gemini-2.5-flash",
        purpose="findings",
        duration_seconds=12,
    )
    close_invocation(outcome="success", findings_count=3)

No-op contract:
    All emit functions are no-ops when os.environ["PYTEST_CURRENT_TEST"] is set,
    UNLESS os.environ["_TELEMETRY_FORCE_EMIT"] is also set (used by telemetry
    unit tests to bypass the guard while still under pytest).

Error safety:
    Every public function is wrapped in try/except -- telemetry must never
    raise or break the call path.

Lambda vs local:
    OpsWriter internally detects AWS_LAMBDA_FUNCTION_NAME and writes directly
    to S3 staging inside Lambda, or to the local outbox when running locally.
    This module does not need to distinguish the two environments.
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
    from scripts.telemetry_schemas import TelemetryAgentInvocations, TelemetryModelCalls

    _SCHEMAS_AVAILABLE = True
except ImportError:
    _OpsWriter = None  # type: ignore[assignment, misc]
    TelemetryAgentInvocations = None  # type: ignore[assignment, misc]
    TelemetryModelCalls = None  # type: ignore[assignment, misc]
    _SCHEMAS_AVAILABLE = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_noop() -> bool:
    """Return True when telemetry should be suppressed."""
    return bool(os.environ.get("PYTEST_CURRENT_TEST")) and not bool(os.environ.get("_TELEMETRY_FORCE_EMIT"))


def _duration_secs(started_at: str | None, ended_at: str) -> int | None:
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
class _InvocationContext:
    """Module-level singleton that carries the active invocation state."""

    invocation_id: str | None = None
    agent_name: str | None = None
    model: str | None = None
    provider: str | None = None
    started_at: str | None = None


_ctx = _InvocationContext()


def _reset_context() -> None:
    _ctx.invocation_id = None
    _ctx.agent_name = None
    _ctx.model = None
    _ctx.provider = None
    _ctx.started_at = None


# ---------------------------------------------------------------------------
# Provider normalisation
# ---------------------------------------------------------------------------


def _normalise_provider(provider: str) -> str:
    """Normalise provider string: replace hyphens with underscores."""
    return provider.replace("-", "_")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def open_invocation(
    agent_name: str,
    trigger: str,
    model: str,
    provider: str,
) -> str:
    """Open a new agent invocation and emit a partial 'running' record.

    Stores the invocation context module-level so subsequent calls to
    ``record_model_call`` and ``close_invocation`` can pick up the FK.

    Args:
        agent_name: Logical agent name (matches schedule.yaml ``name`` field).
        trigger: One of ``"eventbridge"``, ``"manual"``, ``"s3_event"``.
        model: Model identifier string (e.g. ``"gemini-2.5-flash"``).
        provider: Raw provider string; normalised internally.

    Returns:
        The new ``invocation_id`` UUID string.
    """
    try:
        if _is_noop():
            return ""
        if not _SCHEMAS_AVAILABLE or _OpsWriter is None:
            return ""

        invocation_id = str(uuid.uuid4())
        started_at = _now_iso()
        normalised_provider = _normalise_provider(provider)

        _ctx.invocation_id = invocation_id
        _ctx.agent_name = agent_name
        _ctx.model = model
        _ctx.provider = normalised_provider
        _ctx.started_at = started_at

        record = TelemetryAgentInvocations(
            invocation_id=invocation_id,
            agent_name=agent_name,
            trigger=trigger,
            started_at=started_at,
            outcome="running",
            model_used=model,
            provider=normalised_provider,
        )
        _OpsWriter().emit("telemetry_agent_invocations", record.to_dict())
        return invocation_id
    except Exception:  # noqa: BLE001
        logger.exception("agent_telemetry.open_invocation failed (suppressed)")
        return ""


def close_invocation(
    outcome: str,
    findings_count: int = 0,
    recs_created: int = 0,
    queue_entries_written: int = 0,
    error: str | None = None,
    lambda_request_id: str | None = None,
) -> None:
    """Close the active invocation and emit a final record.

    Args:
        outcome: One of ``"success"``, ``"failed"``, ``"timeout"``,
            ``"throttled"``.
        findings_count: Number of findings produced by the agent.
        recs_created: Number of recommendations appended.
        queue_entries_written: Number of priority queue entries written.
        error: Short error message if outcome is not ``"success"``.
        lambda_request_id: AWS Lambda request ID from the context object.
    """
    try:
        if _is_noop():
            _reset_context()
            return
        if not _SCHEMAS_AVAILABLE or _OpsWriter is None:
            _reset_context()
            return

        ended_at = _now_iso()
        record = TelemetryAgentInvocations(
            invocation_id=_ctx.invocation_id or str(uuid.uuid4()),
            agent_name=_ctx.agent_name or "unknown",
            trigger="unknown",
            started_at=_ctx.started_at or ended_at,
            outcome=outcome,
            ended_at=ended_at,
            duration_seconds=_duration_secs(_ctx.started_at, ended_at),
            model_used=_ctx.model,
            provider=_ctx.provider,
            findings_count=findings_count,
            recs_created=recs_created,
            queue_entries_written=queue_entries_written,
            error=error,
            lambda_request_id=lambda_request_id,
        )
        _OpsWriter().emit("telemetry_agent_invocations", record.to_dict())
    except Exception:  # noqa: BLE001
        logger.exception("agent_telemetry.close_invocation failed (suppressed)")
    finally:
        _reset_context()


def record_model_call(
    provider: str,
    model: str,
    purpose: str,
    error: str | None = None,
    duration_seconds: int | None = None,
    tokens_input: int | None = None,
    tokens_output: int | None = None,
) -> None:
    """Emit a telemetry_model_calls record for a single LLM invocation.

    Must be called after ``open_invocation()`` or the ``invocation_id`` FK
    will be ``None`` (not an error -- standalone calls are permitted).

    Args:
        provider: Raw provider string; normalised internally.
        model: Model identifier.
        purpose: Free-text label (e.g. ``"findings"``, ``"comparison"``).
        duration_seconds: Wall-clock duration of the call.
        tokens_input: Input token count (may be None for SDK calls).
        tokens_output: Output token count (may be None for SDK calls).
    """
    try:
        if _is_noop():
            return
        if not _SCHEMAS_AVAILABLE or _OpsWriter is None:
            return

        normalised_provider = _normalise_provider(provider)
        record = TelemetryModelCalls(
            call_id=str(uuid.uuid4()),
            timestamp=_now_iso(),
            provider=normalised_provider,
            model=model,
            purpose=purpose,
            invocation_id=_ctx.invocation_id,
            duration_seconds=duration_seconds,
            tokens_input=tokens_input,
            tokens_output=tokens_output,
            error=error,
        )
        _OpsWriter().emit("telemetry_model_calls", record.to_dict())
    except Exception:  # noqa: BLE001
        logger.exception("agent_telemetry.record_model_call failed (suppressed)")
