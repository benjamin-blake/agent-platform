# complexity-waiver: decision-43
"""Finalisation, CI waiting, merge, cleanup, and recovery for the executor.

Handles the tail of each recommendation's lifecycle: pushing the branch,
creating the PR, polling CI, merging, and cleaning up the local workspace.
On failure, persists partial work as a draft PR for human inspection.

This is a thin facade (Decision 102/104 SLOC decomposition): finalize() and the __main__
entrypoint stay here; every other function moved to a cohesion-seam sibling module
(postflight_gitops, postflight_fixers, postflight_gates, postflight_ciwait) and is re-exported
below, so scripts.executor.postflight remains the sole import surface for callers and tests.
"""

import json  # noqa: F401
import logging
import os
import re  # noqa: F401
import shutil  # noqa: F401
import subprocess
import sys
import time  # noqa: F401
from datetime import datetime, timezone
from typing import Optional

from scripts.execution_state import clear_checkpoint
from scripts.executor.ci_triage import triage_ci_failure  # noqa: F401
from scripts.executor.jsonl_store import _create_postmortem_recommendation, update_recommendation_status
from scripts.executor.plan import ExecutionPlan, load_prompt  # noqa: F401
from scripts.executor.postflight_ciwait import (
    _agent_merge_recovery,
    wait_for_ci,
)
from scripts.executor.postflight_fixers import (
    _fix_ci_failure,
    _fix_code_review_findings,
    _get_ci_failure_details,  # noqa: F401
)
from scripts.executor.postflight_gates import (
    _code_review_gate,
    _commits_ahead_of_main,  # noqa: F401
    _handle_failure,  # noqa: F401
    _parse_scope_files,  # noqa: F401
    _run_verifiers_gate,
    _scope_drift_check,  # noqa: F401
)
from scripts.executor.postflight_gitops import (
    _git_commit_and_push_with_retry,  # noqa: F401
    _safe_merge_origin_main,
    cleanup_after_merge,
    merge_pr,
)
from scripts.executor.telemetry import emit_process_event
from scripts.llm import model_registry  # noqa: F401
from scripts.llm.client import llm_call  # noqa: F401
from scripts.llm.utils import MODEL_EXECUTION, build_context_path, kill_process_tree  # noqa: F401

logger = logging.getLogger(__name__)


def finalize(rec_id: str, no_merge: bool = False) -> Optional[str]:
    """Push and create PR. Returns PR URL on success, None on failure.

    Always waits for CI regardless of no_merge. On CI failure, attempts automated
    fixes (up to CI_FIX_RETRIES, default 2) before giving up.
    If no_merge is False (default), squash-merges the PR after CI passes.
    If no_merge is True, stops after CI passes without merging.
    """
    try:
        logger.info("[FINALIZE] Pushing to remote...")
        # Use the actual current branch rather than deriving it from rec_id so
        # that compound runs (branch = agent/compound-{rec_id}) are handled
        # correctly alongside single-rec runs (branch = agent/{rec_id}).
        _branch_result = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        _current_branch = _branch_result.stdout.strip() if _branch_result.returncode == 0 else f"agent/{rec_id}"

        # Legacy recommendation log commits removed.
        # Persistence is now handled via the ops data portal.

        subprocess.run(
            ["git", "push", "--set-upstream", "origin", _current_branch],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

        pr_url = None
        try:
            create_r = subprocess.run(
                ["gh", "pr", "create", "--fill"],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            pr_url = create_r.stdout.strip()
        except subprocess.CalledProcessError as pr_err:
            pr_stderr = pr_err.stderr or ""
            if "already exists" in pr_stderr or "pull request for branch" in pr_stderr:
                logger.info("[FINALIZE] PR already exists for this branch — retrieving URL via fallback")
            else:
                raise

        if not pr_url:
            url_result = subprocess.run(
                ["gh", "pr", "view", "--json", "url", "-q", ".url"],
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            pr_url = url_result.stdout.strip() if url_result.returncode == 0 else None

        branch = _current_branch
        ready_r = subprocess.run(
            ["gh", "pr", "ready", branch],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if ready_r.returncode == 0:
            logger.info("[FINALIZE] PR marked ready-for-review: %s", branch)
        else:
            _ready_msg = (ready_r.stderr or ready_r.stdout).strip()[:120]
            logger.info("[FINALIZE] gh pr ready (non-critical): %s", _ready_msg)

        # Ensure the PR title matches the current rec, regardless of what a
        # previous (possibly failed or mis-targeted) run set it to.
        try:
            from scripts.executor.jsonl_store import load_recommendation as _load_rec

            _rec = _load_rec(rec_id)
            _rec_title = _rec.get("title", rec_id) if _rec else rec_id
            _expected_title = f"{rec_id}: {_rec_title}"
            _title_r = subprocess.run(
                ["gh", "pr", "view", branch, "--json", "title", "-q", ".title"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            _current_title = _title_r.stdout.strip()
            # Update if stale ([FAILED] prefix, wrong rec_id, or first time)
            _needs_update = _current_title.startswith("[FAILED]") or not _current_title.startswith(rec_id)
            if _needs_update:
                subprocess.run(
                    ["gh", "pr", "edit", branch, "--title", _expected_title],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
                logger.info("[FINALIZE] PR title set: %s", _expected_title)
        except Exception as _title_exc:  # noqa: BLE001
            logger.debug("[FINALIZE] PR title update failed (non-critical): %s", _title_exc)

        # Merge origin/main to prevent conflict-related CI failures.
        # Use a safe merge strategy that avoids silently overwriting product code.
        logger.info("[FINALIZE] Fetching and merging origin/main to avoid conflicts...")
        if _safe_merge_origin_main(branch):
            try:
                subprocess.run(
                    ["git", "push", "origin", branch],
                    check=True,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
            except subprocess.CalledProcessError as _me:
                logger.warning("[FINALIZE] push after merge failed: %s", _me)
        else:
            logger.warning("[FINALIZE] safe merge with origin/main failed")

        skip_ci = os.getenv("SKIP_CI_WAIT", "").lower() in ("1", "true", "yes")
        if skip_ci:
            logger.info("[FINALIZE] SKIP_CI_WAIT=true — skipping remote CI wait (local validate.py already passed)")
            ci_passed = True
        else:
            timeout = int(os.getenv("CI_WAIT_TIMEOUT_SECS", "600"))
            max_fix_retries = int(os.getenv("CI_FIX_RETRIES", "2"))

            ci_passed, ci_reason = wait_for_ci(branch, timeout=timeout)
            for fix_attempt in range(max_fix_retries):
                if ci_passed:
                    break
                if ci_reason in ("timeout", "checks_unavailable"):
                    break
                logger.warning(
                    "[FINALIZE] CI failed (fix attempt %d/%d): %s",
                    fix_attempt + 1,
                    max_fix_retries,
                    ci_reason,
                )
                fixed = _fix_ci_failure(rec_id, branch, ci_reason)
                if not fixed:
                    logger.error("[FINALIZE] Automated fix produced no changes, giving up")
                    break
                ci_passed, ci_reason = wait_for_ci(branch, timeout=timeout)

            # --- Code Review Gate ---
            # If CI passed, we still need to pass the code review gate if it's enabled.
            if ci_passed:
                try:
                    from scripts.executor.jsonl_store import load_recommendation as _load_rec
                    from scripts.executor.plan import ExecutionPlan

                    _rec = _load_rec(rec_id)
                    _plan = ExecutionPlan.load(rec_id)
                    _diff_r = subprocess.run(
                        ["git", "diff", "--name-only", "origin/main"],
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                    )
                    _changed = _diff_r.stdout.splitlines()
                    _effort = _rec.get("effort", "M") if _rec else "M"

                    gate_passed, _, blocking = _code_review_gate(_rec, _plan, _changed, effort=_effort)
                    if not gate_passed and blocking:
                        logger.warning("[FINALIZE] Code review gate failed with blocking findings")
                        fixed = _fix_code_review_findings(rec_id, branch, blocking)
                        if fixed:
                            # Re-poll CI after review fix
                            ci_passed, ci_reason = wait_for_ci(branch, timeout=timeout)
                        else:
                            ci_passed = False
                            ci_reason = "code_review_fix_failed"
                except Exception as gate_exc:
                    logger.warning("[FINALIZE] Code review gate error: %s", gate_exc)
            else:
                if not ci_passed and ci_reason == "failure":
                    logger.error(
                        "[FINALIZE] CI still failing after %d fix attempt(s) — creating postmortem",
                        max_fix_retries,
                    )
                    _plan = None
                    try:
                        from scripts.executor.plan import ExecutionPlan as _EP

                        _plan = _EP.load(rec_id)
                    except Exception:
                        pass

                    update_recommendation_status(
                        rec_id,
                        {
                            "status": "failed",
                            "execution_result": "ci_failed_3_times",
                            "execution_date": datetime.now(timezone.utc).isoformat(),
                            "execution_branch": branch,
                            "execution_pr_url": pr_url,
                            "execution_steps_total": len(_plan.steps) if _plan else None,
                            "failure_reason": (f"CI failed after {max_fix_retries} automated fix attempt(s)"),
                        },
                    )
                    _create_postmortem_recommendation(rec_id, branch, max_fix_retries)

            if not ci_passed:
                if ci_reason in ("timeout", "checks_unavailable"):
                    emit_process_event(
                        tier="exception",
                        category="ci_timeout",
                        severity="error",
                        description=f"CI checks unavailable or timed out: {ci_reason}",
                    )
                else:
                    emit_process_event(
                        tier="rework",
                        category="ci_failure",
                        severity="warning",
                        description=f"CI failed: {ci_reason}",
                    )
                if ci_reason == "checks_unavailable":
                    logger.error("[FINALIZE] CI checks unavailable — escalating to agent")
                    max_recovery_retries = int(os.getenv("MERGE_RECOVERY_RETRIES", "2"))
                    for attempt in range(1, max_recovery_retries + 1):
                        recovered, result_url = _agent_merge_recovery(
                            rec_id,
                            branch,
                            "gh pr checks returned a non-zero exit code every time it was polled. "
                            "No CI checks are registered on this branch. Diagnose why CI is not "
                            "triggering and fix it, then complete the merge.",
                            attempt,
                        )
                        if recovered:
                            clear_checkpoint()
                            return result_url or pr_url
                    _create_postmortem_recommendation(rec_id, branch, max_recovery_retries)
                    return None

                logger.error(
                    "[FINALIZE] CI did not pass after %d fix attempt(s): %s",
                    max_fix_retries,
                    ci_reason,
                )
                return None

        emit_process_event(
            tier="decision",
            category="ci_pass",
            severity="info",
            description="CI passed",
        )
        if no_merge:
            logger.info("[FINALIZE] --no-merge flag set, CI passed, stopping before merge: %s", pr_url)
            return pr_url

        # --- Verifier Gate ---
        if not _run_verifiers_gate(rec_id):
            logger.error("[FINALIZE] Merge blocked by programmatic verifier failure (V3 gate)")
            return None

        max_recovery_retries = int(os.getenv("MERGE_RECOVERY_RETRIES", "2"))
        merged, merge_err = merge_pr(branch)
        if merged:
            emit_process_event(
                tier="decision",
                category="merge_success",
                severity="info",
                description=f"PR merged: {pr_url or branch}",
            )
            cleanup_after_merge(branch)
            return pr_url

        # When CI is being intentionally skipped (billing-constrained environment), merge
        # failures caused by branch-protection CI requirements cannot be fixed by an agent.
        # Skip agent recovery to avoid escalating an unresolvable billing issue.
        _ci_blocked_phrases = ("required status checks", "status check", "check suite", "checks haven't")
        _merge_err_lower = (merge_err or "").lower()
        if skip_ci and any(p in _merge_err_lower for p in _ci_blocked_phrases):
            logger.error(
                "[FINALIZE] SKIP_CI_WAIT=true but merge blocked by branch-protection CI checks. "
                "Merge manually: gh pr merge %s --squash --delete-branch --admin",
                branch,
            )
            return None

        for attempt in range(1, max_recovery_retries + 1):
            _reason = (merge_err or "")[:120]
            logger.warning("[FINALIZE] Merge failed (attempt %d/%d): %s", attempt, max_recovery_retries, _reason)
            recovered, recovery_result = _agent_merge_recovery(rec_id, branch, merge_err or "", attempt)
            if recovered:
                return recovery_result or pr_url
            merge_err = recovery_result

        logger.error("[FINALIZE] Merge still failing after %d agent recovery attempt(s)", max_recovery_retries)
        emit_process_event(
            tier="exception",
            category="merge_fail",
            severity="error",
            description=f"Merge failed after {max_recovery_retries} recovery attempt(s)",
        )
        _create_postmortem_recommendation(rec_id, branch, max_recovery_retries)
        return None

    except subprocess.CalledProcessError as e:
        logger.error("[FINALIZE] Failed: %s", e)
        return None


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    parser = argparse.ArgumentParser()
    parser.add_argument("--test-verifiers", action="store_true", help="Run verifier harness and exit")
    args = parser.parse_args()

    if args.test_verifiers:
        # Pass dummy rec-id for test run
        success = _run_verifiers_gate("test-rec")
        sys.exit(0 if success else 1)
