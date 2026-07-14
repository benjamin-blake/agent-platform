"""Convergence-stale idempotent escalation (CD.35 Wave 6 / T2.35).

Provides an idempotent escalation path: files OR updates a single
tf_convergence_stale rec per red-episode via scripts.ops_data_portal
(file_rec / update_rec). Never writes the convergence record; never runs
terraform apply; never dispatches terraform-apply-sandbox. Part of the
scripts.convergence_health package -- see scripts/convergence_health/__init__.py
for the full public surface.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from scripts.convergence_health.assess import (
    RED_AGE_THRESHOLD_HOURS,
    STALE_GREEN_BACKLOG_THRESHOLD_HOURS,
    HealthVerdict,
    escalation_action,
)

# Three mutually-branched escalation conditions (T2.35 hardening). A stuck gated-apply approval
# takes priority in the title/context even when it co-occurs with a persistently-red record --
# it is the more directly actionable signal (approve/cancel the run). stale_green_backlog and
# persistently_red are mutually exclusive by construction (they require status=="green" and
# status=="red" respectively).
_TITLE_STUCK_APPROVAL = "Gated-apply approval stuck -- staleness escalation"
_TITLE_STALE_GREEN_BACKLOG = "Sandbox convergence green with stale unapplied backlog -- staleness escalation"
_TITLE_PERSISTENTLY_RED = "Sandbox convergence record persistently red -- staleness escalation"

_RESOLUTION_STUCK_APPROVAL = "Gated-apply approval cleared (approved or cancelled); staleness episode resolved."
_RESOLUTION_STALE_GREEN_BACKLOG = "Unapplied terraform/personal/ backlog drained; staleness episode resolved."
_RESOLUTION_PERSISTENTLY_RED = "Convergence record returned to green; staleness episode resolved."


def find_open_convergence_stale_rec(
    open_recs: list[dict[str, Any]],
) -> Optional[dict[str, Any]]:
    """Return the first open tf_convergence_stale rec from a list of open recs, or None."""
    for rec in open_recs:
        if rec.get("source") == "tf_convergence_stale" and rec.get("status") == "open":
            return rec
    return None


def _fetch_open_recs(profile: Optional[str] = None) -> list[dict[str, Any]]:
    """Fetch all open recs from the DuckLake reader (live, never the local JSONL cache)."""
    from src.common.iceberg_reader import make_reader  # noqa: PLC0415

    return make_reader(profile=profile).named("open_recs") or []


def _condition_for_verdict(verdict: HealthVerdict) -> str:
    """Classify which of the three escalation conditions this verdict represents."""
    if verdict.stuck_approvals:
        return "stuck_approval"
    if verdict.status == "green" and verdict.unapplied_backlog > 0:
        return "stale_green_backlog"
    return "persistently_red"


def _condition_from_existing_rec(existing: dict[str, Any]) -> str:
    """Recover the escalation condition an open rec was filed for, from its title.

    Needed at close time: by definition every trigger has cleared (over_threshold is False),
    so the current verdict can no longer tell us which condition the rec was tracking.
    """
    title = existing.get("title", "")
    if title == _TITLE_STUCK_APPROVAL:
        return "stuck_approval"
    if title == _TITLE_STALE_GREEN_BACKLOG:
        return "stale_green_backlog"
    return "persistently_red"


def _build_context(verdict: HealthVerdict, condition: str) -> str:
    if condition == "stuck_approval":
        parts = [
            f"{len(verdict.stuck_approvals)} terraform-apply-sandbox run(s) are waiting on "
            "the tf-gated-apply Environment approval (stuck > threshold), independent of the "
            f"convergence record's own status ({verdict.status})."
        ]
        parts.append(
            "Resolve via: approve or cancel the pending gated-apply run in GitHub Actions -> "
            "Review pending deployments. This rec closes automatically on the next sensor "
            "tick once no stuck approvals remain."
        )
    elif condition == "stale_green_backlog":
        parts = [
            f"The sandbox convergence record is green, but {verdict.unapplied_backlog} merged "
            "terraform/personal/ commit(s) have been pending application for "
            f"{verdict.record_age_hours:.1f} hours -- past the "
            f"{STALE_GREEN_BACKLOG_THRESHOLD_HOURS:.1f}h stale-green-backlog threshold."
        ]
        parts.append(
            "Resolve via: run terraform-apply-sandbox workflow_dispatch (or land a "
            "terraform/personal/ change) to apply the pending backlog. This rec closes "
            "automatically on the next sensor tick once the backlog drains."
        )
    else:
        parts = [
            f"The sandbox convergence record has been red for {verdict.red_age_hours:.1f} hours.",
        ]
        if verdict.unapplied_backlog:
            parts.append(
                f"{verdict.unapplied_backlog} merged terraform/personal/ commit(s) are pending "
                "application since the last green convergence commit."
            )
        parts.append(
            "Resolve via: (a) approve the pending gated-apply run in GitHub Actions, or "
            "(b) run terraform-apply-sandbox workflow_dispatch with acknowledge_red_commit "
            "naming the red commit SHA. This rec closes automatically on the next sensor "
            "tick once the convergence record returns to green."
        )
    return " ".join(parts)


def _build_rec_fields(verdict: HealthVerdict, condition: str) -> dict[str, Any]:
    title = {
        "stuck_approval": _TITLE_STUCK_APPROVAL,
        "stale_green_backlog": _TITLE_STALE_GREEN_BACKLOG,
    }.get(condition, _TITLE_PERSISTENTLY_RED)
    return {
        "title": title,
        "file": ".github/workflows/convergence-health.yml",
        "status": "open",
        "source": "tf_convergence_stale",
        "priority": "High",
        "effort": "S",
        "risk": "medium",
        "verification_tier": "V2",
        "context": _build_context(verdict, condition),
        "acceptance": (
            "the triggering condition clears (approvals resolved, backlog drained, or the "
            "convergence record returns to green) and this rec is closed via the standard "
            "portal path (update_rec --status closed, or a Resolves: trailer when a fix PR lands)."
        ),
    }


def escalate(
    verdict: HealthVerdict,
    portal_caller: Optional[Callable[[str, dict[str, Any]], Any]] = None,
    open_recs: Optional[list[dict[str, Any]]] = None,
    threshold_hours: float = RED_AGE_THRESHOLD_HOURS,
    profile: Optional[str] = None,
    reconcile_in_flight: bool = False,
) -> dict[str, Any]:
    """Idempotent escalation: file/update/close exactly one tf_convergence_stale rec per episode.

    Args:
        verdict:       HealthVerdict from assess_health.
        portal_caller: Injected callable(action, fields) for testability. When None,
                       uses scripts.ops_data_portal.file_rec / update_rec directly.
        open_recs:     Pre-fetched open rec list (for testing). When None, fetches live
                       via the DuckLake reader open_recs named verb (not the JSONL cache).
        threshold_hours: Red-age threshold triggering escalation.
        profile:       AWS profile for the reader / portal.
        reconcile_in_flight: T2.37 c4 -- True when a reconcile.yml Actions run has already
                       started (or completed) during the current red episode (see
                       has_in_flight_reconcile_for_episode). Suppresses ONLY a fresh "file"
                       action -- an already-open rec still updates/closes normally, since
                       refreshing an existing rec's context is not a double-file.

    Returns:
        {"action": "file"|"update"|"close"|"none"|"skipped"|"skipped_reconcile_in_flight", "rec_id": str|None}
    """
    if open_recs is None:
        open_recs = _fetch_open_recs(profile=profile)

    existing = find_open_convergence_stale_rec(open_recs)
    open_rec_exists = existing is not None

    stuck_approval_trigger = bool(verdict.stuck_approvals)
    red_age_trigger = verdict.status == "red" and verdict.red_age_hours >= threshold_hours
    stale_green_backlog_trigger = (
        verdict.status == "green"
        and verdict.unapplied_backlog > 0
        and verdict.record_age_hours >= STALE_GREEN_BACKLOG_THRESHOLD_HOURS
    )
    over_threshold = stuck_approval_trigger or red_age_trigger or stale_green_backlog_trigger

    action = escalation_action(over_threshold=over_threshold, open_rec_exists=open_rec_exists)

    if action == "file" and reconcile_in_flight:
        # T2.37 c4: a Reconcile dispatch already started (or completed) during this red episode --
        # do not double-file a NEW tf_convergence_stale rec for the episode Reconcile is already
        # clearing. The episode either resolves (record returns green, no rec ever needed) or the
        # reconcile run itself fails, and the next sensor tick re-evaluates from a clean slate.
        return {"action": "skipped_reconcile_in_flight", "rec_id": None}

    if action == "none":
        return {"action": "none", "rec_id": None}

    if action == "file":
        condition = _condition_for_verdict(verdict)
        fields = _build_rec_fields(verdict, condition)
        if portal_caller is not None:
            rec_id = portal_caller("file", fields)
        else:
            from scripts.ops_data_portal import file_rec  # noqa: PLC0415

            rec_id = file_rec(fields, profile=profile)
        return {"action": "file", "rec_id": rec_id}

    if action == "update" and existing is not None:
        condition = _condition_for_verdict(verdict)
        updates = {"context": _build_context(verdict, condition)}
        if portal_caller is not None:
            portal_caller("update", {"id": existing["id"], **updates})
        else:
            from scripts.ops_data_portal import update_rec  # noqa: PLC0415

            update_rec(existing["id"], updates, profile=profile)
        return {"action": "update", "rec_id": existing["id"]}

    if action == "close" and existing is not None:
        condition = _condition_from_existing_rec(existing)
        resolution = {
            "stuck_approval": _RESOLUTION_STUCK_APPROVAL,
            "stale_green_backlog": _RESOLUTION_STALE_GREEN_BACKLOG,
        }.get(condition, _RESOLUTION_PERSISTENTLY_RED)
        updates = {
            "status": "closed",
            "resolution": resolution,
        }
        if portal_caller is not None:
            portal_caller("close", {"id": existing["id"], **updates})
        else:
            from scripts.ops_data_portal import update_rec  # noqa: PLC0415

            update_rec(existing["id"], updates, profile=profile)
        return {"action": "close", "rec_id": existing["id"]}

    return {"action": "skipped", "rec_id": None}
