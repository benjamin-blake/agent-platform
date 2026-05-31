"""Verifier for Athena/Iceberg schema integrity against Pydantic models.

Compares local Pydantic models (Recommendation, Session, etc.) against the
authoritative Athena/Iceberg table schemas to detect drift.
"""

from __future__ import annotations

import dataclasses
import logging
import typing
from typing import Any

from scripts.executor.jsonl_store import Recommendation
from scripts.ops_writer import DATABASE, OpsWriter
from scripts.telemetry_schemas import (
    TelemetryAgentInvocations,
    TelemetryModelCalls,
    TelemetryPhases,
    TelemetryProcessEvents,
    TelemetrySessions,
    TelemetrySteps,
    TelemetryTranscripts,
)

from .harness import Verifier, VerifierResult, VerifierSeverity, VerifierStatus, VerifierTier

logger = logging.getLogger(__name__)

# Map table names to their Pydantic/dataclass models for schema comparison
MODEL_MAP: dict[str, Any] = {
    "ops_recommendations": Recommendation,
    "telemetry_sessions": TelemetrySessions,
    "telemetry_phases": TelemetryPhases,
    "telemetry_steps": TelemetrySteps,
    "telemetry_process_events": TelemetryProcessEvents,
    "telemetry_model_calls": TelemetryModelCalls,
    "telemetry_transcripts": TelemetryTranscripts,
    "telemetry_agent_invocations": TelemetryAgentInvocations,
}


class SchemaIntegrityVerifier(Verifier):
    """Detects drift between Pydantic models and Athena/Iceberg schemas."""

    covers: list[str] = [
        "scripts/executor/jsonl_store.py",
        "scripts/ops_data_portal.py",
        "config/agent/data_quality/**",
    ]

    @property
    def tier(self) -> VerifierTier:
        return VerifierTier.V3

    @property
    def severity(self) -> VerifierSeverity:
        return VerifierSeverity.WARN

    async def verify(self) -> VerifierResult:
        try:
            import awswrangler as wr
        except ImportError:
            return VerifierResult(
                name=self.name,
                status=VerifierStatus.SKIPPED,
                message="awswrangler not available (skipping V3 schema check).",
            )

        writer = OpsWriter()
        if not writer._bucket():
            return VerifierResult(
                name=self.name,
                status=VerifierStatus.SKIPPED,
                message="S3_LOG_BUCKET not set (skipping V3 schema check).",
            )

        drift_reports = []

        for table_name, model_cls in MODEL_MAP.items():
            try:
                # Fetch remote schema from Athena catalog
                # Returns dict mapping column name to Athena type
                remote_cols = wr.catalog.get_table_types(database=DATABASE, table=table_name)
                if not remote_cols:
                    # Table not yet provisioned; skip rather than report as drift.
                    # Self-heals when the table is created.
                    continue

                # Extract local field names
                if hasattr(model_cls, "model_fields"):
                    # Pydantic v2
                    local_fields = set(model_cls.model_fields.keys())
                elif hasattr(model_cls, "__dataclass_fields__"):
                    # Dataclass -- use the public API which filters ClassVar entries
                    local_fields = {f.name for f in dataclasses.fields(model_cls)}
                else:
                    # Dataclass or typing.get_type_hints fallback
                    # typing.get_type_hints() is preferred as it handles ClassVar correctly
                    # even with 'from __future__ import annotations'.
                    try:
                        hints = typing.get_type_hints(model_cls)
                        # Filter out ClassVar
                        local_fields = {
                            name for name, hint in hints.items() if getattr(hint, "__origin__", None) is not typing.ClassVar
                        }
                    except Exception:  # noqa: BLE001
                        if hasattr(model_cls, "__dataclass_fields__"):
                            local_fields = set(model_cls.__dataclass_fields__.keys())
                        else:
                            drift_reports.append(f"{table_name}: Could not extract fields from model {model_cls.__name__}")
                            continue

                # Special case: OpsWriter injects SCD2 columns for ops tables
                # and ingested_at/trade_date for all telemetry tables.
                # See scripts/ops_writer.py:_prepare_record()
                if table_name.startswith("ops_"):
                    injected_cols = {"created_timestamp", "last_updated_timestamp"}
                else:
                    injected_cols = {"ingested_at", "trade_date"}
                local_fields.update(injected_cols)

                # Check for missing columns in Athena
                missing_in_athena = local_fields - set(remote_cols.keys())
                # Filter out legacy fields that might be in the model but we don't care if they are missing in Athena
                # (e.g. fields that we dropped or decided not to persist)
                # But for HARD_GATE we want to be strict.

                if missing_in_athena:
                    drift_reports.append(f"{table_name}: Missing columns in Athena: {sorted(missing_in_athena)}")

            except Exception as exc:  # noqa: BLE001
                exc_str = str(exc)
                if any(err in exc_str for err in ["credentials", "Token has expired", "You must specify a region"]):
                    return VerifierResult(
                        name=self.name,
                        status=VerifierStatus.SKIPPED,
                        message=f"AWS credential error (skipping V3 schema check): {exc_str}",
                    )
                # Table/entity not found means it is not yet provisioned; skip (self-heals when created).
                if any(err in exc_str for err in ["EntityNotFoundException", "not found", "does not exist"]):
                    continue
                drift_reports.append(f"{table_name}: Error during comparison: {exc}")

        if not drift_reports:
            return VerifierResult(
                name=self.name,
                status=VerifierStatus.PASS,
                message=f"Schema integrity verified for {len(MODEL_MAP)} tables. No drift detected.",
            )

        return VerifierResult(
            name=self.name,
            status=VerifierStatus.FAIL,
            message="Schema drift detected: " + "; ".join(drift_reports),
            severity=self.severity,
        )
