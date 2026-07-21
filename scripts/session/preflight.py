# complexity-waiver: decision-43
#!/usr/bin/env python3
# complexity-waiver: decision-43
"""Pre-session environment and context check.

Thin CLI facade over the scripts/preflight package (T-sloc decomposition). Outputs JSON to
logs/.preflight-report.json for use by plan.prompt.md. Exits 1 on critical failure (wrong venv),
0 otherwise.

Usage:
    bin/venv-python -m scripts.session.preflight
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from scripts.preflight import (
    _common,
    alerts,
    aws_infra,
    ci_rca_gauges,
    ci_rca_signals,
    context_docs,
    correlation,
    decision_conditions,
    env_git,
    priority_queue,
    prose_context,
    recs_cache,
)

# Facade re-exports (Decision 80/104 pattern): every public function and every test-referenced
# private symbol from the pre-decomposition module, so `from scripts.session.preflight import X`
# and getattr(session_preflight, X) keep resolving. Consolidated in ONE block (tests/CLAUDE.md --
# ruff format silently drops symbols from a second block of the same module's imports).
from scripts.preflight._common import (  # noqa: F401
    _NON_AUTOMATABLE_SOFTCAP,
    _READER_SENTINEL,
    DECISIONS_FILE,
    PRIORITY_QUEUE_FILE,
    RECOMMENDATIONS_FILE,
    ROADMAP_FILE,
    ROADMAP_PLATFORM_PATH,
    ROADMAP_PRODUCT_PATH,
    ROOT,
    SESSION_LOG_FILE,
    STRATEGIC_REVIEW_LOOKBACK_DAYS,
    TERRAFORM_DIR,
    _make_reader,
    _parse_ts_utc,
    _row_ts,
    get_backend,
    read_jsonl,
    resolve_aws_profile,
)
from scripts.preflight.alerts import (  # noqa: F401
    _check_budget_bypass_alert,
    _check_forward_fix_recursion,
    _derive_budget_bypass_recent,
    _derive_forward_fix_recursion,
)
from scripts.preflight.aws_infra import (  # noqa: F401
    _handle_credentials_startup,
    _prime_reader_url,
    check_credentials,
    check_terraform_pending,
)
from scripts.preflight.ci_rca_gauges import (  # noqa: F401
    _CI_RCA_TELEMETRY_WINDOW_DAYS,
    _CI_RCA_WARN_REJECT_ALERT_THRESHOLD,
    _CI_RCA_WARN_REJECT_PROMOTION_THRESHOLD,
    DEDUP_EFFECTIVENESS_MIN_SAMPLE,
    DEDUP_EFFECTIVENESS_THRESHOLD,
    _compute_ci_rca_abstention,
    _compute_ci_rca_telemetry,
    _compute_dedup_effectiveness,
    _derive_ci_rca_back_validation,
    _escalate_ci_rca_probe_health,
    _escalate_dedup_effectiveness,
    escalate_dedup_effectiveness,
    find_open_dedup_effectiveness_rec,
    print_ci_rca_abstention_gauge,
    print_ci_rca_back_validation,
    print_ci_rca_telemetry,
    print_dedup_effectiveness_gauge,
)
from scripts.preflight.ci_rca_signals import (  # noqa: F401
    _CONVERGENCE_RCA_GAP_GRACE_MINUTES,
    _check_ci_rca_liveness,
    _check_convergence_rca_gap,
    _derive_ci_rca_closed,
    _derive_ci_rca_dispute_open,
    _derive_ci_rca_open,
    _derive_ci_rca_since,
    _derive_ci_rca_undetermined_open,
    _fetch_ci_rca_dispute_recs,
    _fetch_ci_rca_recs,
    _fetch_ci_rca_recs_since,
    _fetch_ci_rca_undetermined_recs,
    print_ci_rca_dispute_recs,
    print_ci_rca_recs,
    print_ci_rca_undetermined_recs,
)
from scripts.preflight.context_docs import (  # noqa: F401
    _check_endstate_drift,
    _scan_provisional_contracts,
    check_data_quality_coverage,
    check_telemetry_health,
    parse_last_session,
    print_telemetry_health,
    read_context_files,
)
from scripts.preflight.correlation import (  # noqa: F401
    _CI_TITLE_STOPWORDS,
    _file_paths_correlate,
    _title_jaccard,
    correlate_ci_rca_with_main,
    correlate_recs_with_commits,
    surface_queue_relevance_triage,
)
from scripts.preflight.env_git import (  # noqa: F401
    _get_recent_main_commits,
    _print_activate_hint,
    _print_recent_main_commits,
    check_main_freshness,
    check_venv,
    get_git_status,
    is_worktree,
    run_log_sync,
)
from scripts.preflight.priority_queue import (  # noqa: F401
    _read_priority_queue_cache,
    _shape_priority_queue_rows,
    print_priority_queue,
    read_priority_queue,
)
from scripts.preflight.recs_cache import (  # noqa: F401
    _check_non_automatable_softcap,
    _count_recommendations_reader,
    _derive_decisions_max_updated,
    _derive_open_recs,
    _get_latest_decision_ts,
    _tally_rec_counts,
    count_recommendations,
)
from scripts.roadmap import platform_roadmap
from scripts.roadmap import product_roadmap as product_roadmap_module
from scripts.sync.ops import _rebuild_local_cache as _sync_ops_pull  # noqa: F401  (kept for back-compat test patch targets)
from src.common.iceberg_reader import DuckDBIcebergReader as _DuckDBIcebergReader  # noqa: F401  (kept for back-compat refs)

PREFLIGHT_REPORT = _common.ROOT / "logs" / ".preflight-report.json"
TELEMETRY_ACTIVE_SESSION_FILE = _common.ROOT / "logs" / ".telemetry-active-session.json"


def main(roadmap_detail: str = "slim") -> int:
    session_start = datetime.now(timezone.utc).isoformat()

    # Telemetry health runs early so it appears in output
    telemetry_health = context_docs.check_telemetry_health()
    context_docs.print_telemetry_health(telemetry_health)

    if not os.environ.get("PYTEST_CURRENT_TEST"):
        os.environ.setdefault("S3_LOG_BUCKET", "agent-platform-data-lake")

    venv_ok = env_git.check_venv()
    if not venv_ok:
        print(f"CRITICAL: Wrong virtual environment. sys.executable={sys.executable}")
        print(f"Expected the venv at '{_common.ROOT / '.venv'}'.")
        env_git._print_activate_hint()

    # Run log sync before git_status so a successful sync clears the dirty tree
    log_sync_result = env_git.run_log_sync()

    branch, uncommitted, stash_entries = env_git.get_git_status()

    # If log sync committed and pushed, the working tree is now clean
    if log_sync_result.get("status") == "committed":
        uncommitted = False

    # Phase A: run credential check, git freshness, and terraform check concurrently.
    # creds_status and main_freshness must be resolved before Phase B starts.
    with ThreadPoolExecutor(max_workers=3) as phase_a:
        fut_creds = phase_a.submit(aws_infra.check_credentials)
        fut_freshness = phase_a.submit(env_git.check_main_freshness)
        fut_terraform = phase_a.submit(aws_infra.check_terraform_pending)
        creds_result = fut_creds.result()
        main_freshness = fut_freshness.result()
        terraform_result = fut_terraform.result()

    # check_terraform_pending now returns (bool|None, dict|None)
    if isinstance(terraform_result, tuple):
        terraform_pending, convergence_health_data = terraform_result
    else:
        terraform_pending, convergence_health_data = terraform_result, None

    creds_status = aws_infra._handle_credentials_startup(creds_result)
    s3_log_bucket_set = bool(os.environ.get("S3_LOG_BUCKET", "").strip())

    # Prime the DuckLake reader URL once so all subsequent named() calls skip SSM
    # (Decision 79 first-priority resolution). The remaining reader fan-out in Phase B
    # then hits the Lambda URL directly rather than re-resolving SSM on each call.
    aws_infra._prime_reader_url(creds_status)

    # Single warm-up sync: drain outbox then pull every migrated ops table ONCE, holding the rows
    # in-memory. This is the one serial reader touch that absorbs the Neon cold-resume before the
    # Phase B work; every Phase-B signal is then DERIVED from these rows -- ZERO additional reader
    # calls (neon-egress-reduction D4: catalog egress was self-inflicted by a ~9-10-call fan-out).
    # (The cold-resume warm-up is NOT attributable to Decision 82 -- that Decision concerns the
    # DIRECT-vs-pooled endpoint basis and the EC8 churn-gate N=8->4 frame, audit F-033; the warm
    # connection reuse / egress-budget rationale is the neon-egress-reduction Decision.)
    outbox: dict = {}
    recommendation_sync: dict = {}
    warm_rows: dict[str, list[dict] | None] = {}
    warm_reader_ok: dict[str, bool] = {}
    try:
        from scripts.sync.ops import outbox_summary  # noqa: PLC0415

        outbox = outbox_summary()
        if outbox:
            total = sum(outbox.values())
            print(f"Ops outbox: {total} pending entries ({outbox})", file=sys.stderr)
    except Exception:  # noqa: BLE001
        outbox = {}

    if creds_status == "ok":
        try:
            from scripts.sync.ops import warm_sync  # noqa: PLC0415

            warm = warm_sync()
            recommendation_sync = warm.get("pulled", {})  # type: ignore[assignment]
            warm_rows = warm.get("rows", {})  # type: ignore[assignment]
            warm_reader_ok = warm.get("reader_ok", {})  # type: ignore[assignment]
            drained = sum((warm.get("drained") or {}).values())  # type: ignore[union-attr]
            pulled = sum((warm.get("pulled") or {}).values())  # type: ignore[union-attr]
            if drained or pulled:
                print(
                    f"Ops sync: drained {drained} outbox entries, pulled {pulled} rows from the warehouse",
                    file=sys.stderr,
                )
        except Exception:  # noqa: BLE001
            pass  # sync is best-effort

    last_session = context_docs.parse_last_session()

    # Resolve the per-table warm-pull outcome. cache_rows semantics (D4): a list => serve from it;
    # None => that table's reader pull FAILED (degrade loudly); never the reader sentinel here, so
    # NO Phase-B signal re-touches the reader. creds-down also yields None (degraded read-cache).
    recs_rows_cache = warm_rows.get("ops_recommendations") if warm_reader_ok.get("ops_recommendations") else None
    pq_cache = warm_rows.get("ops_priority_queue") if warm_reader_ok.get("ops_priority_queue") else None
    dec_cache = warm_rows.get("ops_decisions") if warm_reader_ok.get("ops_decisions") else None

    # Phase B: the Neon reader fan-out is gone (D4) -- signals are derived from the warm-up rows
    # above. The executor now fans out only the independent SUBPROCESS calls (git log, gh run list)
    # plus the cheap local derivations. Cap at <=4 concurrent workers to avoid Neon connect p95
    # inflation (Decision 82). Retrieve every future via .result() so exceptions and SystemExit
    # re-raise in the main thread (Decision 55/81).
    with ThreadPoolExecutor(max_workers=4) as phase_b:
        fut_rec_count = phase_b.submit(recs_cache._count_recommendations_reader, recs_rows_cache)
        fut_ci_rca = phase_b.submit(ci_rca_signals._fetch_ci_rca_recs, recs_rows_cache)
        fut_ci_rca_dispute = phase_b.submit(ci_rca_signals._fetch_ci_rca_dispute_recs, recs_rows_cache)
        fut_ci_rca_undetermined = phase_b.submit(ci_rca_signals._fetch_ci_rca_undetermined_recs, recs_rows_cache)
        fut_pq = phase_b.submit(priority_queue.read_priority_queue, 5, creds_status, pq_cache)
        fut_commits = phase_b.submit(env_git._get_recent_main_commits)
        fut_decision_ts = phase_b.submit(recs_cache._get_latest_decision_ts, dec_cache)
        fut_ci_liveness = phase_b.submit(ci_rca_signals._check_ci_rca_liveness, creds_status, recs_rows_cache)
        fut_convergence_rca_gap = phase_b.submit(
            ci_rca_signals._check_convergence_rca_gap, convergence_health_data, recs_rows_cache
        )
        fut_forward_fix = phase_b.submit(alerts._check_forward_fix_recursion, recs_rows_cache)
        fut_budget = phase_b.submit(alerts._check_budget_bypass_alert, recs_rows_cache)

        _rec_result = fut_rec_count.result()
        ci_rca_recs = fut_ci_rca.result()
        ci_rca_dispute_recs = fut_ci_rca_dispute.result()
        ci_rca_undetermined_recs = fut_ci_rca_undetermined.result()
        priority_queue_items = fut_pq.result()
        recent_main_commits = fut_commits.result()
        latest_decision_ts = fut_decision_ts.result()
        ci_rca_liveness_alert = fut_ci_liveness.result()
        convergence_rca_gap_alert = fut_convergence_rca_gap.result()
        forward_fix_alert = fut_forward_fix.result()
        budget_bypass_alert = fut_budget.result()

    recs_read_status: str
    if _rec_result == "reader_unreachable":
        recs_read_status = "reader_unreachable"
        open_recommendations, aging_recommendations, non_automatable_count, non_automatable_details = 0, 0, 0, []
    else:
        recs_read_status = "ok"
        open_recommendations, aging_recommendations, non_automatable_count, non_automatable_details = _rec_result  # type: ignore[misc]

    closed_ci_rca_recs = ci_rca_signals._derive_ci_rca_closed(recs_rows_cache) if recs_rows_cache is not None else None
    ci_rca_correlation = correlation.correlate_ci_rca_with_main(
        ci_rca_recs, recent_main_commits, closed_ci_rca_recs=closed_ci_rca_recs
    )
    ci_rca_signals.print_ci_rca_recs(ci_rca_recs, correlation=ci_rca_correlation)
    ci_rca_signals.print_ci_rca_dispute_recs(ci_rca_dispute_recs)
    ci_rca_signals.print_ci_rca_undetermined_recs(ci_rca_undetermined_recs)

    ci_rca_abstention_gauge = ci_rca_gauges._compute_ci_rca_abstention(recs_rows_cache)
    ci_rca_probe_health_escalation = ci_rca_gauges._escalate_ci_rca_probe_health(
        creds_status, recs_rows_cache, ci_rca_abstention_gauge
    )
    ci_rca_gauges.print_ci_rca_abstention_gauge(ci_rca_abstention_gauge)

    ci_rca_telemetry = ci_rca_gauges._compute_ci_rca_telemetry(recs_rows_cache)
    ci_rca_back_validation = ci_rca_gauges._derive_ci_rca_back_validation(recs_rows_cache)
    ci_rca_gauges.print_ci_rca_telemetry(ci_rca_telemetry)
    ci_rca_gauges.print_ci_rca_back_validation(ci_rca_back_validation)

    dedup_effectiveness_gauge = ci_rca_gauges._compute_dedup_effectiveness(recs_rows_cache)
    dedup_effectiveness_escalation = ci_rca_gauges._escalate_dedup_effectiveness(
        creds_status, recs_rows_cache, dedup_effectiveness_gauge
    )
    ci_rca_gauges.print_dedup_effectiveness_gauge(dedup_effectiveness_gauge)

    priority_queue.print_priority_queue(priority_queue_items)
    env_git._print_recent_main_commits(recent_main_commits)

    # Scan provisional contracts inline (reads only local docs/contracts/ -- no creds, no ThreadPoolExecutor).
    # The default per-contract provider computes a deterministic days-since-first-production-invocation
    # metric from each contract's provisional_v0 date; production_invocations stays dormant (T2.36).
    provisional_contracts_due = context_docs._scan_provisional_contracts()

    print("\n--- Provisional contracts due ---")
    if provisional_contracts_due:
        for contract_id in provisional_contracts_due:
            print(f"  {contract_id}: re_ratification_trigger fired -- ratification review required")
    else:
        print("  (none)")
    print()

    # Reversal-conditions monitor (audit SEQ-02, Decision 133 follow-on): reads local
    # DECISIONS.md/DECISIONS_ARCHIVE.md only (no creds needed). Resilient -- never raises;
    # a malformed stanza surfaces loudly in the bucket without crashing preflight.
    decision_conditions_bucket = decision_conditions.preflight_bucket()
    decision_conditions.print_decision_conditions(decision_conditions_bucket)

    # Dedupe open_recs: count already computed in Phase B; pass to read_context_files
    # to skip the second open_recs verb call (Decision 84 I-3: closed named-verb boundary).
    open_recs_count = open_recommendations if recs_read_status == "ok" else None
    context = context_docs.read_context_files(open_recs_count=open_recs_count)

    # Dedupe decisions_max_updated: timestamp fetched once in Phase B; reuse for both
    # roadmap compute_state_dict calls rather than re-issuing the verb.
    platform_roadmap_state = platform_roadmap.compute_state_dict(
        _common.ROADMAP_PLATFORM_PATH, latest_decision_ts=latest_decision_ts
    )
    product_roadmap_state = product_roadmap_module.compute_state_dict(
        _common.ROADMAP_PRODUCT_PATH,
        platform_yaml_path=_common.ROADMAP_PLATFORM_PATH,
        latest_decision_ts=latest_decision_ts,
    )

    report: dict = {
        "venv_ok": venv_ok,
        "branch": branch,
        "uncommitted_changes": uncommitted,
        "stash_entries": stash_entries,
        "main_freshness": main_freshness,
        "creds_status": creds_status,
        "s3_log_bucket_set": s3_log_bucket_set,
        "ops_outbox": outbox,
        "terraform_pending": terraform_pending,
        "convergence_health": convergence_health_data,
        "last_session": last_session,
        "open_recommendations": open_recommendations,
        "aging_recommendations": aging_recommendations,
        "non_automatable_recommendations": non_automatable_count,
        "priority_queue": priority_queue_items,
        "priority_queue_source": "ducklake_reader" if creds_status == "ok" else "cache",
        "recs_read_status": recs_read_status,
        "ci_rca_recs": ci_rca_recs,
        "ci_rca_unresolved_recs": ci_rca_correlation.get("unresolved") or [],
        "ci_rca_likely_resolved_recs": ci_rca_correlation.get("likely_resolved") or [],
        "ci_rca_dispute_recs": ci_rca_dispute_recs,
        "ci_rca_undetermined_recs": ci_rca_undetermined_recs[:5],
        "ci_rca_undetermined_total": len(ci_rca_undetermined_recs),
        "ci_rca_abstention_gauge": ci_rca_abstention_gauge,
        "ci_rca_probe_health_escalation": ci_rca_probe_health_escalation,
        "ci_rca_telemetry": ci_rca_telemetry,
        "ci_rca_back_validation": ci_rca_back_validation,
        "dedup_effectiveness_gauge": dedup_effectiveness_gauge,
        "dedup_effectiveness_escalation": dedup_effectiveness_escalation,
        "recent_main_commits": recent_main_commits,
        "friction_patterns": telemetry_health.get("friction_patterns", []),
        "log_sync_result": log_sync_result,
        "recommendation_sync": recommendation_sync,
        "telemetry_health": telemetry_health,
        "data_quality": context_docs.check_data_quality_coverage(),
        "context": context,
        "platform_roadmap": _slim_roadmap_state(platform_roadmap_state, full=(roadmap_detail == "full")),
        "product_roadmap": _slim_roadmap_state(product_roadmap_state),
        "session_start": session_start,
    }

    report["provisional_contracts_due"] = provisional_contracts_due
    report["decision_conditions"] = decision_conditions_bucket
    report["non_automatable_softcap_breached"] = recs_cache._check_non_automatable_softcap(non_automatable_count)
    report["ci_rca_liveness_alert"] = ci_rca_liveness_alert
    report["convergence_rca_gap_alert"] = convergence_rca_gap_alert
    if convergence_rca_gap_alert is not None:
        print(
            f"Convergence RCA gap alert: record red {convergence_rca_gap_alert['red_age_hours']}h "
            f"(commit {convergence_rca_gap_alert.get('commit_sha', '')[:8]}) with no matching ci_rca rec filed "
            "since the red episode began -- file one manually or dispatch ci-rca.yml.",
            file=sys.stderr,
        )
    report["forward_fix_recursion_alert"] = forward_fix_alert
    report["budget_bypass_alert"] = budget_bypass_alert
    if budget_bypass_alert is not None:
        print(
            f"Budget bypass alert: {budget_bypass_alert['count']} --ignore-budget invocations in the last 7 days."
            " Repeated bypass indicates fast-tier drift -- consider a planning session to revisit the budget.",
            file=sys.stderr,
        )

    endstate_drift = context_docs._check_endstate_drift()
    report["endstate_drift"] = endstate_drift
    if endstate_drift.get("stale"):
        new_ids = endstate_drift.get("new_ids") or []
        ids_note = f" (new ids: {new_ids})" if new_ids else ""
        _msg = f"Advisory: Platform End-State fingerprint stale -- roadmap has new tier_item IDs since the stamp.{ids_note}"
        print(_msg, file=sys.stderr)

    # Fail-open prose-context advisory (Decision 110/62/59); never affects the exit code below.
    report["prose_context"] = prose_context.measure_prose_context()
    prose_context.print_prose_context_report(report["prose_context"])

    # Ensure logs/ directory exists
    PREFLIGHT_REPORT.parent.mkdir(parents=True, exist_ok=True)
    PREFLIGHT_REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(_format_preflight_summary(report, PREFLIGHT_REPORT))

    return 0 if venv_ok else 1


def _slim_roadmap_state(state: dict, full: bool = False) -> dict:
    """Return actionable roadmap subsets for session workflows.

    slim (full=False, default -- used by /plan): next_eligible + strategic_pending only.
    Keeps the planning agent's payload lean; blocked_on_cd and gate_evaluations are absent.

    full (full=True -- used by /orient): entire computed state including in_progress, blocked,
    active_tier, blocked_on_cd, ratifiable_cds, and gate_evaluations. Uses .get() defaults so
    product_roadmap (no candidate_decisions / cross_tier_gates) is unaffected (Decision 93).
    """
    if full:
        return {
            "next_eligible": state.get("next_eligible", []),
            "strategic_pending": state.get("strategic_pending", []),
            "in_progress": state.get("in_progress", []),
            "blocked": state.get("blocked", []),
            "active_tier": state.get("active_tier"),
            "blocked_on_cd": state.get("blocked_on_cd", []),
            "ratifiable_cds": state.get("ratifiable_cds", []),
            "realized_but_pending_cds": state.get("realized_but_pending_cds", []),
            "gate_evaluations": state.get("gate_evaluations", []),
        }
    return {
        "next_eligible": state.get("next_eligible", []),
        "strategic_pending": state.get("strategic_pending", []),
    }


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
    return (
        f"Preflight OK -> {report_path}\n"
        f"  venv={report.get('venv_ok')} creds={report.get('creds_status')} "
        f"branch={report.get('branch')} main=({behind} behind, {ahead} ahead)\n"
        f"  open_recs={report.get('open_recommendations')} "
        f"non_automatable={report.get('non_automatable_recommendations')} "
        f"{ci_rca_summary}{recs_status_suffix}{convergence_rca_gap_suffix}\n"
        f"  Read the report file for full constraint detail."
    )


def open_telemetry_session(workflow: str, branch: str) -> str:
    """Open a telemetry session and record state to the active-session file.

    Writes ``logs/.telemetry-active-session.json`` containing the session_id,
    workflow, branch, and started_at timestamp.  Returns the session_id UUID.

    On any error the function logs a warning and returns a generated UUID so
    that callers can still proceed; the telemetry record will simply be partial.
    """
    try:
        from scripts.executor.telemetry import open_session  # noqa: PLC0415

        session_id = open_session(workflow=workflow, branch=branch, model_primary="manual")
    except Exception as exc:  # noqa: BLE001
        import uuid  # noqa: PLC0415

        session_id = str(uuid.uuid4())
        print(f"WARNING: telemetry.open_session failed ({exc}); using local UUID", file=sys.stderr)

    state = {
        "session_id": session_id,
        "workflow": workflow,
        "branch": branch,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    TELEMETRY_ACTIVE_SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    TELEMETRY_ACTIVE_SESSION_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return session_id


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Pre-session environment and context check",
    )
    parser.add_argument(
        "--health",
        action="store_true",
        help=("Run only the telemetry health check. Exits non-zero on critical threshold."),
    )
    parser.add_argument(
        "--open-session",
        action="store_true",
        dest="open_session",
        help="Open a telemetry session and write state to logs/.telemetry-active-session.json",
    )
    parser.add_argument(
        "--workflow",
        default="manual",
        help="Workflow name for telemetry (used with --open-session)",
    )
    parser.add_argument(
        "--branch",
        default="",
        help="Branch name for telemetry (used with --open-session; defaults to current git branch)",
    )
    parser.add_argument(
        "--roadmap-detail",
        choices=["slim", "full"],
        default="slim",
        dest="roadmap_detail",
        help=(
            "Roadmap projection depth written to platform_roadmap in the preflight report. "
            "'slim' (default, used by /plan): next_eligible + strategic_pending only. "
            "'full' (used by /orient): adds in_progress, blocked, active_tier, blocked_on_cd, gate_evaluations."
        ),
    )
    args = parser.parse_args()

    if args.health:
        health = context_docs.check_telemetry_health()
        context_docs.print_telemetry_health(health)
        sys.exit(1 if health["overall"] == "critical" else 0)

    if args.open_session:
        branch = args.branch
        if not branch:
            result = subprocess.run(
                ["git", "branch", "--show-current"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=_common.ROOT,
            )
            branch = result.stdout.strip() if result.returncode == 0 else "unknown"
        sid = open_telemetry_session(workflow=args.workflow, branch=branch)
        print(sid)
        sys.exit(0)

    sys.exit(main(roadmap_detail=args.roadmap_detail))
