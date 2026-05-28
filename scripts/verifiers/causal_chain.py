"""Verifier for end-to-end telemetry causal chain integrity.

Proves that the telemetry pipeline (Produce -> Transport -> Persist -> Query) is
functioning by emitting a heartbeat event and polling for its appearance in Athena.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid

from scripts.executor.telemetry import emit_process_event
from scripts.ops_writer import DATABASE, OpsWriter

from .harness import Verifier, VerifierResult, VerifierSeverity, VerifierStatus, VerifierTier

logger = logging.getLogger(__name__)


class CausalChainVerifier(Verifier):
    """Proves telemetry pipeline integrity via a round-trip heartbeat."""

    covers: list[str] = [
        "scripts/executor/telemetry.py",
        "scripts/executor/postflight.py",
        "logs/.telemetry-active-session.json",
    ]

    @property
    def tier(self) -> VerifierTier:
        return VerifierTier.V3

    @property
    def severity(self) -> VerifierSeverity:
        return VerifierSeverity.HARD_GATE

    async def verify(self) -> VerifierResult:
        try:
            import awswrangler as wr
            import boto3
        except ImportError:
            return VerifierResult(
                name=self.name,
                status=VerifierStatus.SKIPPED,
                message="awswrangler not available (skipping V3 causal chain check).",
            )

        writer = OpsWriter()
        if not writer._bucket():
            return VerifierResult(
                name=self.name,
                status=VerifierStatus.SKIPPED,
                message="S3_LOG_BUCKET not set (skipping V3 causal chain check).",
            )

        # Pre-flight: credential + region check before emitting an orphan heartbeat.
        profile = os.environ.get("AWS_PROFILE", "company-aws-profile")
        try:
            session = boto3.Session(profile_name=profile, region_name="eu-west-2")
            session.client("sts").get_caller_identity()
        except Exception as exc:
            return VerifierResult(
                name=self.name,
                status=VerifierStatus.SKIPPED,
                message=f"AWS credential error (skipping V3 causal chain check): {exc}",
            )

        # 1. Produce: Emit heartbeat event with a unique nonce
        nonce = str(uuid.uuid4())
        logger.info("CausalChainVerifier: Emitting heartbeat event (nonce=%s)", nonce)

        emit_process_event(
            tier="V3",
            category="VERIFICATION",
            severity="INFO",
            description=f"CausalChainVerifier heartbeat: {nonce}",
            detected_by=self.name,
        )

        # 2. Poll: Wait for the event to appear in Athena
        # Note: In a real environment, we might need to trigger a compaction first
        # if the system doesn't do it automatically or if we want immediate verification.
        # But the verifier's job is to verify the *actual* system, which usually has
        # a delay.

        # Trigger compaction for the process events table to speed up the round-trip
        # (This makes the verifier more deterministic for interactive use)
        writer.compact("telemetry_process_events")

        max_wait = 180
        start_time = time.time()
        backoff = 2

        query = f"""
            SELECT count(*) as count
            FROM {DATABASE}.telemetry_process_events
            WHERE description LIKE '%{nonce}%'
        """

        while time.time() - start_time < max_wait:
            try:
                df = wr.athena.read_sql_query(
                    sql=query,
                    database=DATABASE,
                    ctas_approach=False,
                    workgroup="agent-platform-production",
                    boto3_session=session,
                )

                if not df.empty and df.iloc[0]["count"] > 0:
                    return VerifierResult(
                        name=self.name,
                        status=VerifierStatus.PASS,
                        message=f"Causal chain verified. Heartbeat nonce {nonce} found in Athena.",
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning("CausalChainVerifier: Poll query failed: %s", exc)

            await asyncio.sleep(backoff)
            backoff = min(backoff * 1.5, 10)

        return VerifierResult(
            name=self.name,
            status=VerifierStatus.FAIL,
            message=f"Causal chain broken. Heartbeat nonce {nonce} not found in Athena after {max_wait}s.",
            severity=self.severity,
        )
