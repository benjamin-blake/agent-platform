"""CI-RCA gauge concern for session_preflight."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone

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
