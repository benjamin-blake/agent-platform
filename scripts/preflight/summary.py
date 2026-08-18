"""Stdout presentation for session_preflight: the terse one-line summary plus the small set of
alert print blocks that render a computed alert dict to stderr.

Relocated out of scripts/session/preflight.py (PLAN-convergence-health-prod-drift-red) to create
SLOC headroom for the convergence-sensor-liveness wiring -- preflight.py was at 498 effective
lines against the hard 500 gate. Deliberately NOT folded into scripts/preflight/alerts.py: that
module's docstring scopes it to "Recurrence and bypass alert concern" and every one of its seven
functions is a pure derivation that prints nothing -- mixing presentation into it would blur that
boundary. This module holds ONLY presentation (prints); every alert dict it renders is computed
elsewhere (ci_rca_signals.py, alerts.py, context_docs.py) and passed in.
"""

from __future__ import annotations

import sys
from pathlib import Path


def print_convergence_rca_gap_alert(alert: dict | None) -> None:
    """Print the convergence-RCA-gap alert (see ci_rca_signals._check_convergence_rca_gap)."""
    if alert is not None:
        print(
            f"Convergence RCA gap alert: record red {alert['red_age_hours']}h "
            f"(commit {alert.get('commit_sha', '')[:8]}) with no matching ci_rca rec filed "
            "since the red episode began -- file one manually or dispatch ci-rca.yml.",
            file=sys.stderr,
        )


def print_convergence_sensor_liveness_alert(alert: dict | None) -> None:
    """Print the convergence-sensor-liveness alert (see
    ci_rca_signals._check_convergence_sensor_liveness). Distinct from
    print_convergence_rca_gap_alert -- this fires on the WORKFLOW's own conclusion, independent of
    the convergence record's colour, closing the blind spot where a dead sensor looks healthy
    because the record it never reached stays green."""
    if alert is not None:
        print(
            f"Convergence sensor liveness alert: latest convergence-health.yml run concluded "
            f"'{alert.get('conclusion', '')}' (not success) -- {alert.get('run_url', '')}. "
            "A dead sensor can look healthy if the convergence record stays green while only the "
            "workflow itself fails; investigate the run log.",
            file=sys.stderr,
        )


def print_budget_bypass_alert(alert: dict | None) -> None:
    """Print the fast-tier budget-bypass alert (see alerts._check_budget_bypass_alert)."""
    if alert is not None:
        print(
            f"Budget bypass alert: {alert['count']} --ignore-budget invocations in the last 7 days."
            " Repeated bypass indicates fast-tier drift -- consider a planning session to revisit the budget.",
            file=sys.stderr,
        )


def print_budget_breach_summary(summary: dict | None) -> None:
    """Print the fast-tier budget-breach summary (see alerts._check_budget_breach_summary)."""
    if summary is not None:
        dominant_breach_phase = max(summary["by_phase"], key=summary["by_phase"].get)
        print(
            f"Budget breach summary: {summary['count']} fast-tier budget breach(es) in the last "
            f"7 days (dominant phase: {dominant_breach_phase}).",
            file=sys.stderr,
        )


def print_endstate_drift_advisory(endstate_drift: dict) -> None:
    """Print the Platform End-State fingerprint staleness advisory (see
    context_docs._check_endstate_drift)."""
    if endstate_drift.get("stale"):
        new_ids = endstate_drift.get("new_ids") or []
        ids_note = f" (new ids: {new_ids})" if new_ids else ""
        msg = f"Advisory: Platform End-State fingerprint stale -- roadmap has new tier_item IDs since the stamp.{ids_note}"
        print(msg, file=sys.stderr)


def _format_preflight_summary(report: dict, report_path: Path) -> str:
    """One-line summary for stdout. The full JSON is on disk -- duplicating it here
    forces every consuming agent to pay ~12-15k tokens for a payload already
    available via file read."""
    mf = report.get("main_freshness", {}) or {}
    behind = mf.get("commits_behind", "?")
    ahead = mf.get("commits_ahead", "?")
    recs_status = report.get("recs_read_status", "ok")
    recs_status_suffix = "" if recs_status == "ok" else f" [DEGRADED: recs_read_status={recs_status}]"
    ci_rca_unresolved = len(report.get("ci_rca_unresolved_recs") or [])
    ci_rca_likely = len(report.get("ci_rca_likely_resolved_recs") or [])
    if ci_rca_unresolved or ci_rca_likely:
        ci_rca_summary = f"ci_rca_unresolved={ci_rca_unresolved} ci_rca_likely_resolved={ci_rca_likely}"
    else:
        ci_rca_summary = "ci_rca=0"
    convergence_rca_gap = report.get("convergence_rca_gap_alert")
    convergence_rca_gap_suffix = (
        f" convergence_rca_gap_alert=red_{convergence_rca_gap['red_age_hours']}h" if convergence_rca_gap else ""
    )
    sensor_liveness = report.get("convergence_sensor_liveness_alert")
    sensor_liveness_suffix = f" convergence_sensor_liveness_alert={sensor_liveness['conclusion']}" if sensor_liveness else ""
    return (
        f"Preflight OK -> {report_path}\n"
        f"  venv={report.get('venv_ok')} creds={report.get('creds_status')} "
        f"branch={report.get('branch')} main=({behind} behind, {ahead} ahead)\n"
        f"  open_recs={report.get('open_recommendations')} "
        f"non_automatable={report.get('non_automatable_recommendations')} "
        f"{ci_rca_summary}{recs_status_suffix}{convergence_rca_gap_suffix}{sensor_liveness_suffix}\n"
        f"  Read the report file for full constraint detail."
    )
