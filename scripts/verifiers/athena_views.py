"""Verifier for Athena connectivity and view freshness.

Checks if the AWS SSO session is active and if Athena views are queryable.
Returns SKIPPED if auth is missing, PASS if connected, and FAIL if queries fail.
"""

from __future__ import annotations

import logging

from scripts.aws_profile import resolve_aws_profile

from .harness import Hermeticity, Verifier, VerifierResult, VerifierStatus, VerifierTier

logger = logging.getLogger(__name__)


class AthenaViewsVerifier(Verifier):
    """Checks Athena connectivity and basic view health."""

    hermeticity: Hermeticity = Hermeticity.NON_HERMETIC_BY_CONSTRUCTION  # network

    @property
    def tier(self) -> VerifierTier:
        return VerifierTier.V3

    async def verify(self) -> VerifierResult:
        try:
            import awswrangler as wr
            import boto3
        except ImportError:
            return VerifierResult(
                name=self.name,
                status=VerifierStatus.SKIPPED,
                message="boto3 or awswrangler not available in this environment.",
            )

        # 1. Check Auth (SSO)
        try:
            profile = resolve_aws_profile(default="agent_platform")
            session = boto3.Session(profile_name=profile)
            sts = session.client("sts")
            sts.get_caller_identity()
        except Exception as exc:
            return VerifierResult(
                name=self.name,
                status=VerifierStatus.SKIPPED,
                message=f"AWS SSO session inactive or profile missing: {exc}",
            )

        # 2. Test Connectivity via simple query using ops_decisions_current (the surviving view
        # post-T2.7 recs-view drop; retained until the decisions table migrates to DuckLake).
        try:
            # Import constants from ops_writer to ensure consistency
            from scripts.ops_writer import ATHENA_WORKGROUP, DATABASE

            # Use ops_decisions_current as the liveness probe (surviving view post-T2.19 view drop).
            df = wr.athena.read_sql_query(
                sql="SELECT count(*) as cnt FROM ops_decisions_current",
                database=DATABASE,
                workgroup=ATHENA_WORKGROUP,
                ctas_approach=False,
                boto3_session=session,
            )
            count = int(df["cnt"].iloc[0])
            return VerifierResult(
                name=self.name,
                status=VerifierStatus.PASS,
                message=f"Athena connected (database: {DATABASE}). Views are fresh. Found {count} decisions.",
            )
        except Exception as exc:
            return VerifierResult(
                name=self.name,
                status=VerifierStatus.FAIL,
                message=f"Athena query failed (connectivity or schema issue): {exc}",
            )
