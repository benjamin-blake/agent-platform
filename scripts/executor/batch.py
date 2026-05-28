# complexity-waiver: decision-43
"""Batch and compound orchestration for the recommendation executor.

Extracted from scripts/execute_recommendation.py (Strangler Fig pattern).
All functions remain importable from the original module via re-exports.
"""

from __future__ import annotations

import graphlib
import json
import logging
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EFFORT_WEIGHTS: dict[str, float] = {"XS": 0.5, "S": 1.0, "M": 2.0, "L": 4.0, "XL": 8.0}
EFFORT_ORDER: dict[str, int] = {"XS": 0, "S": 1, "M": 2, "L": 3, "XL": 4}
PRIORITY_ORDER: dict[str, int] = {
    "Critical": 0,
    "High": 1,
    "Medium": 2,
    "Low": 3,
}
MAX_BATCH_EFFORT: float = 2.0  # equivalent to M
MAX_BATCH_SIZE: int = 4
DEFAULT_NEXT_BATCH_LIMIT: int = 3


# ---------------------------------------------------------------------------
# Batch selection
# ---------------------------------------------------------------------------


def select_compound_batch(recs: list[dict]) -> list[dict]:
    """Select recs for compound execution (total effort <= M, max 4 recs).

    Prefers recs with lower effort to maximise batch size.
    Prefer same-file recs to reduce merge conflicts (sort by primary file secondarily).
    """
    eligible = [r for r in recs if r.get("automatable", True) and r.get("status", "open") == "open"]
    eligible.sort(
        key=lambda r: (
            EFFORT_WEIGHTS.get(r.get("effort", "M"), 2.0),
            r.get("file", ""),
        )
    )

    batch: list[dict] = []
    total_effort = 0.0
    for rec in eligible:
        effort = EFFORT_WEIGHTS.get(rec.get("effort", "M"), 2.0)
        if total_effort + effort <= MAX_BATCH_EFFORT and len(batch) < MAX_BATCH_SIZE:
            batch.append(rec)
            total_effort += effort
        if total_effort >= MAX_BATCH_EFFORT or len(batch) >= MAX_BATCH_SIZE:
            break
    return batch


def get_eligible_recs() -> list[dict]:
    """Return all eligible recommendations in their JSONL order."""
    from scripts.execute_recommendation import is_eligible  # noqa: PLC0415
    from scripts.executor.jsonl_store import load_all_recommendations  # noqa: PLC0415

    recs_by_id = load_all_recommendations()
    return [rec for rec in recs_by_id.values() if is_eligible(rec, recs_by_id)]


def select_next_batch(
    limit: int = DEFAULT_NEXT_BATCH_LIMIT,
) -> dict:
    """Select the next batch of recs for the supervisor prompt.

    Applies the standard eligibility filter (status open, automatable,
    risk low, dependencies closed) then sorts by priority (Critical
    first) and effort (XS first).  Recs that are open but blocked by
    unclosed dependencies appear in the ``skipped`` list with a reason.

    Args:
        limit: Maximum number of recommended rec IDs to return.

    Returns:
        ``{"recommended": [...ids], "skipped": [...{id, reason}]}``
    """
    from scripts.executor.jsonl_store import load_all_recommendations  # noqa: PLC0415

    recs_by_id = load_all_recommendations()

    recommended: list[dict] = []
    skipped: list[dict] = []

    for rec in recs_by_id.values():
        if rec.get("status") != "open":
            continue
        if not rec.get("automatable", False):
            continue
        if rec.get("risk") != "low":
            continue

        # Check dependency blocking
        deps: list[str] = rec.get("dependencies", [])
        blocked_by: list[str] = []
        for dep_id in deps:
            dep = recs_by_id.get(dep_id)
            if dep is None or dep.get("status") != "closed":
                blocked_by.append(dep_id)

        if blocked_by:
            skipped.append(
                {
                    "id": rec["id"],
                    "reason": ("blocked by unclosed dependencies: " + ", ".join(blocked_by)),
                }
            )
            continue

        recommended.append(rec)

    # Sort: priority ascending (Critical=0), then effort ascending
    recommended.sort(
        key=lambda r: (
            PRIORITY_ORDER.get(r.get("priority", "Medium"), 2),
            EFFORT_ORDER.get(r.get("effort", "M"), 2),
        )
    )

    rec_ids = [r["id"] for r in recommended[:limit]]
    return {"recommended": rec_ids, "skipped": skipped}


def topological_sort_recs(recs: list[dict]) -> list[dict]:
    """Sort recommendations in dependency order using graphlib.TopologicalSorter.

    Returns empty list on cycle.
    """
    rec_ids = {rec["id"] for rec in recs}
    rec_by_id = {rec["id"]: rec for rec in recs}

    graph: dict[str, set[str]] = {rec["id"]: set() for rec in recs}
    for rec in recs:
        for dep_id in rec.get("dependencies", []):
            if dep_id in rec_ids:
                graph[rec["id"]].add(dep_id)

    try:
        sorter = graphlib.TopologicalSorter(graph)
        order = list(sorter.static_order())
        return [rec_by_id[rid] for rid in order if rid in rec_by_id]
    except graphlib.CycleError as e:
        logger.error("[BATCH] Dependency cycle detected: %s", e)
        return []


# ---------------------------------------------------------------------------
# Batch execution
# ---------------------------------------------------------------------------


def execute_batch(
    no_merge: bool = False,
    max_recs: int = 10,
    restart: bool = False,
) -> dict:
    """Process eligible recommendations in dependency order.

    Returns:
        Summary dict: {attempted, succeeded, failed, skipped}
    """
    from scripts.execute_recommendation import execute_recommendation  # noqa: PLC0415

    attempted = 0
    succeeded = 0
    failed = 0
    processed_ids: set[str] = set()

    print("\n" + "=" * 60)
    print("BATCH MODE")
    print("=" * 60)

    while attempted < max_recs:
        eligible = get_eligible_recs()
        eligible = [r for r in eligible if r["id"] not in processed_ids]

        if not eligible:
            print("[BATCH] No more eligible recommendations")
            break

        sorted_recs = topological_sort_recs(eligible)
        if not sorted_recs:
            print("[BATCH] No recs after topological sort (possible cycle or empty)")
            break

        rec = sorted_recs[0]
        rec_id = rec["id"]
        processed_ids.add(rec_id)
        attempted += 1

        print(f"\n[BATCH] Processing {rec_id}: {rec.get('title', '(no title)')} ({attempted}/{max_recs})")

        success = execute_recommendation(rec_id, no_merge=no_merge, restart=restart)
        if success:
            succeeded += 1
            print(f"[BATCH] {rec_id}: SUCCESS")
        else:
            failed += 1
            print(f"[BATCH] {rec_id}: FAILED -- continuing to next eligible rec")

        try:
            from scripts.sync_ops import drain as drain_outbox  # noqa: PLC0415

            drain_outbox()
        except Exception:  # noqa: BLE001
            pass  # drain is best-effort; full sync runs at preflight/postflight only

    final_eligible = get_eligible_recs()
    skipped = max(0, len([r for r in final_eligible if r["id"] not in processed_ids]))
    summary = {
        "attempted": attempted,
        "succeeded": succeeded,
        "failed": failed,
        "skipped": skipped,
    }

    print("\n" + "=" * 60)
    print(f"BATCH SUMMARY: {attempted} attempted / {succeeded} succeeded / {failed} failed / {summary['skipped']} skipped")
    print("=" * 60)
    return summary


# ---------------------------------------------------------------------------
# Compound recommendation execution
# ---------------------------------------------------------------------------


def load_cluster(cluster_id: str) -> list[str]:
    """Read cluster rec_ids from logs/.rec-curator-findings.jsonl.

    Args:
        cluster_id: The cluster ID to look up (e.g., 'cluster-001')

    Returns:
        List of rec IDs in the cluster, or empty list if not found.
    """
    findings_path = Path("logs") / ".rec-curator-findings.jsonl"
    rec_ids: list[str] = []

    if not findings_path.exists():
        return rec_ids

    try:
        with open(findings_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    finding = json.loads(line)
                    if finding.get("type") == "cluster" and finding.get("cluster_id") == cluster_id:
                        rec_ids = finding.get("rec_ids", [])
                        return rec_ids
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        logger.warning("Error reading cluster %s: %s", cluster_id, e)

    return rec_ids


def _ensure_compound_branch(branch_name: str) -> bool:
    """Create a compound branch from main. Returns True if ready."""
    from scripts.execute_recommendation import _check_jsonl_clean  # noqa: PLC0415

    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        current = result.stdout.strip()

        if current == branch_name:
            logger.info("[COMPOUND] Already on compound branch %s", branch_name)
            return True

        if current != "main":
            logger.error(
                "[COMPOUND] Expected to be on main, but on %s",
                current,
            )
            return False

        if not _check_jsonl_clean():
            print("ERROR: Recommendations JSONL has uncommitted changes -- commit or stash before branching")
            return False

        subprocess.run(
            ["git", "fetch", "origin", "main"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        try:
            subprocess.run(
                ["git", "checkout", "-b", branch_name],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except subprocess.CalledProcessError as e:
            if e.returncode == 128:
                subprocess.run(
                    ["git", "checkout", branch_name],
                    check=True,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
            else:
                raise
        return True
    except subprocess.CalledProcessError as e:
        logger.error("[COMPOUND] Git operation failed: %s", e)
        return False


def execute_compound(
    rec_ids: list[str],
    cluster_id: str | None = None,
    no_merge: bool = False,
    no_review: bool = False,
    restart: bool = False,
    skip_critique: bool = False,
) -> dict:
    """Execute multiple recommendations in a single compound branch.

    Creates one branch (agent/compound-{first_rec} or agent/cluster-{cluster_id}),
    generates and implements plans for each rec sequentially, runs validation once,
    creates one PR, and updates all rec statuses.

    Returns:
        Summary dict: {attempted, succeeded, failed, pr_url}
    """
    from scripts.execute_recommendation import (  # noqa: PLC0415
        _discard_commit_range_files,
    )
    from scripts.executor.jsonl_store import (  # noqa: PLC0415
        load_recommendation,
        update_recommendation_status,
    )
    from scripts.executor.plan import (  # noqa: PLC0415
        ExecutionPlan,
        _detect_critique_cycling,
        critique_plan,
        generate_initial_plan,
        refine_plan,
        save_plan,
    )
    from scripts.executor.postflight import (  # noqa: PLC0415
        _code_review_gate,
        _fix_code_review_findings,
        finalize,
    )
    from scripts.executor.step_runner import (  # noqa: PLC0415
        StepOutcome,
        _append_step_telemetry,
        commit_step,
        get_implementation_model,
        implement_step,
    )
    from scripts.llm_utils import LLMResponseError  # noqa: PLC0415

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if not rec_ids:
        return {"attempted": 0, "succeeded": 0, "failed": 0, "pr_url": None}

    # Determine branch name
    if cluster_id:
        branch_name = f"agent/cluster-{cluster_id}"
    else:
        branch_name = f"agent/compound-{rec_ids[0]}"

    attempted = 0
    succeeded = 0
    failed_recs: list[str] = []

    print("\n" + "=" * 60)
    label = f"COMPOUND EXECUTION: {cluster_id}" if cluster_id else "COMPOUND EXECUTION"
    print(label)
    print("=" * 60)
    print(f"Branch: {branch_name}")
    print(f"Processing {len(rec_ids)} recommendation(s)")

    if not _ensure_compound_branch(branch_name):
        print("ERROR: Failed to set up compound branch")
        return {
            "attempted": 0,
            "succeeded": 0,
            "failed": len(rec_ids),
            "pr_url": None,
        }

    for rec_id in rec_ids:
        attempted += 1
        print(f"\n--- Compound rec {attempted}/{len(rec_ids)}: {rec_id} ---")

        rec = load_recommendation(rec_id)
        if not rec:
            print(f"ERROR: Recommendation {rec_id} not found")
            failed_recs.append(rec_id)
            continue

        # Generate plan
        try:
            plan = generate_initial_plan(rec)
            if getattr(plan, "status", "") != "no_changes_needed":
                save_plan(plan)

            # Critique loop
            if skip_critique or plan.status == "no_changes_needed":
                print("[SKIP] Critique loop skipped")
                was_no_op = plan.status == "no_changes_needed"
                plan.status = "approved"
                if not was_no_op:
                    save_plan(plan)
            else:
                max_revisions = int(os.getenv("PLAN_MAX_REVISIONS", "3"))
                for iteration in range(max_revisions):
                    print(f"\n--- Critique iteration {iteration + 1}/{max_revisions} ---")

                    critique = critique_plan(plan)
                    plan.critique_history.append(critique)

                    if critique["verdict"] == "approved":
                        print("Plan APPROVED")
                        plan.status = "approved"
                        if getattr(plan, "status", "") != "no_changes_needed":
                            save_plan(plan)
                        break

                    print("Plan needs revision. Suggestions:")
                    for s in critique.get("suggestions", [])[:5]:
                        print(f"  - {s[:80]}")

                    if _detect_critique_cycling(plan.critique_history):
                        msg = "[CRITIQUE-CYCLING] Cycling detected -- auto-approving plan to break loop"
                        print(msg)
                        plan.status = "approved"
                        if getattr(plan, "status", "") != "no_changes_needed":
                            save_plan(plan)
                        break

                    if iteration < max_revisions - 1:
                        plan = refine_plan(plan, critique, rec)
                else:
                    raise LLMResponseError(
                        f"Plan still needs revision after {max_revisions} critique "
                        f"iteration(s). Increase PLAN_MAX_REVISIONS or use "
                        f"--skip-critique to override."
                    )
        except LLMResponseError as exc:
            logger.error("[COMPOUND] Plan critique exhausted for %s: %s", rec_id, exc)
            failed_recs.append(rec_id)
            continue
        except Exception as exc:
            logger.error("[COMPOUND] Plan failed for %s: %s", rec_id, exc)
            failed_recs.append(rec_id)
            continue

        # Implement steps
        all_steps_ok = True
        committed_steps_for_rec = 0
        for i, step in enumerate(plan.steps, 1):
            step_ok, step_reqs, impl_hash, _ = implement_step(
                step,
                rec_id,
                i,
                len(plan.steps),
                recommendation_target_file=rec.get("file", ""),
                effort=rec.get("effort", ""),
            )
            if step_ok != StepOutcome.SUCCESS:
                if step_ok == StepOutcome.ACCEPTANCE_FAILED:
                    logger.error(
                        "[COMPOUND] Step %d acceptance check FAILED for %s",
                        i,
                        rec_id,
                    )
                else:
                    logger.error("[COMPOUND] Step %d failed for %s", i, rec_id)
                # Revert file changes if step failed
                step_file = step.get("file", "")
                if step_file:
                    try:
                        subprocess.run(
                            ["git", "checkout", "--", step_file],
                            check=False,
                            capture_output=True,
                            text=True,
                            encoding="utf-8",
                            errors="replace",
                        )
                        if step.get("action") == "create":
                            Path(step_file).unlink(missing_ok=True)
                    except Exception as e:
                        logger.warning(
                            "[COMPOUND] Failed to revert %s: %s",
                            step_file,
                            e,
                        )
                # Reset all commits made for this recommendation
                if committed_steps_for_rec > 0:
                    try:
                        subprocess.run(
                            ["git", "reset", f"HEAD~{committed_steps_for_rec}"],
                            check=True,
                            capture_output=True,
                            text=True,
                            encoding="utf-8",
                            errors="replace",
                        )
                        logger.info(
                            "[COMPOUND] Reset %d commit(s) for failed %s",
                            committed_steps_for_rec,
                            rec_id,
                        )
                        _discard_commit_range_files(committed_steps_for_rec)
                    except Exception as e:
                        logger.warning(
                            "[COMPOUND] Failed to reset %d commit(s): %s",
                            committed_steps_for_rec,
                            e,
                        )
                failed_recs.append(rec_id)
                all_steps_ok = False
                break

            commit_ok, diff_stat = commit_step(step, rec_id, i)
            if commit_ok:
                committed_steps_for_rec += 1
            _append_step_telemetry(
                rec_id=rec_id,
                step_n=i,
                total_steps=len(plan.steps),
                prompt_hash=impl_hash,
                diff_stat=diff_stat,
                model=get_implementation_model(rec.get("effort", "")),
            )

        if all_steps_ok:
            succeeded += 1
            print(f"[COMPOUND] {rec_id}: OK")

    successful_rec_ids = [rec_id for rec_id in rec_ids if rec_id not in failed_recs]
    review_gate_failed = False
    review_failure_reason: str | None = None

    # Batch-level code review gate
    review_skip = no_review or os.getenv("SKIP_CODE_REVIEW", "false").lower() in ("true", "1")
    if not review_skip and succeeded > 0:
        try:
            changed_result = subprocess.run(
                ["git", "diff", "origin/main", "--name-only"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
            changed_files = [p for p in changed_result.stdout.splitlines() if p.strip()]
        except Exception:
            changed_files = []
        # Create compound rec metadata combining all successful recs
        compound_rec = {
            "id": f"compound-batch-{len(rec_ids)}",
            "title": f"Batch execution: {', '.join(successful_rec_ids)}",
            "status": "closed",
            "file": "",
        }

        max_review_retries = int(os.getenv("REVIEW_FIX_RETRIES", "2"))
        batch_plan = ExecutionPlan(
            rec_id="compound-batch",
            slug="batch",
            revision=1,
            timestamp=datetime.now(timezone.utc).isoformat(),
            status="approved",
            model="batch-review",
            tokens_used=None,
            steps=[],
            plan_text=f"Batch review: {', '.join(successful_rec_ids)}",
        )
        review_passed, review_cost, blocking = _code_review_gate(compound_rec, batch_plan, changed_files, effort="")
        for review_attempt in range(max_review_retries):
            if not blocking:
                break
            logger.warning(
                "[COMPOUND-REVIEW] %d finding(s) (attempt %d/%d) -- requesting fix...",
                len(blocking),
                review_attempt + 1,
                max_review_retries,
            )
            fixed = _fix_code_review_findings(successful_rec_ids[0], blocking)
            if not fixed:
                break
            review_passed, review_cost, blocking = _code_review_gate(compound_rec, batch_plan, changed_files, effort="")
        if blocking:
            review_gate_failed = True
            review_failure_reason = (
                "compound code review gate failed: "
                f"{len(blocking)} blocking finding(s) remain after "
                f"{max_review_retries} retry attempt(s)"
            )
            logger.error("[COMPOUND-REVIEW] %s", review_failure_reason)
        else:
            logger.info("[COMPOUND-REVIEW] No CRITICAL/HIGH findings remaining")
    elif review_skip:
        logger.info("[COMPOUND-REVIEW] Code review skipped (SKIP_CODE_REVIEW or no_review)")
    elif succeeded == 0:
        logger.info("[COMPOUND-REVIEW] No successful recs -- code review skipped")

    # Finalize: push and create one PR
    pr_url: str | None = None
    if succeeded > 0 and not review_gate_failed:
        pr_url = finalize(rec_ids[0], no_merge=no_merge)
    elif review_gate_failed:
        logger.error("[COMPOUND] Finalize skipped due to unresolved blocking code-review findings")

    # Update statuses
    if review_gate_failed and review_failure_reason:
        for rec_id in successful_rec_ids:
            if rec_id in failed_recs:
                continue
            update_recommendation_status(
                rec_id,
                {
                    "status": "failed",
                    "execution_result": "failure",
                    "execution_date": datetime.now(timezone.utc).isoformat(),
                    "execution_branch": branch_name,
                    "failure_step": None,
                    "failure_reason": review_failure_reason,
                    "execution_steps_attempted": succeeded,
                    "execution_steps_total": attempted,
                },
            )
            failed_recs.append(rec_id)
        succeeded = 0
    else:
        for rec_id in rec_ids:
            if rec_id not in failed_recs:
                update_recommendation_status(
                    rec_id,
                    {
                        "status": "closed",
                        "execution_result": "compound",
                        "execution_date": datetime.now(timezone.utc).isoformat(),
                        "execution_branch": branch_name,
                        "execution_pr_url": pr_url or "",
                    },
                )

    summary = {
        "attempted": attempted,
        "succeeded": succeeded,
        "failed": len(failed_recs),
        "pr_url": pr_url,
    }

    print("\n" + "=" * 60)
    _s = f"{attempted} attempted / {succeeded} succeeded / {len(failed_recs)} failed"
    print(f"COMPOUND SUMMARY: {_s}")
    print("=" * 60)
    return summary
