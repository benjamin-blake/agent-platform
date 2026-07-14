"""Health assessment surface for the convergence-health sensor (CD.35 Wave 6 / T2.35).

Derives a HealthVerdict from the convergence record and supplementary
signals (stuck gated-apply approvals, unapplied terraform/personal/
backlog). Part of the scripts.convergence_health package -- see
scripts/convergence_health/__init__.py for the full public surface.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional

from scripts.convergence_health.record import count_unapplied_tf_commits, record_age_hours, red_age_hours

RED_AGE_THRESHOLD_HOURS: float = 6.0
# Must exceed normal apply latency (an apply advances the record within minutes) so a healthy
# in-flight merge can never false-positive; only a green record with a backlog persisting for
# hours escalates.
STALE_GREEN_BACKLOG_THRESHOLD_HOURS: float = 2.0


@dataclass
class HealthVerdict:
    status: str  # "green" | "red" | "unknown"
    red_age_hours: float
    unapplied_backlog: int
    stuck_approvals: list[dict[str, Any]] = field(default_factory=list)
    severity: str = "none"  # "none" | "low" | "high"
    record_age_hours: float = 0.0


def escalation_action(over_threshold: bool, open_rec_exists: bool) -> str:
    """Return the action to take given red-age and existing-rec state.

    Returns:
        "file"   -- new rec should be filed (over threshold, no open rec yet)
        "update" -- existing open rec should be updated (still over threshold)
        "close"  -- existing open rec should be closed (under threshold / green)
        "none"   -- nothing to do (under threshold, no open rec)
    """
    if over_threshold and not open_rec_exists:
        return "file"
    if over_threshold and open_rec_exists:
        return "update"
    if not over_threshold and open_rec_exists:
        return "close"
    return "none"


def assess_health(
    record: Optional[dict[str, Any]],
    stuck_approvals: Optional[list[dict[str, Any]]] = None,
    git_runner: Optional[Callable[[list[str]], str]] = None,
    now: Optional[datetime] = None,
) -> HealthVerdict:
    """Derive a HealthVerdict from the convergence record and supplementary signals."""
    if record is None:
        return HealthVerdict(
            status="unknown",
            red_age_hours=0.0,
            unapplied_backlog=0,
            stuck_approvals=[],
            severity="none",
            record_age_hours=0.0,
        )

    status = record.get("status", "unknown")
    age = red_age_hours(record, now=now)
    rec_age = record_age_hours(record, now=now)
    backlog = count_unapplied_tf_commits(
        record.get("commit_sha", ""),
        git_runner=git_runner,
    )
    approvals = stuck_approvals or []
    stale_green_backlog = status == "green" and backlog > 0 and rec_age >= STALE_GREEN_BACKLOG_THRESHOLD_HOURS

    if approvals:
        # A stuck gated-apply approval escalates independent of the record's own status --
        # a routed gated-apply deliberately leaves the record green while it waits.
        severity = "high"
    elif status == "red":
        severity = "high" if age >= RED_AGE_THRESHOLD_HOURS else "low"
    elif stale_green_backlog:
        severity = "high"
    else:
        severity = "none"

    return HealthVerdict(
        status=status,
        red_age_hours=round(age, 2),
        unapplied_backlog=backlog,
        stuck_approvals=approvals,
        severity=severity,
        record_age_hours=round(rec_age, 2),
    )
