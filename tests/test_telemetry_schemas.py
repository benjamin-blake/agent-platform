"""Tests for scripts/telemetry_schemas.py -- 100% coverage."""

from __future__ import annotations

import logging

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _import_all():
    from scripts.telemetry_schemas import (  # noqa: PLC0415
        TELEMETRY_TABLE_DTYPES,
        TELEMETRY_TABLE_NAMES,
        TelemetryAgentInvocations,
        TelemetryModelCalls,
        TelemetryPhases,
        TelemetryProcessEvents,
        TelemetrySessions,
        TelemetrySteps,
        TelemetryTranscripts,
        validate_record,
    )

    return (
        TELEMETRY_TABLE_DTYPES,
        TELEMETRY_TABLE_NAMES,
        TelemetryAgentInvocations,
        TelemetryModelCalls,
        TelemetryPhases,
        TelemetryProcessEvents,
        TelemetrySessions,
        TelemetrySteps,
        TelemetryTranscripts,
        validate_record,
    )


def _make_sessions(**overrides):
    defaults = {
        "session_id": "sess-001",
        "workflow": "executor",
        "outcome": "success",
        "started_at": "2026-04-24T10:00:00+00:00",
        "process_event_count": 2,
        "rework_count": 0,
        "exception_count": 0,
        "execution_attempt": 1,
    }
    defaults.update(overrides)
    from scripts.telemetry_schemas import TelemetrySessions  # noqa: PLC0415

    return TelemetrySessions(**defaults)


def _make_phases(**overrides):
    defaults = {
        "phase_id": "phase-001",
        "session_id": "sess-001",
        "phase": "implementation",
        "phase_order": 1,
        "started_at": "2026-04-24T10:00:00+00:00",
        "outcome": "success",
        "attempt_number": 1,
    }
    defaults.update(overrides)
    from scripts.telemetry_schemas import TelemetryPhases  # noqa: PLC0415

    return TelemetryPhases(**defaults)


def _make_steps(**overrides):
    defaults = {
        "step_id": "step-001",
        "session_id": "sess-001",
        "phase_id": "phase-001",
        "step_number": 1,
        "total_steps": 5,
        "title": "Create file",
        "started_at": "2026-04-24T10:00:00+00:00",
        "outcome": "success",
        "retry_count": 0,
    }
    defaults.update(overrides)
    from scripts.telemetry_schemas import TelemetrySteps  # noqa: PLC0415

    return TelemetrySteps(**defaults)


def _make_process_events(**overrides):
    defaults = {
        "event_id": "evt-001",
        "timestamp": "2026-04-24T10:00:00+00:00",
        "tier": "rework",
        "category": "step_cli_error",
        "severity": "warning",
        "description": "LLM returned invalid output",
        "detected_by": "executor_script",
    }
    defaults.update(overrides)
    from scripts.telemetry_schemas import TelemetryProcessEvents  # noqa: PLC0415

    return TelemetryProcessEvents(**defaults)


def _make_model_calls(**overrides):
    defaults = {
        "call_id": "call-001",
        "timestamp": "2026-04-24T10:00:00+00:00",
        "provider": "copilot_cli",
        "model": "claude-sonnet-4.6",
        "purpose": "implementation",
    }
    defaults.update(overrides)
    from scripts.telemetry_schemas import TelemetryModelCalls  # noqa: PLC0415

    return TelemetryModelCalls(**defaults)


def _make_transcripts(**overrides):
    defaults = {
        "transcript_id": "trans-001",
        "timestamp": "2026-04-24T10:00:00+00:00",
        "purpose": "implementation",
        "local_path": "logs/transcripts/impl-001.md",
        "size_bytes": 1024,
    }
    defaults.update(overrides)
    from scripts.telemetry_schemas import TelemetryTranscripts  # noqa: PLC0415

    return TelemetryTranscripts(**defaults)


def _make_agent_invocations(**overrides):
    defaults = {
        "invocation_id": "inv-001",
        "agent_name": "doc-freshness",
        "trigger": "eventbridge",
        "started_at": "2026-04-24T10:00:00+00:00",
        "outcome": "success",
    }
    defaults.update(overrides)
    from scripts.telemetry_schemas import TelemetryAgentInvocations  # noqa: PLC0415

    return TelemetryAgentInvocations(**defaults)


# ---------------------------------------------------------------------------
# Test 1: All 7 dataclasses instantiate with only required fields
# ---------------------------------------------------------------------------


class TestDataclassInstantiation:
    """Each dataclass can be created with required fields only; optional fields default to None."""

    def test_telemetry_sessions_required_only(self):
        obj = _make_sessions()
        assert obj.session_id == "sess-001"
        assert obj.branch is None
        assert obj.rec_ids is None
        assert obj.ended_at is None
        assert obj.ingested_at is not None
        assert obj.trade_date is not None

    def test_telemetry_phases_required_only(self):
        obj = _make_phases()
        assert obj.phase_id == "phase-001"
        assert obj.ended_at is None
        assert obj.model_used is None
        assert obj.ingested_at is not None
        assert obj.trade_date is not None

    def test_telemetry_steps_required_only(self):
        obj = _make_steps()
        assert obj.step_id == "step-001"
        assert obj.target_file is None
        assert obj.acceptance_passed is None
        assert obj.ingested_at is not None

    def test_telemetry_process_events_required_only(self):
        obj = _make_process_events()
        assert obj.event_id == "evt-001"
        assert obj.session_id is None
        assert obj.root_cause is None
        assert obj.ingested_at is not None

    def test_telemetry_model_calls_required_only(self):
        obj = _make_model_calls()
        assert obj.call_id == "call-001"
        assert obj.session_id is None
        assert obj.error is None
        assert obj.ingested_at is not None

    def test_telemetry_transcripts_required_only(self):
        obj = _make_transcripts()
        assert obj.transcript_id == "trans-001"
        assert obj.s3_key is None
        assert obj.token_count is None
        assert obj.ingested_at is not None

    def test_telemetry_agent_invocations_required_only(self):
        obj = _make_agent_invocations()
        assert obj.invocation_id == "inv-001"
        assert obj.ended_at is None
        assert obj.error is None
        assert obj.ingested_at is not None

    def test_telemetry_sessions_ingested_at_and_trade_date_auto_populated(self):
        """ingested_at and trade_date have values without being explicitly supplied."""
        obj = _make_sessions()
        assert obj.ingested_at is not None
        assert len(obj.ingested_at) > 0
        assert obj.trade_date is not None
        assert len(obj.trade_date) == 10  # YYYY-MM-DD

    def test_all_table_names_set(self):
        from scripts.telemetry_schemas import (  # noqa: PLC0415
            TelemetryAgentInvocations,
            TelemetryModelCalls,
            TelemetryPhases,
            TelemetryProcessEvents,
            TelemetrySessions,
            TelemetrySteps,
            TelemetryTranscripts,
        )

        assert TelemetrySessions.TABLE_NAME == "telemetry_sessions"
        assert TelemetryPhases.TABLE_NAME == "telemetry_phases"
        assert TelemetrySteps.TABLE_NAME == "telemetry_steps"
        assert TelemetryProcessEvents.TABLE_NAME == "telemetry_process_events"
        assert TelemetryModelCalls.TABLE_NAME == "telemetry_model_calls"
        assert TelemetryTranscripts.TABLE_NAME == "telemetry_transcripts"
        assert TelemetryAgentInvocations.TABLE_NAME == "telemetry_agent_invocations"


# ---------------------------------------------------------------------------
# Test 2: validate_record drops unknown fields with warning
# ---------------------------------------------------------------------------


class TestValidateRecordUnknownFields:
    def test_drops_unknown_fields_and_logs_warning(self, caplog):
        from scripts.telemetry_schemas import validate_record  # noqa: PLC0415

        record = {
            "session_id": "sess-001",
            "workflow": "executor",
            "outcome": "success",
            "started_at": "2026-04-24T10:00:00+00:00",
            "process_event_count": 2,
            "rework_count": 0,
            "exception_count": 0,
            "execution_attempt": 1,
            "bogus_field": 123,
            "another_unknown": "xyz",
        }
        with caplog.at_level(logging.WARNING, logger="scripts.telemetry_schemas"):
            cleaned = validate_record("telemetry_sessions", record)

        assert "bogus_field" not in cleaned
        assert "another_unknown" not in cleaned
        assert cleaned["session_id"] == "sess-001"
        assert any("bogus_field" in msg for msg in caplog.messages)

    def test_passes_valid_record_unchanged(self):
        from scripts.telemetry_schemas import validate_record  # noqa: PLC0415

        record = {
            "session_id": "sess-001",
            "workflow": "executor",
            "outcome": "success",
            "started_at": "2026-04-24T10:00:00+00:00",
            "process_event_count": 2,
            "rework_count": 0,
            "exception_count": 0,
            "execution_attempt": 1,
        }
        cleaned = validate_record("telemetry_sessions", record)
        assert cleaned == record


# ---------------------------------------------------------------------------
# Test 3: validate_record passes missing required fields with warning
# ---------------------------------------------------------------------------


class TestValidateRecordMissingRequiredFields:
    def test_missing_required_fields_logs_warning_returns_record(self, caplog):
        from scripts.telemetry_schemas import validate_record  # noqa: PLC0415

        record = {"session_id": "sess-002", "workflow": "executor"}
        with caplog.at_level(logging.WARNING, logger="scripts.telemetry_schemas"):
            result = validate_record("telemetry_sessions", record)

        # Record is returned -- not rejected
        assert result["session_id"] == "sess-002"
        # Warning logged about missing required fields
        assert any("required fields missing" in msg for msg in caplog.messages)

    def test_empty_record_returns_empty_with_warning(self, caplog):
        from scripts.telemetry_schemas import validate_record  # noqa: PLC0415

        with caplog.at_level(logging.WARNING, logger="scripts.telemetry_schemas"):
            result = validate_record("telemetry_sessions", {})

        assert result == {}
        assert any("required fields missing" in msg for msg in caplog.messages)


# ---------------------------------------------------------------------------
# Test 4: validate_record with fully valid record
# ---------------------------------------------------------------------------


class TestValidateRecordFullyValid:
    def test_full_valid_record_passes_unchanged(self):
        from scripts.telemetry_schemas import validate_record  # noqa: PLC0415

        record = {
            "session_id": "sess-003",
            "workflow": "executor",
            "outcome": "success",
            "started_at": "2026-04-24T10:00:00+00:00",
            "process_event_count": 5,
            "rework_count": 1,
            "exception_count": 0,
            "execution_attempt": 1,
            "branch": "agent/test-branch",
            "rec_ids": ["rec-001", "rec-002"],
            "plan_slug": "test-plan",
        }
        cleaned = validate_record("telemetry_sessions", record)
        assert cleaned["branch"] == "agent/test-branch"
        assert cleaned["rec_ids"] == ["rec-001", "rec-002"]
        assert len(cleaned) == len(record)  # nothing dropped


# ---------------------------------------------------------------------------
# Test 5: TELEMETRY_TABLE_DTYPES has entries for all 7 tables
# ---------------------------------------------------------------------------


class TestTelemetryTableDtypes:
    def test_dtypes_has_all_7_tables(self):
        from scripts.telemetry_schemas import TELEMETRY_TABLE_DTYPES, TELEMETRY_TABLE_NAMES  # noqa: PLC0415

        for table in TELEMETRY_TABLE_NAMES:
            assert table in TELEMETRY_TABLE_DTYPES, f"Missing dtype entry for {table}"

    def test_array_columns_have_explicit_dtypes(self):
        """Every array<> column in every table must have an explicit dtype override."""
        from scripts.telemetry_schemas import TELEMETRY_TABLE_DTYPES  # noqa: PLC0415

        # telemetry_sessions has rec_ids and scope_drift_files (list[str] fields)
        sessions_dtypes = TELEMETRY_TABLE_DTYPES["telemetry_sessions"]
        assert sessions_dtypes.get("rec_ids") == "array<string>"
        assert sessions_dtypes.get("scope_drift_files") == "array<string>"

    def test_array_dtype_values_are_array_types(self):
        """All dtype overrides declared as array<> must use the Athena array<> syntax."""
        from scripts.telemetry_schemas import TELEMETRY_TABLE_DTYPES  # noqa: PLC0415

        for table, dtypes in TELEMETRY_TABLE_DTYPES.items():
            for col, dtype in dtypes.items():
                if dtype.startswith("array"):
                    assert ">" in dtype, f"{table}.{col} dtype looks malformed: {dtype}"

    def test_integer_columns_use_bigint(self):
        """Integer columns use bigint to avoid Iceberg promotion issues."""
        from scripts.telemetry_schemas import TELEMETRY_TABLE_DTYPES  # noqa: PLC0415

        # Spot-check a few
        assert TELEMETRY_TABLE_DTYPES["telemetry_sessions"]["execution_attempt"] == "bigint"
        assert TELEMETRY_TABLE_DTYPES["telemetry_steps"]["retry_count"] == "bigint"
        assert TELEMETRY_TABLE_DTYPES["telemetry_agent_invocations"]["findings_count"] == "bigint"


# ---------------------------------------------------------------------------
# Test 6: to_dict() method
# ---------------------------------------------------------------------------


class TestToDict:
    def test_sessions_to_dict_returns_dict(self):
        obj = _make_sessions()
        d = obj.to_dict()
        assert isinstance(d, dict)
        assert d["session_id"] == "sess-001"
        assert d["branch"] is None  # optional field

    def test_phases_to_dict(self):
        obj = _make_phases()
        d = obj.to_dict()
        assert d["phase"] == "implementation"

    def test_steps_to_dict(self):
        obj = _make_steps()
        d = obj.to_dict()
        assert d["title"] == "Create file"


# ---------------------------------------------------------------------------
# Test 7: validate_record returns empty dict for unknown table
# ---------------------------------------------------------------------------


class TestValidateRecordUnknownTable:
    def test_unknown_table_returns_empty_dict_with_warning(self, caplog):
        from scripts.telemetry_schemas import validate_record  # noqa: PLC0415

        with caplog.at_level(logging.WARNING, logger="scripts.telemetry_schemas"):
            result = validate_record("not_a_real_table", {"foo": "bar"})

        assert result == {}
        assert any("unknown table" in msg for msg in caplog.messages)


# ---------------------------------------------------------------------------
# Test 8: TELEMETRY_TABLE_NAMES has exactly 7 entries
# ---------------------------------------------------------------------------


class TestTelemetryTableNames:
    def test_table_names_count(self):
        from scripts.telemetry_schemas import TELEMETRY_TABLE_NAMES  # noqa: PLC0415

        assert len(TELEMETRY_TABLE_NAMES) == 7

    def test_table_names_are_all_telemetry_prefixed(self):
        from scripts.telemetry_schemas import TELEMETRY_TABLE_NAMES  # noqa: PLC0415

        for name in TELEMETRY_TABLE_NAMES:
            assert name.startswith("telemetry_"), f"{name} does not start with telemetry_"


class TestTelemetryTableTimestampCols:
    """TELEMETRY_TABLE_TIMESTAMP_COLS covers all tables and has no ingested_at entries.

    ingested_at is excluded because write() always injects it; including it in
    TELEMETRY_TABLE_TIMESTAMP_COLS would cause compact() to attempt a redundant
    conversion on a column already present in the DataFrame.
    """

    def test_all_seven_tables_have_an_entry(self):
        from scripts.telemetry_schemas import TELEMETRY_TABLE_NAMES, TELEMETRY_TABLE_TIMESTAMP_COLS  # noqa: PLC0415

        for table in TELEMETRY_TABLE_NAMES:
            assert table in TELEMETRY_TABLE_TIMESTAMP_COLS, f"{table} missing from TELEMETRY_TABLE_TIMESTAMP_COLS"

    def test_no_entry_contains_ingested_at(self):
        """ingested_at is always written by OpsWriter.write(); compact() handles it separately."""
        from scripts.telemetry_schemas import TELEMETRY_TABLE_TIMESTAMP_COLS  # noqa: PLC0415

        for table, cols in TELEMETRY_TABLE_TIMESTAMP_COLS.items():
            assert "ingested_at" not in cols, f"{table} should not list ingested_at in TELEMETRY_TABLE_TIMESTAMP_COLS"

    def test_sessions_phases_steps_invocations_have_started_and_ended_at(self):
        from scripts.telemetry_schemas import TELEMETRY_TABLE_TIMESTAMP_COLS  # noqa: PLC0415

        for table in ("telemetry_sessions", "telemetry_phases", "telemetry_steps", "telemetry_agent_invocations"):
            cols = TELEMETRY_TABLE_TIMESTAMP_COLS[table]
            assert "started_at" in cols, f"{table} missing started_at"
            assert "ended_at" in cols, f"{table} missing ended_at"

    def test_event_tables_have_timestamp_field(self):
        from scripts.telemetry_schemas import TELEMETRY_TABLE_TIMESTAMP_COLS  # noqa: PLC0415

        for table in ("telemetry_process_events", "telemetry_model_calls", "telemetry_transcripts"):
            cols = TELEMETRY_TABLE_TIMESTAMP_COLS[table]
            assert "timestamp" in cols, f"{table} missing timestamp"
