"""CI-RCA gauge concern for session_preflight."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

from scripts.preflight import _common


def _compute_ci_rca_abstention(cache_rows: list[dict] | None, window_days: int = 14) -> dict | None:
    """Compute the CI-RCA probe abstention gauge from the warm cache (T1.13 c12(i)).

    Returns None when the warm cache is unavailable (reader unreachable / offline) --
    zero new reader egress (Decision 88), computed entirely from already-loaded rows.
    """
    if cache_rows is None:
        return None
    from scripts.ci_rca.probe_health import compute_abstention_rate  # noqa: PLC0415

    undetermined_count, total_count, rate = compute_abstention_rate(cache_rows, window_days=window_days)
    return {
        "undetermined_count": undetermined_count,
        "total_count": total_count,
        "rate": rate,
        "window_days": window_days,
    }


def _escalate_ci_rca_probe_health(
    creds_status: str,
    cache_rows: list[dict] | None,
    gauge: dict | None,
) -> dict | None:
    """Idempotently file/update/close a source=ci_rca_probe_health rec on the warm-cache path.

    Skips (returns None) when creds are unavailable or the warm cache did not load -- degraded
    offline sessions never attempt a portal write. This is the deterministic preflight trigger
    that substitutes for a cron until Lambda scheduled agents re-enable (AGENTS.md runbook).
    """
    if creds_status != "ok" or cache_rows is None or gauge is None:
        return None
    try:
        from scripts.ci_rca.probe_health import escalate  # noqa: PLC0415

        open_recs = [r for r in cache_rows if r.get("status") == "open"]
        return escalate(
            gauge["undetermined_count"],
            gauge["total_count"],
            gauge["rate"],
            open_recs,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[WARN] preflight: ci_rca_probe_health.escalate() failed: {exc}", file=sys.stderr)
        return None


def print_ci_rca_abstention_gauge(gauge: dict | None) -> None:
    """Print the CI-RCA probe abstention-rate gauge line."""
    if gauge is None:
        return
    print(
        f"CI-RCA probe abstention (last {gauge['window_days']}d): "
        f"{gauge['undetermined_count']}/{gauge['total_count']} undetermined ({gauge['rate']:.0%})"
    )


_CI_RCA_TELEMETRY_WINDOW_DAYS = 7


_CI_RCA_WARN_REJECT_ALERT_THRESHOLD = 0.25


_CI_RCA_WARN_REJECT_PROMOTION_THRESHOLD = 0.05


def _compute_ci_rca_telemetry(
    cache_rows: list[dict] | None,
    window_days: int = _CI_RCA_TELEMETRY_WINDOW_DAYS,
    now: datetime | None = None,
) -> dict | None:
    """Compute the CI-RCA Section 7 telemetry gauge from the warm cache (T1.13 c1/c3).

    Re-grounded from the stale Athena ops_ci_rca_telemetry table / ci_rca_health view (INTENT
    Section 7.1/7.3) to warm-cache-derived surfacing: recurrence-class distribution, the
    warn-mode reject rate (c3's load-bearing metric, from context_v2_json.warn_mode_reject
    markers), dispute-path traffic, bundle-upload backlog, and why_chain_terminus_override
    usage -- all parsed off already-loaded recs_cache rows (Decision 88, zero new reader
    egress). Returns None when the warm cache is unavailable (reader unreachable / offline).

    Strict-mode rejections are NOT counted here: they raise before any rec is written, so
    strict rejection-by-reason counts are not cache-derivable and are deferred to telemetry
    Phase 4 (T2.36).
    """
    if cache_rows is None:
        return None
    import json as _json  # noqa: PLC0415

    if now is None:
        now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=window_days)

    recurrence_class_distribution = {"novel": 0, "instance_of_known_pattern": 0, "regression": 0}
    warn_mode_reject_count = 0
    ci_rca_total = 0
    dispute_count = 0
    bundle_upload_backlog = 0
    why_chain_terminus_override_count = 0

    for row in cache_rows:
        ts = _common._row_ts(row)
        if ts is None or ts < cutoff:
            continue
        source = row.get("source")
        if source == "ci_rca_evidence_dispute":
            dispute_count += 1
            continue
        if source != "ci_rca":
            continue
        ci_rca_total += 1
        ctx_raw = row.get("context_v2_json") or ""
        if not ctx_raw:
            continue
        try:
            ctx = _json.loads(ctx_raw)
        except Exception:
            continue
        recurrence_class = ctx.get("recurrence_class")
        if recurrence_class in recurrence_class_distribution:
            recurrence_class_distribution[recurrence_class] += 1
        if ctx.get("warn_mode_reject"):
            warn_mode_reject_count += 1
        evidence_bundle_ref = ctx.get("evidence_bundle_ref") or {}
        if evidence_bundle_ref and evidence_bundle_ref.get("upload_status") != "ok":
            bundle_upload_backlog += 1
        if ctx.get("why_chain_terminus_override"):
            why_chain_terminus_override_count += 1

    warn_mode_reject_rate = (warn_mode_reject_count / ci_rca_total) if ci_rca_total else 0.0
    if warn_mode_reject_rate > _CI_RCA_WARN_REJECT_ALERT_THRESHOLD:
        threshold_note = "enforcement may need tuning"
    elif warn_mode_reject_rate <= _CI_RCA_WARN_REJECT_PROMOTION_THRESHOLD:
        threshold_note = "Phase-4 promotion gate met"
    else:
        threshold_note = None

    return {
        "window_days": window_days,
        "recurrence_class_distribution": recurrence_class_distribution,
        "warn_mode_reject_count": warn_mode_reject_count,
        "ci_rca_total": ci_rca_total,
        "warn_mode_reject_rate": warn_mode_reject_rate,
        "warn_mode_reject_threshold_note": threshold_note,
        "dispute_count": dispute_count,
        "bundle_upload_backlog": bundle_upload_backlog,
        "why_chain_terminus_override_count": why_chain_terminus_override_count,
    }


def print_ci_rca_telemetry(telemetry: dict | None) -> None:
    """Print the CI-RCA Telemetry (last Nd) section (T1.13 c1/c3)."""
    window_days = telemetry["window_days"] if telemetry else _CI_RCA_TELEMETRY_WINDOW_DAYS
    print(f"\n--- CI-RCA Telemetry (last {window_days}d) ---")
    if telemetry is None:
        print("  (unavailable -- warm cache not loaded)")
        print()
        return
    dist = telemetry["recurrence_class_distribution"]
    print(
        "  Recurrence class: "
        f"novel={dist['novel']} instance_of_known_pattern={dist['instance_of_known_pattern']} regression={dist['regression']}"
    )
    note = f" ({telemetry['warn_mode_reject_threshold_note']})" if telemetry["warn_mode_reject_threshold_note"] else ""
    print(
        f"  Warn-mode reject rate: {telemetry['warn_mode_reject_count']}/{telemetry['ci_rca_total']} "
        f"({telemetry['warn_mode_reject_rate']:.0%}){note}"
    )
    print(f"  Dispute-path traffic: {telemetry['dispute_count']}")
    print(f"  Bundle-upload backlog: {telemetry['bundle_upload_backlog']}")
    print(f"  why_chain_terminus_override usage: {telemetry['why_chain_terminus_override_count']}")
    print()


def _derive_ci_rca_back_validation(cache_rows: list[dict] | None) -> list[dict] | None:
    """Compute the CI-RCA Section 7 back-validation (preventive_action did not hold) gauge.

    T1.13 c12(iii): delegates to scripts.ci_rca.back_validation.find_preventive_regressions,
    which is Python-side over the already-loaded warm cache -- zero new reader egress
    (Decision 88), no new NAMED_READS verb, no Lambda redeploy. Returns None when the warm
    cache is unavailable (reader unreachable / offline).
    """
    if cache_rows is None:
        return None
    from scripts.ci_rca.back_validation import find_preventive_regressions  # noqa: PLC0415

    return find_preventive_regressions(cache_rows)


def print_ci_rca_back_validation(flags: list[dict] | None) -> None:
    """Print the CI-RCA Back-Validation (preventive_action did not hold) section (T1.13 c12(iii))."""
    print("\n--- CI-RCA Back-Validation (preventive_action did not hold) ---")
    if not flags:
        print("  (none)")
        print()
        return
    print("  [CANDIDATE] file-only match -- treat as a candidate, not a confirmed regression (Decision 55).")
    for flag in flags:
        print(f"  {flag['new_rec_id']} recurs on {flag['file']} -- prior {flag['prior_rec_id']} claimed:")
        print(f"    {flag['preventive_action_excerpt']}")
    print()


# ---------------------------------------------------------------------------
# Dedup-effectiveness SLI (WS5): promotes the fingerprint-dedup mechanism's own health to a
# monitored signal, mirroring ci_rca_probe_health's escalate() shape. This is the
# "verification-in-production" half of the dedup fix (WS1-WS3) -- a synthetic self-test
# (dedup-probe.yml) proves the mechanism CAN work; this gauge proves it IS working in
# production, so correctness never again depends on a human noticing (2026-07 incident: a
# defeated dedup guard ran the expensive agent 3x + a prior incident filed ~23 duplicate recs
# for one issue before either safeguard existed).
# ---------------------------------------------------------------------------

DEDUP_EFFECTIVENESS_THRESHOLD: float = 0.9
DEDUP_EFFECTIVENESS_MIN_SAMPLE: int = 3
_DEDUP_EFFECTIVENESS_WINDOW_DAYS = 14
_DEDUP_EFFECTIVENESS_MARKER_FILE = "scripts/ci_rca/dedup.py"


def _compute_dedup_effectiveness(
    cache_rows: list[dict] | None,
    window_days: int = _DEDUP_EFFECTIVENESS_WINDOW_DAYS,
    now: datetime | None = None,
) -> dict | None:
    """Read-time-only SLI (Decision 88; zero new reader egress): among OPEN source=ci_rca recs
    with a fingerprint, what fraction are duplicates of an earlier-filed rec sharing the same
    fingerprint (dedup should have matched/skipped them, but a duplicate rec was filed anyway).

    Groups OPEN, fingerprinted source=ci_rca recs by context_v2_json.fingerprint; within each
    group, the earliest-created row (by created_timestamp) is the canonical filing -- every
    other member is a should-have-been-deduped duplicate. effectiveness = 1 - duplicate_count /
    total_fingerprinted (1.0 when there are no fingerprinted rows yet -- no observed duplicates
    is not evidence of a working guard, just an untested one; min-sample gating in escalate()
    prevents alarming on that case).

    Returns None when the warm cache is unavailable (reader unreachable / offline).
    """
    if cache_rows is None:
        return None
    if now is None:
        now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=window_days)

    groups: dict[str, list[dict]] = {}
    total_fingerprinted = 0
    for row in cache_rows:
        if row.get("source") != "ci_rca" or row.get("status") != "open":
            continue
        ts = _common._row_ts(row)
        if ts is None or ts < cutoff:
            continue
        ctx_raw = row.get("context_v2_json") or ""
        if not ctx_raw:
            continue
        try:
            ctx = json.loads(ctx_raw)
        except (TypeError, ValueError):
            continue
        fingerprint = ctx.get("fingerprint") if isinstance(ctx, dict) else None
        if not fingerprint:
            continue
        total_fingerprinted += 1
        groups.setdefault(fingerprint, []).append(row)

    duplicate_fingerprints = 0
    duplicate_count = 0
    for rows in groups.values():
        if len(rows) > 1:
            duplicate_fingerprints += 1
            duplicate_count += len(rows) - 1

    rate = (duplicate_count / total_fingerprinted) if total_fingerprinted else 0.0
    effectiveness = 1.0 - rate
    return {
        "window_days": window_days,
        "total_fingerprinted": total_fingerprinted,
        "distinct_fingerprints": len(groups),
        "duplicate_fingerprints": duplicate_fingerprints,
        "duplicate_count": duplicate_count,
        "effectiveness": effectiveness,
    }


def print_dedup_effectiveness_gauge(gauge: dict | None) -> None:
    """Print the CI-RCA fingerprint dedup effectiveness gauge line."""
    if gauge is None:
        return
    print(
        f"CI-RCA dedup effectiveness (last {gauge['window_days']}d): "
        f"{gauge['effectiveness']:.0%} ({gauge['duplicate_count']} duplicate(s) across "
        f"{gauge['duplicate_fingerprints']}/{gauge['distinct_fingerprints']} fingerprints)"
    )


def find_open_dedup_effectiveness_rec(rows: list[dict]) -> Optional[dict]:
    """Return the first open dedup-effectiveness escalation rec from a list of recs, or None."""
    for rec in rows:
        if (
            rec.get("source") == "ci_rca"
            and rec.get("status") == "open"
            and rec.get("file") == _DEDUP_EFFECTIVENESS_MARKER_FILE
        ):
            return rec
    return None


def _build_dedup_effectiveness_context(gauge: dict) -> str:
    return (
        f"CI-RCA fingerprint dedup effectiveness degraded: {gauge['duplicate_count']} duplicate open "
        f"source=ci_rca rec(s) recurred on a fingerprint an OPEN rec already covered, across "
        f"{gauge['duplicate_fingerprints']}/{gauge['distinct_fingerprints']} distinct fingerprints in "
        f"the trailing {gauge['window_days']} days ({gauge['effectiveness']:.0%} effectiveness, below "
        f"the {DEDUP_EFFECTIVENESS_THRESHOLD:.0%} threshold). Investigate scripts.ci_rca.dedup and the "
        "fp_dedup workflow step (.github/workflows/ci-rca.yml) for a fingerprinting or lookup "
        "regression -- a prior incident filed ~23 duplicate recs for one issue before this SLI "
        "existed. This rec closes automatically once effectiveness returns above threshold."
    )


def _build_dedup_effectiveness_fields(gauge: dict) -> dict[str, Any]:
    return {
        "title": "CI-RCA fingerprint dedup effectiveness degraded -- duplicate recs recurring per fingerprint",
        "file": _DEDUP_EFFECTIVENESS_MARKER_FILE,
        "status": "open",
        "source": "ci_rca",
        "priority": "High",
        "effort": "M",
        "risk": "medium",
        "verification_tier": "V2",
        "context": _build_dedup_effectiveness_context(gauge),
        "acceptance": (
            "The dedup-effectiveness rate (1 - duplicate_count/total_fingerprinted for OPEN "
            f"source=ci_rca recs in the trailing {gauge['window_days']} days) returns at or above the "
            f"{DEDUP_EFFECTIVENESS_THRESHOLD:.0%} threshold, and this rec is closed automatically by "
            "ci_rca_gauges.escalate_dedup_effectiveness() with the recovered rate recorded as the "
            "closure proof (Decision 103/70)."
        ),
    }


def escalate_dedup_effectiveness(
    gauge: dict,
    open_recs: list[dict],
    portal_caller: Optional[Callable[[str, dict[str, Any]], Any]] = None,
    threshold: float = DEDUP_EFFECTIVENESS_THRESHOLD,
    min_sample: int = DEDUP_EFFECTIVENESS_MIN_SAMPLE,
    profile: Optional[str] = None,
) -> dict[str, Any]:
    """Idempotent escalation: file/update/close exactly one source=ci_rca dedup-effectiveness
    rec per episode -- reuses ci_rca_probe_health.escalate()'s file/update/close/none shape.

    Args:
        gauge:         Output of _compute_dedup_effectiveness.
        open_recs:     REQUIRED caller-supplied list of open recs (the warm preflight cache).
                       Never constructs a DuckLake reader (Decision 88: zero new reader egress).
        portal_caller: Injected callable(action, fields) for testability. When None, uses
                       scripts.ops_data_portal.file_rec / update_rec directly.
        threshold:     Effectiveness threshold below which escalation triggers.
        min_sample:    Minimum total_fingerprinted required before degraded can be True (avoids
                       escalating on a near-empty early sample).
        profile:       AWS profile for the portal.

    Returns:
        {"action": "file"|"update"|"close"|"none"|"skipped", "rec_id": str|None}
    """
    from scripts.ci_rca.probe_health import escalation_action  # noqa: PLC0415

    existing = find_open_dedup_effectiveness_rec(open_recs)
    open_rec_exists = existing is not None
    degraded = gauge["total_fingerprinted"] >= min_sample and gauge["effectiveness"] < threshold

    action = escalation_action(over_threshold=degraded, open_rec_exists=open_rec_exists)

    if action == "none":
        return {"action": "none", "rec_id": None}

    if action == "file":
        fields = _build_dedup_effectiveness_fields(gauge)
        if portal_caller is not None:
            rec_id = portal_caller("file", fields)
        else:
            from scripts.ops_data_portal import file_rec  # noqa: PLC0415

            rec_id = file_rec(fields, profile=profile)
        return {"action": "file", "rec_id": rec_id}

    if action == "update" and existing is not None:
        updates = {"context": _build_dedup_effectiveness_context(gauge)}
        if portal_caller is not None:
            portal_caller("update", {"id": existing["id"], **updates})
        else:
            from scripts.ops_data_portal import update_rec  # noqa: PLC0415

            update_rec(existing["id"], updates, profile=profile)
        return {"action": "update", "rec_id": existing["id"]}

    if action == "close" and existing is not None:
        updates = {
            "status": "closed",
            "resolution": (
                f"Dedup effectiveness recovered to {gauge['effectiveness']:.0%} "
                f"(>= {threshold:.0%} threshold); episode resolved."
            ),
        }
        if portal_caller is not None:
            portal_caller("close", {"id": existing["id"], **updates})
        else:
            from scripts.ops_data_portal import update_rec  # noqa: PLC0415

            update_rec(existing["id"], updates, profile=profile)
        return {"action": "close", "rec_id": existing["id"]}

    return {"action": "skipped", "rec_id": None}


def _escalate_dedup_effectiveness(
    creds_status: str,
    cache_rows: list[dict] | None,
    gauge: dict | None,
) -> dict | None:
    """Idempotently file/update/close the dedup-effectiveness rec on the warm-cache path.

    Skips (returns None) when creds are unavailable or the warm cache did not load -- degraded
    offline sessions never attempt a portal write (mirrors _escalate_ci_rca_probe_health).
    """
    if creds_status != "ok" or cache_rows is None or gauge is None:
        return None
    try:
        open_recs = [r for r in cache_rows if r.get("status") == "open"]
        return escalate_dedup_effectiveness(gauge, open_recs)
    except Exception as exc:  # noqa: BLE001
        print(f"[WARN] preflight: ci_rca_gauges.escalate_dedup_effectiveness() failed: {exc}", file=sys.stderr)
        return None
