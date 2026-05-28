"""Verifier for data quality assertions.

Runs the full DQ check suite directly against Athena. Never reads from a local cache file.
"""

from __future__ import annotations

import os
from pathlib import Path

from .harness import Verifier, VerifierResult, VerifierSeverity, VerifierStatus, VerifierTier

_ROOT = Path(__file__).resolve().parent.parent.parent
_DQ_DIR = _ROOT / "config" / "agent" / "data_quality"


class DataQualityVerifier(Verifier):
    """Runs DQ checks against Athena directly; never reads a local cache."""

    covers: list[str] = [
        "config/agent/data_quality/**",
        "scripts/data_quality_runner.py",
        "scripts/ops_data_portal.py",
        "src/data/**",
    ]

    @property
    def tier(self) -> VerifierTier:
        return VerifierTier.V2

    async def verify(self) -> VerifierResult:
        try:
            import boto3

            from scripts.data_quality_runner import (
                build_tombstone_checks,
                load_checks,
                load_tombstones,
                run_checks,
            )
        except ImportError as exc:
            return VerifierResult(
                name=self.name,
                status=VerifierStatus.SKIPPED,
                message=f"Required module unavailable (skipping DQ check): {exc}",
            )

        profile = os.environ.get("AWS_PROFILE", "company-aws-profile")
        try:
            boto3.Session(profile_name=profile).client("sts", region_name="eu-west-2").get_caller_identity()
        except Exception as exc:
            return VerifierResult(
                name=self.name,
                status=VerifierStatus.SKIPPED,
                message=f"AWS credentials unavailable (skipping DQ check): {exc}",
            )

        yaml_files = sorted(_DQ_DIR.glob("*.yaml"))
        if not yaml_files:
            return VerifierResult(
                name=self.name,
                status=VerifierStatus.FAIL,
                message=f"No DQ YAML files found in {_DQ_DIR}.",
                severity=VerifierSeverity.HARD_GATE,
            )

        all_checks = []
        workgroup = "agent-platform-production"
        database = "trading_formulas_db"
        for yf in yaml_files:
            checks, metadata = load_checks(yf)
            workgroup = metadata.get("athena_workgroup", workgroup)
            database = metadata.get("database", database)
            all_checks.extend(checks)

        all_checks.extend(build_tombstone_checks(load_tombstones(), database=database))

        result = run_checks(all_checks, workgroup, database, profile_name=profile)

        if result.verdict == "SKIP":
            return VerifierResult(
                name=self.name,
                status=VerifierStatus.SKIPPED,
                message="DQ checks skipped (boto3 unavailable or dry-run).",
            )

        total = len(result.results)
        if total == 0:
            return VerifierResult(
                name=self.name,
                status=VerifierStatus.FAIL,
                message="DQ run returned 0 checks -- runner may have silently skipped all checks.",
                severity=VerifierSeverity.HARD_GATE,
            )

        if result.verdict == "PASS":
            return VerifierResult(
                name=self.name,
                status=VerifierStatus.PASS,
                message=f"Data quality passed: {result.passed} passed, {result.warned} warned.",
            )

        msg = (
            f"Data quality {result.verdict}: {result.hard_gated} hard-gated, {result.failed} failed, "
            f"{result.errored} errored, {result.warned} warned. Run validate.py --scope dq for details."
        )
        return VerifierResult(
            name=self.name,
            status=VerifierStatus.FAIL,
            message=msg,
            severity=VerifierSeverity.HARD_GATE,
        )
