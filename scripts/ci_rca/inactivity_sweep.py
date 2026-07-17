"""CI-RCA timestamp-based inactivity sweep (ci-rca-identity-lifecycle).

CLI backstop: bin/venv-python -m scripts.ci_rca.inactivity_sweep

Reads every OPEN source=ci_rca rec via the DuckLake reader NAMED VERBS (Decision 84 I-3 /
Decision 88 -- scripts.ops_portal.ci_rca_lifecycle.list_open_ci_rca_recs; no ad-hoc re-fetch) and
closes those satisfying the purely TIMESTAMP-based deterministic inactivity predicate
(ci_rca_lifecycle.is_inactive) through the ops portal (update_rec, resolution=stale_no_recurrence,
with the last_seen + age proof recorded in the closure). Portal-only writes (Decision 84); never
re-stages from a read cache.

Run by .github/workflows/ci-rca-inactivity-sweep.yml on a weekly schedule + workflow_dispatch.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any

from scripts.ops_portal.ci_rca_lifecycle import is_inactive, list_open_ci_rca_recs

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

_RESOLUTION = "stale_no_recurrence"


def find_inactive_recs(rows: list[dict[str, Any]], *, now: "datetime | None" = None) -> list[dict[str, Any]]:
    """Filter parsed source=ci_rca rows (as returned by list_open_ci_rca_recs) down to those
    satisfying the timestamp-based inactivity predicate. Pure function -- no portal I/O."""
    inactive: list[dict[str, Any]] = []
    for row in rows:
        ctx = row.get("_ctx") or {}
        created = str(row.get("created_timestamp") or "")
        if is_inactive(ctx, created, now=now):
            inactive.append(row)
    return inactive


def close_inactive_recs(rows: list[dict[str, Any]], *, profile: str | None = None, dry_run: bool = False) -> list[str]:
    """Close each row via the ops portal with a recorded proof (last_seen/created age). Returns
    the list of rec ids actually closed (empty under --dry-run)."""
    from scripts.ops_data_portal import update_rec  # noqa: PLC0415

    closed: list[str] = []
    for row in rows:
        rec_id = str(row.get("id"))
        ctx = row.get("_ctx") or {}
        last_seen = ctx.get("last_seen") or row.get("created_timestamp")
        created = row.get("created_timestamp")
        proof = f"last_seen={last_seen!r}, created_timestamp={created!r}"
        if dry_run:
            logger.info("[DRY-RUN] would close %s (stale_no_recurrence; %s)", rec_id, proof)
            continue
        update_rec(
            rec_id,
            {
                "status": "closed",
                "resolution": f"CI-RCA inactivity sweep: resolution=stale_no_recurrence. Proof: {proof}.",
            },
            profile=profile,
        )
        logger.info("Closed %s (stale_no_recurrence; %s)", rec_id, proof)
        closed.append(rec_id)
    return closed


def run_sweep(*, profile: str | None = None, dry_run: bool = False) -> dict[str, Any]:
    rows = list_open_ci_rca_recs(profile=profile)
    inactive = find_inactive_recs(rows)
    closed = close_inactive_recs(inactive, profile=profile, dry_run=dry_run)
    return {
        "open_count": len(rows),
        "inactive_count": len(inactive),
        "closed": closed,
        "dry_run": dry_run,
        "swept_at": datetime.now(timezone.utc).isoformat(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CI-RCA timestamp-based inactivity sweep.")
    parser.add_argument("--profile", default=None, help="AWS profile override")
    parser.add_argument("--dry-run", action="store_true", help="Report candidates without closing")
    args = parser.parse_args(argv)

    result = run_sweep(profile=args.profile, dry_run=args.dry_run)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
