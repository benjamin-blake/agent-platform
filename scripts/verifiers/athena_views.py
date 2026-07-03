"""Verifier for live DuckLake ops_decisions reachability.

Repointed (VF-03) off the frozen Athena decisions view onto the live DuckLake
decisions surface via the closed ducklake_reader boundary (Decision 84 I-3: named_read verb,
no caller SQL). Returns SKIPPED if the reader/creds are unavailable, PASS if the named-verb
read succeeds, and FAIL on unexpected error. Asserts no currency of the returned timestamp --
it proves the surface is reachable, not how up to date its data is.

The class name and module path are retained despite the repoint (documented misnomer): a
rename would cascade to the REGISTRY import, the test module, and the filename, which is
deferred to keep this plan's blast radius small.
"""

from __future__ import annotations

import logging

from .harness import Hermeticity, Verifier, VerifierResult, VerifierStatus, VerifierTier

logger = logging.getLogger(__name__)


class AthenaViewsVerifier(Verifier):
    """Checks live DuckLake ops_decisions reachability via the closed reader boundary."""

    hermeticity: Hermeticity = Hermeticity.NON_HERMETIC_BY_CONSTRUCTION  # network
    covers: list[str] = [
        "src/common/iceberg_reader.py",
        "src/common/ducklake_scd2_schema.py",
    ]

    @property
    def tier(self) -> VerifierTier:
        return VerifierTier.V3

    async def verify(self) -> VerifierResult:
        try:
            from src.common.iceberg_reader import DuckLakeReader
        except ImportError as exc:
            return VerifierResult(
                name=self.name,
                status=VerifierStatus.SKIPPED,
                message=f"src.common.iceberg_reader not available in this environment: {exc}",
            )

        try:
            reader = DuckLakeReader()
            rows = reader.named("decisions_max_updated")
        except RuntimeError as exc:
            if "cannot reach the DuckLake reader" in str(exc):
                return VerifierResult(
                    name=self.name,
                    status=VerifierStatus.SKIPPED,
                    message=f"DuckLake reader unreachable (creds/reader unavailable): {exc}",
                )
            return VerifierResult(
                name=self.name,
                status=VerifierStatus.FAIL,
                message=f"DuckLake decisions_max_updated read failed (connectivity or verb issue): {exc}",
            )
        except Exception as exc:
            return VerifierResult(
                name=self.name,
                status=VerifierStatus.FAIL,
                message=f"DuckLake decisions_max_updated read failed (unexpected error): {exc}",
            )

        ts = rows[0].get("ts") if rows else None
        return VerifierResult(
            name=self.name,
            status=VerifierStatus.PASS,
            message=f"Live ops_decisions reachable via DuckLake (decisions_max_updated -> {ts}).",
        )
