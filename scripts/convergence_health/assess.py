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

from scripts.convergence_health.record import (
    count_unapplied_tf_commits,
    read_infra_error_marker,
    record_age_hours,
    red_age_hours,
)

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
    # DEP-11 (T2.47): the routed-pending marker from the convergence record (write-convergence-
    # record's pending_gated merge), or None when absent. Orthogonal to severity/status -- a
    # routed-pending episode leaves status green (anti-masking, Decision 55); this field is what
    # lets the verdict, the drift rec, and the PR advisory status distinguish "pending-gated" from
    # a genuinely converged green or a genuinely red episode.
    pending_gated: Optional[dict[str, Any]] = None
    # Decision 154 / rec-2862: the non-status infra_error marker (write-convergence-record's
    # pre-apply-failure merge), or None when absent. Orthogonal to status like pending_gated, but
    # the severity convention deliberately DIVERGES from it: infra_error FLOORS severity at "low"
    # (never overriding a higher value, never leaving "none") because it marks a failure, whereas
    # pending_gated marks a healthy waiting state and deliberately does not force severity on its
    # own (see test_pending_gated_does_not_force_high_severity_on_its_own). This field aids a human
    # reading convergence_health output only -- severity is emitted solely by
    # scripts/convergence_health/__main__.py; escalate.py never reads it, and preflight does not
    # read it at all, so this floor files nothing on its own.
    infra_error: Optional[dict[str, Any]] = None


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
            pending_gated=None,
            infra_error=None,
        )

    status = record.get("status", "unknown")
    age = red_age_hours(record, now=now)
    rec_age = record_age_hours(record, now=now)
    backlog = count_unapplied_tf_commits(
        record.get("commit_sha", ""),
        git_runner=git_runner,
    )
    approvals = stuck_approvals or []
    pending_gated = record.get("pending_gated")
    infra_error = read_infra_error_marker(record)
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

    # Decision 154 / rec-2862: infra_error FLOORS severity at "low" -- raises "none" to "low",
    # never overrides a higher value ("high" stays "high" even with a marker present), and is
    # computed AFTER the primary severity derivation above so it can only raise, never lower, the
    # result. This is deliberately NOT excluded from red-age escalation by skipping the "red"
    # branch above -- a pre-apply-failure marker coexisting with an unrelated red status (e.g. a
    # later out-of-band drift) must still surface that red's own age-based severity; the floor
    # only ever adds a "low" it would not otherwise have had.
    if infra_error is not None and severity == "none":
        severity = "low"

    return HealthVerdict(
        status=status,
        red_age_hours=round(age, 2),
        unapplied_backlog=backlog,
        stuck_approvals=approvals,
        severity=severity,
        record_age_hours=round(rec_age, 2),
        pending_gated=pending_gated,
        infra_error=infra_error,
    )
