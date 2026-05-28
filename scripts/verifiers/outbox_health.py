"""Verifier for local telemetry outbox health.

Checks if any pending telemetry files exist in logs/.ops-outbox/.
Fails if the outbox is not empty, indicating a sync failure or pending drain.
"""

from __future__ import annotations

import time
from pathlib import Path

from .harness import Verifier, VerifierResult, VerifierSeverity, VerifierStatus, VerifierTier


class OutboxHealthVerifier(Verifier):
    """Checks for pending telemetry in the local outbox.

    Staleness thresholds:
    - > 24h: HARD_GATE (pipeline is likely broken)
    - > 2h: ADVISORY (sync is lagging)
    - <= 2h: PASS (normal operation)
    """

    covers: list[str] = [
        "scripts/ops_data_portal.py",
        "logs/.ops-outbox/**",
        "scripts/sync_ops.py",
    ]

    @property
    def tier(self) -> VerifierTier:
        return VerifierTier.V1

    async def verify(self) -> VerifierResult:
        # Resolve logs/ relative to repo root (parent of scripts/)
        root = Path(__file__).resolve().parent.parent.parent
        outbox_dir = root / "logs" / ".ops-outbox"

        if not outbox_dir.exists():
            return VerifierResult(
                name=self.name,
                status=VerifierStatus.PASS,
                message="Outbox directory does not exist (clean).",
            )

        # Count all .jsonl files in any subdirectories
        pending_files = list(outbox_dir.rglob("*.jsonl"))
        count = len(pending_files)

        if count == 0:
            return VerifierResult(
                name=self.name,
                status=VerifierStatus.PASS,
                message="Outbox is empty.",
            )

        # Check staleness
        now = time.time()
        stale_hard = []
        stale_advisory = []
        fresh = 0

        for p in pending_files:
            mtime = p.stat().st_mtime
            age_h = (now - mtime) / 3600

            if age_h > 24:
                stale_hard.append(p)
            elif age_h > 2:
                stale_advisory.append(p)
            else:
                fresh += 1

        if not stale_hard and not stale_advisory:
            return VerifierResult(
                name=self.name,
                status=VerifierStatus.PASS,
                message=f"Outbox contains {count} fresh files (<2h old).",
            )

        # Summarise by table for the most severe category
        target_files = stale_hard if stale_hard else stale_advisory
        tables = {}
        for p in target_files:
            table_name = p.parent.name
            tables[table_name] = tables.get(table_name, 0) + 1

        summary = ", ".join(f"{t}: {c}" for t, c in sorted(tables.items()))
        severity = VerifierSeverity.HARD_GATE if stale_hard else VerifierSeverity.ADVISORY
        status = VerifierStatus.FAIL

        msg = (
            f"Outbox contains {len(target_files)} stale files "
            f"({'>24h' if stale_hard else '>2h'}): {summary}. "
            f"Total pending: {count} ({fresh} fresh). Run sync_ops --drain."
        )

        return VerifierResult(
            name=self.name,
            status=status,
            message=msg,
            severity=severity,
        )
