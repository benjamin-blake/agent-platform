"""telemetry_schemas -- Schema definitions for the 7 telemetry Iceberg tables.

Each dataclass corresponds to one Iceberg table in trading_formulas_db (telemetry_ prefix).
Required fields have no default; optional fields default to None.  ingested_at and
trade_date are auto-populated by the dataclass default_factory so they are never None
when a fresh record is created in-process.

See docs/INTENT-telemetry-system.md for the authoritative schema spec.
See docs/contracts/storage-substrate.yaml (telemetry_tables section) for the substrate index.
"""

from __future__ import annotations

import dataclasses
import datetime
import logging
from dataclasses import dataclass, field
from typing import ClassVar

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _today_iso() -> str:
    return datetime.date.today().isoformat()


# ---------------------------------------------------------------------------
# Table 1: telemetry_sessions
# ---------------------------------------------------------------------------


@dataclass
class TelemetrySessions:
    """One row per workflow invocation."""

    TABLE_NAME: ClassVar[str] = "telemetry_sessions"
    REQUIRED_FIELDS: ClassVar[set[str]] = {
        "session_id",
        "workflow",
        "outcome",
        "started_at",
        "process_event_count",
        "rework_count",
        "exception_count",
        "execution_attempt",
    }

    # --- Required (no default) ---
    session_id: str
    workflow: str
    outcome: str
    started_at: str
    process_event_count: int
    rework_count: int
    exception_count: int
    execution_attempt: int

    # --- Optional ---
    branch: str | None = None
    rec_ids: list[str] | None = None
    plan_slug: str | None = None
    ended_at: str | None = None
    duration_seconds: int | None = None
    failure_reason: str | None = None
    failure_phase: str | None = None
    files_changed: int | None = None
    lines_added: int | None = None
    lines_removed: int | None = None
    steps_total: int | None = None
    steps_completed: int | None = None
    scope_drift_files: list[str] | None = None
    pr_url: str | None = None
    ci_outcome: str | None = None
    model_primary: str | None = None
    parent_session_id: str | None = None
    coverage_before: float | None = None
    coverage_after: float | None = None
    ingested_at: str = field(default_factory=_now_iso)
    trade_date: str = field(default_factory=_today_iso)

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


# ---------------------------------------------------------------------------
# Table 2: telemetry_phases
# ---------------------------------------------------------------------------


@dataclass
class TelemetryPhases:
    """One row per phase within a session."""

    TABLE_NAME: ClassVar[str] = "telemetry_phases"
    REQUIRED_FIELDS: ClassVar[set[str]] = {
        "phase_id",
        "session_id",
        "phase",
        "phase_order",
        "started_at",
        "outcome",
        "attempt_number",
    }

    # --- Required ---
    phase_id: str
    session_id: str
    phase: str
    phase_order: int
    started_at: str
    outcome: str
    attempt_number: int

    # --- Optional ---
    ended_at: str | None = None
    duration_seconds: int | None = None
    max_attempts: int | None = None
    model_used: str | None = None
    tokens_input: int | None = None
    tokens_output: int | None = None
    revision_count: int | None = None
    blocking_findings_count: int | None = None
    plan_steps_json: str | None = None
    metadata_json: str | None = None
    ingested_at: str = field(default_factory=_now_iso)
    trade_date: str = field(default_factory=_today_iso)

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


# ---------------------------------------------------------------------------
# Table 3: telemetry_steps
# ---------------------------------------------------------------------------


@dataclass
class TelemetrySteps:
    """One row per implementation step within a plan."""

    TABLE_NAME: ClassVar[str] = "telemetry_steps"
    REQUIRED_FIELDS: ClassVar[set[str]] = {
        "step_id",
        "session_id",
        "phase_id",
        "step_number",
        "total_steps",
        "title",
        "started_at",
        "outcome",
        "retry_count",
    }

    # --- Required ---
    step_id: str
    session_id: str
    phase_id: str
    step_number: int
    total_steps: int
    title: str
    started_at: str
    outcome: str
    retry_count: int

    # --- Optional ---
    target_file: str | None = None
    action: str | None = None
    ended_at: str | None = None
    duration_seconds: int | None = None
    model_used: str | None = None
    tokens_input: int | None = None
    tokens_output: int | None = None
    acceptance_command: str | None = None
    acceptance_passed: bool | None = None
    acceptance_duration_seconds: int | None = None
    diff_stat: str | None = None
    lines_added: int | None = None
    lines_removed: int | None = None
    model_escalated_from: str | None = None
    prompt_hash: str | None = None
    transcript_path: str | None = None
    ingested_at: str = field(default_factory=_now_iso)
    trade_date: str = field(default_factory=_today_iso)

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


# ---------------------------------------------------------------------------
# Table 4: telemetry_process_events
# ---------------------------------------------------------------------------


@dataclass
class TelemetryProcessEvents:
    """One row per notable event during execution."""

    TABLE_NAME: ClassVar[str] = "telemetry_process_events"
    REQUIRED_FIELDS: ClassVar[set[str]] = {
        "event_id",
        "timestamp",
        "tier",
        "category",
        "severity",
        "description",
        "detected_by",
    }

    # --- Required ---
    event_id: str
    timestamp: str
    tier: str
    category: str
    severity: str
    description: str
    detected_by: str

    # --- Optional ---
    session_id: str | None = None
    phase_id: str | None = None
    step_id: str | None = None
    rec_id: str | None = None
    root_cause: str | None = None
    resolution: str | None = None
    time_lost_seconds: int | None = None
    rec_filed: str | None = None
    ingested_at: str = field(default_factory=_now_iso)
    trade_date: str = field(default_factory=_today_iso)

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


# ---------------------------------------------------------------------------
# Table 5: telemetry_model_calls
# ---------------------------------------------------------------------------


@dataclass
class TelemetryModelCalls:
    """One row per LLM invocation."""

    TABLE_NAME: ClassVar[str] = "telemetry_model_calls"
    REQUIRED_FIELDS: ClassVar[set[str]] = {
        "call_id",
        "timestamp",
        "provider",
        "model",
        "purpose",
    }

    # --- Required ---
    call_id: str
    timestamp: str
    provider: str
    model: str
    purpose: str

    # --- Optional ---
    session_id: str | None = None
    phase_id: str | None = None
    step_id: str | None = None
    invocation_id: str | None = None
    duration_seconds: int | None = None
    tokens_input: int | None = None
    tokens_output: int | None = None
    exit_code: int | None = None
    copilot_session_id: str | None = None
    prompt_hash: str | None = None
    error: str | None = None
    ingested_at: str = field(default_factory=_now_iso)
    trade_date: str = field(default_factory=_today_iso)

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


# ---------------------------------------------------------------------------
# Table 6: telemetry_transcripts
# ---------------------------------------------------------------------------


@dataclass
class TelemetryTranscripts:
    """One row per transcript file (metadata index, not content)."""

    TABLE_NAME: ClassVar[str] = "telemetry_transcripts"
    REQUIRED_FIELDS: ClassVar[set[str]] = {
        "transcript_id",
        "timestamp",
        "purpose",
        "local_path",
        "size_bytes",
    }

    # --- Required ---
    transcript_id: str
    timestamp: str
    purpose: str
    local_path: str
    size_bytes: int

    # --- Optional ---
    session_id: str | None = None
    phase_id: str | None = None
    step_id: str | None = None
    invocation_id: str | None = None
    s3_key: str | None = None
    token_count: int | None = None
    model_used: str | None = None
    rec_id: str | None = None
    ingested_at: str = field(default_factory=_now_iso)
    trade_date: str = field(default_factory=_today_iso)

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


# ---------------------------------------------------------------------------
# Table 7: telemetry_agent_invocations
# ---------------------------------------------------------------------------


@dataclass
class TelemetryAgentInvocations:
    """One row per scheduled agent Lambda invocation (standalone, no FK to sessions)."""

    TABLE_NAME: ClassVar[str] = "telemetry_agent_invocations"
    REQUIRED_FIELDS: ClassVar[set[str]] = {
        "invocation_id",
        "agent_name",
        "trigger",
        "started_at",
        "outcome",
    }

    # --- Required ---
    invocation_id: str
    agent_name: str
    trigger: str
    started_at: str
    outcome: str

    # --- Optional ---
    ended_at: str | None = None
    duration_seconds: int | None = None
    model_used: str | None = None
    provider: str | None = None
    tokens_input: int | None = None
    tokens_output: int | None = None
    findings_count: int | None = None
    recs_created: int | None = None
    queue_entries_written: int | None = None
    error: str | None = None
    lambda_request_id: str | None = None
    workflow_run_id: str | None = None
    ingested_at: str = field(default_factory=_now_iso)
    trade_date: str = field(default_factory=_today_iso)

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


# ---------------------------------------------------------------------------
# Module-level metadata
# ---------------------------------------------------------------------------

TELEMETRY_TABLE_NAMES: list[str] = [
    "telemetry_sessions",
    "telemetry_phases",
    "telemetry_steps",
    "telemetry_process_events",
    "telemetry_model_calls",
    "telemetry_transcripts",
    "telemetry_agent_invocations",
]

# Explicit Athena dtype overrides for awswrangler compaction.
# array<> columns must be declared explicitly to prevent null-inference failures
# when a batch has all-null values for those columns (gotcha documented in
# copilot-instructions.md: awswrangler fill_missing_columns_in_df=True behaviour).
# All integer columns are declared as "bigint" to avoid Iceberg integer-promotion
# errors on schema evolution (gotcha: Iceberg integer promotion).
TELEMETRY_TABLE_DTYPES: dict[str, dict[str, str]] = {
    "telemetry_sessions": {
        "rec_ids": "array<string>",
        "scope_drift_files": "array<string>",
        "duration_seconds": "bigint",
        "files_changed": "bigint",
        "lines_added": "bigint",
        "lines_removed": "bigint",
        "steps_total": "bigint",
        "steps_completed": "bigint",
        "process_event_count": "bigint",
        "rework_count": "bigint",
        "exception_count": "bigint",
        "execution_attempt": "bigint",
    },
    "telemetry_phases": {
        "phase_order": "bigint",
        "duration_seconds": "bigint",
        "attempt_number": "bigint",
        "max_attempts": "bigint",
        "tokens_input": "bigint",
        "tokens_output": "bigint",
        "revision_count": "bigint",
        "blocking_findings_count": "bigint",
    },
    "telemetry_steps": {
        "step_number": "bigint",
        "total_steps": "bigint",
        "duration_seconds": "bigint",
        "tokens_input": "bigint",
        "tokens_output": "bigint",
        "acceptance_duration_seconds": "bigint",
        "lines_added": "bigint",
        "lines_removed": "bigint",
        "retry_count": "bigint",
    },
    "telemetry_process_events": {
        "time_lost_seconds": "bigint",
    },
    "telemetry_model_calls": {
        "duration_seconds": "bigint",
        "tokens_input": "bigint",
        "tokens_output": "bigint",
        "exit_code": "bigint",
    },
    "telemetry_transcripts": {
        "size_bytes": "bigint",
        "token_count": "bigint",
    },
    "telemetry_agent_invocations": {
        "duration_seconds": "bigint",
        "tokens_input": "bigint",
        "tokens_output": "bigint",
        "findings_count": "bigint",
        "recs_created": "bigint",
        "queue_entries_written": "bigint",
    },
}

# Timestamp columns per table that may be absent from a partial write.
# compact() pre-fills these with pd.NaT (datetime64[ns]) before calling
# wr.athena.to_iceberg so that awswrangler's fill_missing_columns_in_df code
# path never tries to cast None to bare 'datetime64' -- which pandas 2.x
# rejects with "Passing in 'datetime64' dtype with no precision is not allowed".
# (ingested_at is excluded: write() always injects it, so it is always present.)
TELEMETRY_TABLE_TIMESTAMP_COLS: dict[str, list[str]] = {
    "telemetry_sessions": ["started_at", "ended_at"],
    "telemetry_phases": ["started_at", "ended_at"],
    "telemetry_steps": ["started_at", "ended_at"],
    "telemetry_process_events": ["timestamp"],
    "telemetry_model_calls": ["timestamp"],
    "telemetry_transcripts": ["timestamp"],
    "telemetry_agent_invocations": ["started_at", "ended_at"],
}

# Mapping from table name to the set of valid field names for that table.
# Built once at import time from the dataclass field lists.
_SCHEMA_CLASSES: dict[str, type] = {
    "telemetry_sessions": TelemetrySessions,
    "telemetry_phases": TelemetryPhases,
    "telemetry_steps": TelemetrySteps,
    "telemetry_process_events": TelemetryProcessEvents,
    "telemetry_model_calls": TelemetryModelCalls,
    "telemetry_transcripts": TelemetryTranscripts,
    "telemetry_agent_invocations": TelemetryAgentInvocations,
}

_SCHEMA_FIELDS: dict[str, set[str]] = {
    table: {f.name for f in dataclasses.fields(cls)} for table, cls in _SCHEMA_CLASSES.items()
}


def validate_record(table_name: str, record: dict) -> dict:
    """Validate and clean a record dict against the schema for *table_name*.

    - Unknown fields are dropped with a logged warning.
    - Missing required fields are logged as a warning but the record is NOT
      rejected (forward-compatibility: new code writing to old schema).
    - Returns the cleaned record (a new dict, not mutated in-place).
    - Returns an empty dict for unrecognised table names (with a warning).
    """
    valid_fields = _SCHEMA_FIELDS.get(table_name)
    if valid_fields is None:
        logger.warning(
            "telemetry_schemas.validate_record: unknown table %r -- returning empty dict",
            table_name,
        )
        return {}

    schema_cls = _SCHEMA_CLASSES[table_name]
    required = getattr(schema_cls, "REQUIRED_FIELDS", set())

    cleaned: dict = {}
    unknown: list[str] = []

    for key, value in record.items():
        if key in valid_fields:
            cleaned[key] = value
        else:
            unknown.append(key)

    if unknown:
        logger.warning(
            "telemetry_schemas.validate_record: dropping unknown fields from %s: %s",
            table_name,
            unknown,
        )

    missing = required - set(cleaned.keys())
    if missing:
        logger.warning(
            "telemetry_schemas.validate_record: required fields missing from %s record: %s"
            " -- proceeding with nulls (forward-compatibility)",
            table_name,
            sorted(missing),
        )

    return cleaned


def get_all_columns(table_name: str) -> list[str]:
    """Return ordered list of all column names for a telemetry table.

    Returns empty list with a warning for unknown table names.
    """
    cls = _SCHEMA_CLASSES.get(table_name)
    if cls is None:
        logger.warning("telemetry_schemas.get_all_columns: unknown table %r", table_name)
        return []
    return [f.name for f in dataclasses.fields(cls)]


def get_required_columns(table_name: str) -> list[str]:
    """Return list of required (non-nullable) column names for a telemetry table.

    Returns empty list with a warning for unknown table names.
    """
    cls = _SCHEMA_CLASSES.get(table_name)
    if cls is None:
        logger.warning("telemetry_schemas.get_required_columns: unknown table %r", table_name)
        return []
    required = getattr(cls, "REQUIRED_FIELDS", set())
    return [f.name for f in dataclasses.fields(cls) if f.name in required]
