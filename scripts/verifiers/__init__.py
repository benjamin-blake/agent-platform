"""Verifier registry and discovery logic.

Central registry of all programmatic verifiers used in the V3 integration flow.
"""

from __future__ import annotations

import fnmatch

from .athena_views import AthenaViewsVerifier
from .data_quality import DataQualityVerifier
from .harness import Hermeticity, Verifier, VerifierResult, VerifierSeverity, VerifierStatus, VerifierTier
from .outbox_health import OutboxHealthVerifier
from .schema_integrity import SchemaIntegrityVerifier

# Registry of all verifiers that should run during the integration flow.
# These provide hard gates for autonomous execution.
REGISTRY: list[type[Verifier]] = [
    OutboxHealthVerifier,
    AthenaViewsVerifier,
    SchemaIntegrityVerifier,
    DataQualityVerifier,
    # CausalChainVerifier deregistered during public-repo CI bootstrap; telemetry tables
    # are deferred. Reactivate per docs/ROADMAP-PLATFORM.yaml T2.15, T3.20, and CD.40
    # once telemetry_agent_turns is live.
]


async def run_all_verifiers(
    tier_filter: VerifierTier | None = None,
    min_severity: VerifierSeverity | None = None,
    verifier_name: str | None = None,
) -> list[VerifierResult]:
    """Instantiate and run all registered verifiers sequentially.

    Args:
        tier_filter: If provided, only run verifiers in this tier.
        min_severity: If provided, only run verifiers with this severity or higher.
        verifier_name: If provided, only run the verifier with this class name.

    Returns:
        List of VerifierResult objects.
    """
    results = []
    for verifier_cls in REGISTRY:
        # Instantiate to check properties
        verifier = verifier_cls()

        if verifier_name and verifier.name != verifier_name:
            continue

        if tier_filter and verifier.tier.value != tier_filter.value:
            continue

        if min_severity and verifier.severity.rank < min_severity.rank:
            continue

        results.append(await verifier.run())
    return results


def check_coverage(scope_files: list[str]) -> list[str]:
    """Return scope files not matched by any registered verifier's covers globs.

    Wave 1 of INTENT-verification-system.md: surfaces V3 verifier coverage gaps
    so planners and `validate.py --coverage` can identify scope files that lack
    a verifier. Reads each verifier class's `covers` attribute (a list of
    fnmatch globs) directly from the REGISTRY without instantiation.
    """
    all_globs: list[str] = []
    for verifier_cls in REGISTRY:
        all_globs.extend(g for g in getattr(verifier_cls, "covers", []) if g not in ("**", "*"))

    uncovered: list[str] = []
    for path in scope_files:
        normalised = path.replace("\\", "/")
        if not any(fnmatch.fnmatch(normalised, glob) for glob in all_globs):
            uncovered.append(path)
    return uncovered


__all__ = [
    "Verifier",
    "VerifierResult",
    "VerifierStatus",
    "Hermeticity",
    "REGISTRY",
    "check_coverage",
    "run_all_verifiers",
]
