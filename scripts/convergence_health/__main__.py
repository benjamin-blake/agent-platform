"""CLI entry point for the convergence-health sensor (called by convergence-health.yml).

Preserves `python -m scripts.convergence_health [--ducklake-drift|--prod-drift]`. Part of
the scripts.convergence_health package -- see scripts/convergence_health/__init__.py for
the full public surface.
"""

from __future__ import annotations

from typing import Optional

from scripts.convergence_health.approvals import (
    diagnose_stuck_approvals,
    find_reconcile_runs_since,
    find_stuck_gated_approvals,
    has_in_flight_reconcile_for_episode,
)
from scripts.convergence_health.assess import assess_health
from scripts.convergence_health.code_drift import detect_ducklake_code_drift, detect_prod_code_drift
from scripts.convergence_health.escalate import escalate
from scripts.convergence_health.record import derive_red_since, read_convergence_record


def main(profile: Optional[str] = None) -> int:
    """Assess convergence health and escalate if warranted. Returns exit code."""
    import json  # noqa: PLC0415
    import os  # noqa: PLC0415

    try:
        import boto3  # noqa: PLC0415

        session = boto3.Session(profile_name=profile)
        s3 = session.client("s3")
    except Exception as exc:  # noqa: BLE001
        print(f"[convergence_health] S3 client init failed: {exc}")
        return 1

    record = read_convergence_record(s3)
    diagnose_mode = bool(os.environ.get("CONVERGENCE_HEALTH_DIAGNOSE"))

    if diagnose_mode:
        diagnose_out = diagnose_stuck_approvals()
        verdict = assess_health(record, stuck_approvals=diagnose_out)
    else:
        stuck = find_stuck_gated_approvals()
        verdict = assess_health(record, stuck_approvals=stuck)

    print(
        f"[convergence_health] HealthVerdict: {
            json.dumps(
                {
                    'status': verdict.status,
                    'red_age_hours': verdict.red_age_hours,
                    'unapplied_backlog': verdict.unapplied_backlog,
                    'stuck_approvals': len(verdict.stuck_approvals),
                    'severity': verdict.severity,
                }
            )
        }"
    )

    if diagnose_mode:
        print(f"[convergence_health] diagnose_stuck_approvals: {diagnose_out}")
        return 0  # read-only; do not escalate

    reconcile_in_flight = False
    if record is not None and record.get("status") == "red":
        # T2.37 c4: only worth the extra API call when there is a red episode to potentially
        # double-file against.
        reconcile_runs = find_reconcile_runs_since()
        reconcile_in_flight = has_in_flight_reconcile_for_episode(reconcile_runs, red_since=derive_red_since(record))

    result = escalate(verdict, profile=profile, reconcile_in_flight=reconcile_in_flight)
    print(f"[convergence_health] escalation result: {result}")
    return 0


def main_ducklake_drift(profile: Optional[str] = None) -> int:
    """Run the DuckLake code-drift sensor (T2.38) and escalate if warranted. Returns exit code."""
    try:
        result = detect_ducklake_code_drift(profile=profile)
    except Exception as exc:  # noqa: BLE001
        print(f"[convergence_health] ducklake_code_drift failed: {exc}")
        return 1
    print(f"[convergence_health] ducklake_code_drift result: {result}")
    return 0


def main_prod_drift(profile: Optional[str] = None) -> int:
    """Run the prod-class code-drift sensor (T2.43) and escalate if warranted. Returns exit code."""
    try:
        result = detect_prod_code_drift(profile=profile)
    except Exception as exc:  # noqa: BLE001
        print(f"[convergence_health] prod_code_drift failed: {exc}")
        return 1
    print(f"[convergence_health] prod_code_drift result: {result}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    import sys

    if "--ducklake-drift" in sys.argv[1:]:
        sys.exit(main_ducklake_drift())
    elif "--prod-drift" in sys.argv[1:]:
        sys.exit(main_prod_drift())
    else:
        sys.exit(main())
