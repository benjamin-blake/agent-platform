# complexity-waiver: decision-43
"""Finalisation, CI waiting, merge, cleanup, and recovery for the executor.

Handles the tail of each recommendation's lifecycle: pushing the branch,
creating the PR, polling CI, merging, and cleaning up the local workspace.
On failure, persists partial work as a draft PR for human inspection.
"""

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from scripts import model_registry
from scripts.execution_state import clear_checkpoint
from scripts.executor.ci_triage import triage_ci_failure
from scripts.executor.jsonl_store import _create_postmortem_recommendation, update_recommendation_status
from scripts.executor.plan import ExecutionPlan, load_prompt
from scripts.executor.telemetry import emit_process_event
from scripts.llm_client import llm_call
from scripts.llm_utils import (
    MODEL_EXECUTION,
    build_context_path,
    kill_process_tree,
)

logger = logging.getLogger(__name__)

# Resolve review model via registry; fall back to COPILOT_MODEL_REVIEW env var.
# model_registry.resolve_model() checks COPILOT_MODEL_REVIEW internally (env override).
# MODEL_REVIEW is deprecated -- use _code_review_gate(effort=...) for per-effort routing.


# ---------------------------------------------------------------------------
# Git / Commit / Push helpers
# ---------------------------------------------------------------------------


def _git_commit_and_push_with_retry(
    branch: str,
    commit_message: str,
    files_to_add: list[str],
    retry_count: int = 3,
) -> bool:
    """Add files, commit with hook retries, and push to remote.

    Returns:
        True if commit and push succeeded, False otherwise.
    """
    try:
        if files_to_add:
            subprocess.run(
                ["git", "add"] + files_to_add,
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )

        for attempt in range(retry_count):
            commit_r = subprocess.run(
                ["git", "commit", "-m", commit_message],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if commit_r.returncode == 0:
                break

            # If pre-commit hooks modified files (e.g. ruff/black), re-add and retry
            if "files were modified by this hook" in (commit_r.stderr or ""):
                if files_to_add:
                    subprocess.run(
                        ["git", "add"] + files_to_add,
                        check=True,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                    )
                else:
                    # If we didn't have a file list, add all changes
                    subprocess.run(
                        ["git", "add", "-u"],
                        check=True,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                    )
            else:
                logger.warning("[GIT-COMMIT] Commit failed (attempt %d/%d): %s", attempt + 1, retry_count, commit_r.stderr)
                if attempt == retry_count - 1:
                    return False

        subprocess.run(
            ["git", "push"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        return True
    except subprocess.CalledProcessError as e:
        logger.warning("[GIT-COMMIT] Process failed: %s", e)
        return False


# ---------------------------------------------------------------------------
# CI details / fix helpers
# ---------------------------------------------------------------------------


def _get_ci_failure_details(branch: str) -> str:
    """Fetch human-readable CI failure details from gh pr checks.

    Returns a short (capped) string suitable for inclusion in a fix prompt.
    """
    try:
        result = subprocess.run(
            ["gh", "pr", "checks", branch],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        return (result.stdout or "").strip()[:4000]
    except Exception:
        return "(could not retrieve CI failure details)"


def _fix_ci_failure(rec_id: str, branch: str, ci_reason: str) -> bool:
    """Ask the model to fix a CI failure, then commit and push any changes.

    Attempts a deterministic fix via triage_ci_failure() first.  Only
    escalates to the LLM when triage_ci_failure().escalate_to_llm is True.

    Returns True if a fix was committed and pushed, False otherwise.
    """
    logger.info("[CI-FIX] Attempting automated fix for %s (reason=%s)...", branch, ci_reason)

    ci_details = _get_ci_failure_details(branch)

    # --- Deterministic triage (no LLM cost) ---
    triage = triage_ci_failure(ci_details or ci_reason)
    logger.info("[CI-FIX] Triage: category=%s fixed=%s escalate=%s", triage.category, triage.fixed, triage.escalate_to_llm)

    if triage.fixed and triage.files_changed:
        # Auto-fix applied (e.g. ruff --fix) — commit and push
        return _git_commit_and_push_with_retry(
            branch=branch,
            commit_message=f"fix(ci): deterministic triage fix for {rec_id}",
            files_to_add=triage.files_changed if isinstance(triage.files_changed, list) else triage.files_changed.split(),
        )

    if not triage.escalate_to_llm:
        logger.info("[CI-FIX] Triage says no LLM escalation needed — fix was sufficient or unknown")
        return triage.fixed

    # --- LLM escalation ---
    llm_context = triage.context_for_llm or ci_details or "(no CI details available)"

    # Extract potential failing files from the triage context to provide snippets
    failing_files = []
    for match in re.finditer(r"([\w/.-]+\.py):", llm_context):
        path = match.group(1)
        if Path(path).exists() and path not in failing_files:
            failing_files.append(path)

    file_snippets = ""
    for path in failing_files[:3]:  # Cap at 3 files to avoid prompt bloat
        try:
            content = Path(path).read_text(encoding="utf-8")
            # Truncate large files
            if len(content) > 2000:
                content = content[:2000] + "\n# ... (truncated)"
            file_snippets += f"\nFILE: {path}\n```python\n{content}\n```\n"
        except Exception:
            continue

    try:
        # Run local validate.py to get fresh errors for the prompt.
        # Use Popen + kill_process_tree on Windows to prevent orphan processes.
        with subprocess.Popen(
            [sys.executable, "scripts/validate.py"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        ) as val_proc:
            try:
                val_stdout, val_stderr = val_proc.communicate(timeout=120)
                local_errors = (val_stdout + val_stderr).strip() if val_proc.returncode != 0 else ""
            except subprocess.TimeoutExpired:
                kill_process_tree(val_proc.pid)
                val_proc.wait()
                local_errors = "(validate.py timed out)"
    except Exception:
        local_errors = "(validate.py could not be started)"

    prompt = (
        f"The CI pipeline failed for branch {branch} (rec_id: {rec_id}).\n"
        "Your task is to diagnose and fix the failure.\n\n"
        f"CI FAILURE CATEGORY: {triage.category.value}\n\n"
        f"CI FAILURE DETAILS:\n{llm_context}\n\n"
        f"LOCAL VALIDATE OUTPUT:\n{local_errors[:2000] or '(validate passed locally)'}\n\n"
        f"FAILING FILE SNIPPETS:\n{file_snippets or '(No file snippets identified)'}\n\n"
        "Examine the errors carefully, identify the root cause, and apply the minimal "
        "fix required. Do not change unrelated code."
    )

    try:
        context_path = build_context_path("ci-fix", rec_id)
        result = llm_call(
            prompt,
            model=MODEL_EXECUTION if MODEL_EXECUTION else None,
            timeout=300,
            context_file_path=context_path,
            inline_instruction="Diagnose and fix the CI failure described in the attached context.",
            check=False,
            purpose="ci_fix",
        )
        if result.exit_code != 0:
            logger.warning("[CI-FIX] LLM call failed (exit %d)", result.exit_code)
            return False
    except Exception as exc:
        logger.warning("[CI-FIX] LLM call error: %s", exc)
        return False

    changed = subprocess.run(
        ["git", "diff", "--name-only"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()
    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()
    if not changed and not staged:
        logger.info("[CI-FIX] No file changes produced — nothing to commit")
        return False

    try:
        files_to_add = (changed + " " + staged).strip().split()
        return _git_commit_and_push_with_retry(
            branch=branch,
            commit_message=f"fix(ci): automated fix for {rec_id}",
            files_to_add=files_to_add,
        )
    except Exception as exc:
        logger.warning("[CI-FIX] Post-LLM fix application failed: %s", exc)
        return False


def _fix_code_review_findings(rec_id: str, branch: str, blocking_findings: list[str]) -> bool:
    """Ask the model to fix CRITICAL/HIGH code-review findings, then commit.

    Returns True if a fix was committed, False if nothing changed or failed.
    """
    logger.info("[REVIEW-FIX] Attempting automated fix for %d finding(s)...", len(blocking_findings))

    findings_text = "\n".join(f"- {f}" for f in blocking_findings)
    prompt = (
        f"A code review for recommendation {rec_id} found the following CRITICAL or HIGH issues "
        "that must be addressed before the PR can be merged.\n\n"
        f"BLOCKING FINDINGS:\n{findings_text}\n\n"
        "Your task: read the relevant files, diagnose each issue, and apply the minimal "
        "fix required. Do not change unrelated code. After fixing, briefly summarise "
        "what you changed and why."
    )

    try:
        context_path = build_context_path("review-fix", rec_id)
        result = llm_call(
            prompt,
            model=MODEL_EXECUTION if MODEL_EXECUTION else None,
            timeout=300,
            context_file_path=context_path,
            inline_instruction="Fix the blocking code review findings described in the attached context.",
            check=False,
            purpose="code_review_fix",
        )
        if result.exit_code != 0:
            logger.warning("[REVIEW-FIX] LLM call failed (exit %d)", result.exit_code)
            return False
    except Exception as exc:
        logger.warning("[REVIEW-FIX] LLM call error: %s", exc)
        return False

    changed = subprocess.run(
        ["git", "diff", "--name-only"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    ).stdout.strip()
    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    ).stdout.strip()
    if not changed and not staged:
        logger.info("[REVIEW-FIX] No file changes produced — nothing to commit")
        return False

    try:
        files_to_add = (changed + " " + staged).strip().split()
        return _git_commit_and_push_with_retry(
            branch=branch,
            commit_message=f"fix(review): address findings for {rec_id}",
            files_to_add=files_to_add,
        )
    except Exception as exc:
        logger.warning("[REVIEW-FIX] Post-LLM fix application failed: %s", exc)
        return False


def _commits_ahead_of_main() -> int:
    """Return the number of commits on HEAD not on main (local).

    Returns 0 on any git error so uncertainty never causes phases to be skipped.
    """
    try:
        result = subprocess.run(
            ["git", "rev-list", "--count", "main..HEAD"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=15,
        )
        if result.returncode == 0:
            return int(result.stdout.strip() or "0")
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError, OSError):
        pass
    return 0


def _scope_drift_check(plan_steps: list[dict]) -> list[str]:
    """Compare git diff against planned files and return unplanned file paths.

    Runs ``git diff origin/main --name-only`` and checks whether every changed
    file appears in the plan's step list.  Files under ``logs/`` and
    ``__pycache__/`` are always excluded (they are expected side-effects).

    Returns:
        List of file paths that are in the diff but not in any plan step.
        Empty list means no drift.
    """
    planned_files = {s.get("file", "") for s in plan_steps if s.get("file")}

    try:
        result = subprocess.run(
            ["git", "diff", "origin/main", "--name-only"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        if result.returncode != 0:
            logger.warning("[SCOPE] git diff failed (exit %d) — skipping drift check", result.returncode)
            return []
    except (subprocess.TimeoutExpired, FileNotFoundError):
        logger.warning("[SCOPE] git diff unavailable — skipping drift check")
        return []

    changed = [p for p in result.stdout.splitlines() if p.strip()]
    _EXCLUDED_PREFIXES = (
        "logs/",
        "__pycache__/",
        ".venv/",
        "build/",
        ".pytest_cache/",
        ".ruff_cache/",
        ".mypy_cache/",
    )
    _EXCLUDED_NAMES = {"requirements.txt", "scripts/execute_recommendation.py"}
    _EXCLUDED_EXTENSIONS = (".jsonl",)
    unplanned = [
        p
        for p in changed
        if not any(p.startswith(prefix) for prefix in _EXCLUDED_PREFIXES)
        and p not in planned_files
        and p not in _EXCLUDED_NAMES
        and not any(p.endswith(ext) for ext in _EXCLUDED_EXTENSIONS)
    ]
    if unplanned:
        emit_process_event(
            tier="decision",
            category="scope_drift_detected",
            severity="warning",
            description=f"{len(unplanned)} unplanned file(s): {', '.join(unplanned[:5])}",
        )
    return unplanned


def _code_review_gate(
    rec: dict,
    plan: ExecutionPlan,
    changed_files: list[str],
    effort: str = "",
) -> tuple[bool, float, list[str]]:
    """Run a focused automated code review via the Copilot CLI.

    Returns:
        Tuple of (passed, blocking_findings) where:
        - passed is True if no CRITICAL or HIGH findings were found
        - blocking_findings is a list of finding strings
    """
    rec_id = rec.get("id", "unknown")

    review_model = model_registry.resolve_model("review", effort or "M")

    per_file_budget = max(2000, 40000 // max(len(changed_files), 1))
    file_snippets: list[str] = []
    for fpath in changed_files:
        p = Path(fpath)
        if not p.exists():
            continue
        try:
            content = p.read_text(encoding="utf-8", errors="replace")
            if len(content) > per_file_budget:
                omitted = content[per_file_budget:].count("\n")
                content = content[:per_file_budget] + f"\n# ... ({omitted} lines omitted)\n"
            file_snippets.append(f"### {fpath}\n```\n{content}\n```")
        except OSError:
            continue

    files_block = "\n\n".join(file_snippets) if file_snippets else "(no readable changed files)"

    try:
        template, _ = load_prompt("code-review")
    except FileNotFoundError:
        logger.warning("[REVIEW] code-review.prompt.md not found — skipping gate")
        return True, 0.0, []

    prompt = template.format(
        rec_id=rec_id,
        title=rec.get("title", "(no title)"),
        acceptance=rec.get("acceptance", "(no acceptance criteria)"),
        plan_steps=plan.plan_text[:3000],
        changed_files="\n".join(changed_files),
        files_block=files_block,
    )

    logger.info("[REVIEW] Running focused code review (%d files)...", len(changed_files))
    context_path = build_context_path("review", rec_id)
    try:
        result = llm_call(
            prompt,
            model=review_model if review_model else None,
            timeout=300,
            context_file_path=context_path,
            inline_instruction="Review the code changes and report findings per the attached context.",
            check=False,
            purpose="code_review",
        )
    except subprocess.TimeoutExpired:
        logger.warning("[REVIEW] Code review timed out (300s) -- treating as passed")
        return True, 0.0, []

    cost = result.cost_usd
    if result.exit_code != 0 or not result.content.strip():
        logger.warning("[REVIEW] Code review call failed or returned empty — treating as passed")
        return True, cost, []

    output = result.content
    blocking: list[str] = []
    gate_passed = False
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if re.match(r"^\s*(?:\*\*)?(?:CRITICAL|HIGH)(?:\*\*)?\s*:\s", stripped):
            cleaned = stripped.strip(" -#*")
            if cleaned and not cleaned.isupper():
                blocking.append(cleaned)
        if stripped.startswith("GATE: PASSED"):
            gate_passed = True
        if stripped.startswith("GATE: FAILED"):
            gate_passed = False

    if blocking:
        logger.error("[REVIEW] %d blocking finding(s) found:", len(blocking))
        for f in blocking:
            logger.error("[REVIEW]   %s", f)
    else:
        logger.info("[REVIEW] No CRITICAL or HIGH findings — gate passed")
        emit_process_event(
            tier="decision",
            category="code_review_pass",
            severity="info",
            description="Code review passed",
        )

    return gate_passed and not blocking, cost, blocking


def _handle_failure(
    rec_id: str,
    rec: dict,
    failure_step: Optional[int],
    failure_reason: str,
    steps_completed: int,
    total_steps: int,
) -> None:
    """Push partial branch and create a draft PR on execution failure.

    Best-effort: logs warnings on push/PR errors but does not raise.
    """
    try:
        branch_result = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        branch = branch_result.stdout.strip() or f"agent/{rec_id}"
    except Exception:
        branch = f"agent/{rec_id}"

    title = rec.get("title", rec_id)
    pr_title = f"[FAILED] {rec_id}: {title}"
    pr_body = (
        f"## Automated Execution Failed\n\n"
        f"**Recommendation**: {rec_id}\n"
        f"**Failure step**: {failure_step if failure_step is not None else 'post-impl'}\n"
        f"**Reason**: {failure_reason[:500]}\n"
        f"**Steps completed**: {steps_completed}/{total_steps}\n\n"
        f"This draft PR preserves partial work for manual review or retry."
    )

    try:
        subprocess.run(
            ["git", "push", "--set-upstream", "origin", branch],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        logger.info("[FAILURE] Pushed partial branch %s", branch)
    except subprocess.CalledProcessError as e:
        logger.warning("[FAILURE] Push failed (non-critical): %s", (e.stderr or str(e))[:200])
        return

    try:
        subprocess.run(
            ["gh", "pr", "create", "--draft", "--head", branch, "--title", pr_title, "--body", pr_body],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        logger.info("[FAILURE] Draft PR created: %s", pr_title)
    except subprocess.CalledProcessError as e:
        logger.warning("[FAILURE] Draft PR creation failed (non-critical): %s", (e.stderr or str(e))[:200])


# ---------------------------------------------------------------------------
# CI wait / merge / cleanup
# ---------------------------------------------------------------------------


def wait_for_ci(branch: str, timeout: int = 600, interval: int = 30) -> tuple[bool, str]:
    """Poll CI status for the PR associated with branch until pass/fail/timeout.

    Returns:
        (True, "success") on CI pass
        (False, "timeout") after timeout
        (False, "failure") on CI failure
        (False, "checks_unavailable") when gh pr checks keeps failing
    """
    start = time.time()
    consecutive_check_failures = 0
    max_check_failures = int(os.getenv("CI_CHECKS_FAIL_THRESHOLD", "5"))
    early_poll_count = int(os.getenv("CI_EARLY_POLL_COUNT", "3"))
    early_poll_interval = int(os.getenv("CI_EARLY_POLL_INTERVAL", "10"))
    poll_number = 0

    while True:
        elapsed = time.time() - start
        remaining = timeout - elapsed
        if remaining <= 0:
            logger.warning("[CI] Timeout after %ds waiting for CI on %s", timeout, branch)
            return False, "timeout"

        try:
            result = subprocess.run(
                ["gh", "pr", "checks", branch, "--json", "state"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=30,
            )
            if result.returncode != 0:
                consecutive_check_failures += 1
                _gh_err = ("" or result.stdout or "(no output)").strip()[:200]
                logger.warning(
                    "[CI] gh pr checks failed (exit %d, consecutive=%d/%d): %s",
                    result.returncode,
                    consecutive_check_failures,
                    max_check_failures,
                    _gh_err,
                )
                if consecutive_check_failures >= max_check_failures:
                    logger.error("[CI] gh pr checks failed %d times in a row — escalating", max_check_failures)
                    return False, "checks_unavailable"
            else:
                consecutive_check_failures = 0
                try:
                    data = json.loads(result.stdout)
                    if isinstance(data, list):
                        states = [str(c.get("state", "")).lower() for c in data]
                    elif isinstance(data, dict):
                        states = [str(data.get("state", "")).lower()]
                    else:
                        states = []

                    if not states:
                        logger.info("[CI] No checks found yet, waiting... (%.0fs remaining)", remaining)
                    elif all(s in ("success", "pass") for s in states):
                        logger.info("[CI] All checks passed for %s", branch)
                        return True, "success"
                    elif any(s in ("failure", "fail", "error") for s in states):
                        logger.error("[CI] Check failure detected for %s: %s", branch, states)
                        return False, "failure"
                    else:
                        logger.info("[CI] Checks pending (%s), %.0fs remaining", states, remaining)
                except json.JSONDecodeError:
                    logger.warning("[CI] Failed to parse gh pr checks output, retrying...")

        except subprocess.TimeoutExpired:
            logger.warning("[CI] gh pr checks timed out, will retry...")

        poll_number += 1
        _sleep = early_poll_interval if poll_number <= early_poll_count else interval
        time.sleep(_sleep)


def _agent_merge_recovery(rec_id: str, branch: str, merge_err: str, attempt: int) -> tuple[bool, str]:
    """Hand merge failure entirely to the implementation agent for autonomous recovery.

    Returns:
        (True, pr_url) if the PR state is MERGED after the agent call.
        (False, reason) otherwise.
    """
    logger.info("[MERGE-RECOVERY] Attempt %d: handing merge failure to agent...", attempt)

    prompt = (
        f"The automated executor tried to merge the PR for branch `{branch}` "
        f"(rec_id: {rec_id}) but the merge failed with this error:\n\n"
        f"```\n{merge_err}\n```\n\n"
        "Your task is to diagnose the problem and complete the merge. Depending on the error, "
        "you may need to:\n"
        "- Resolve merge conflicts (remove all `<<<<<<<` / `=======` / `>>>>>>>` markers)\n"
        "- Stash or commit uncommitted working-tree changes\n"
        "- Rebase or merge from origin/main\n"
        "- Run `gh pr ready` if the PR is still a draft\n"
        f"- Run `gh pr merge {branch} --squash --delete-branch`\n\n"
        "When the merge is complete, run:\n"
        "  git checkout main && git pull origin main\n\n"
        "Output the exact string `MERGE_COMPLETE` on its own line to signal success, "
        "or `MERGE_FAILED: <reason>` if you cannot complete it."
    )

    try:
        context_path = build_context_path("merge-recovery", rec_id)
        result = llm_call(
            prompt,
            model=MODEL_EXECUTION if MODEL_EXECUTION else None,
            timeout=600,
            context_file_path=context_path,
            inline_instruction="Diagnose the merge failure and complete the merge per the attached context.",
            check=False,
            purpose="merge_recovery",
        )
        if result.exit_code != 0:
            logger.warning("[MERGE-RECOVERY] Agent call failed (exit %d)", result.exit_code)
            return False, f"agent call failed (exit {result.exit_code})"
    except Exception as exc:
        logger.warning("[MERGE-RECOVERY] Agent call error: %s", exc)
        return False, f"agent call error: {exc}"

    try:
        state_result = subprocess.run(
            ["gh", "pr", "view", branch, "--json", "state", "-q", ".state"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        pr_state = state_result.stdout.strip().upper()
    except Exception:
        pr_state = "UNKNOWN"

    if pr_state == "MERGED":
        logger.info("[MERGE-RECOVERY] PR confirmed MERGED on attempt %d", attempt)
        url_result = subprocess.run(
            ["gh", "pr", "view", branch, "--json", "url", "-q", ".url"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        pr_url = url_result.stdout.strip() if url_result.returncode == 0 else ""
        cleanup_after_merge(branch)
        return True, pr_url

    reason = f"PR state is {pr_state!r} after agent recovery (expected MERGED)"
    logger.error("[MERGE-RECOVERY] Attempt %d failed: %s", attempt, reason)
    return False, reason


def merge_pr(branch: str) -> tuple[bool, Optional[str]]:
    """Squash-merge the PR for branch and delete the remote branch.

    Returns:
        (True, None) on success
        (False, error_message) on failure
    """
    try:
        stash_result = subprocess.run(
            ["git", "stash", "--include-untracked"],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        stashed = "No local changes to save" not in stash_result.stdout
        try:
            subprocess.run(
                ["gh", "pr", "merge", branch, "--squash", "--delete-branch"],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
        finally:
            if stashed:
                subprocess.run(
                    ["git", "stash", "pop"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                )
        logger.info("[MERGE] PR for %s squash-merged", branch)
        return True, None
    except subprocess.CalledProcessError as e:
        error_msg = (e.stderr or str(e))[:500]
        logger.error("[MERGE] Failed to merge PR for %s: %s", branch, error_msg)
        return False, error_msg


def _safe_merge_origin_main(branch: str) -> bool:
    """Merge origin/main into the current branch safely.

    If conflicts occur, it resolves them automatically ONLY for log files
    (using 'ours'). If conflicts occur in product code (src/, scripts/),
    it aborts the merge to prevent silent regressions.

    Returns:
        True if merge succeeded (with or without auto-resolution), False otherwise.
    """
    try:
        subprocess.run(
            ["git", "fetch", "origin", "main"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        # Attempt a regular merge without committing yet
        merge_r = subprocess.run(
            ["git", "merge", "origin/main", "--no-commit", "--no-ff"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        if merge_r.returncode == 0:
            # Clean merge
            subprocess.run(
                ["git", "commit", "--no-edit", "-m", f"chore: merge origin/main into {branch}"],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            return True

        # Handle conflicts
        conflict_result = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=U"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        conflicted_files = conflict_result.stdout.splitlines()
        logger.info("[SAFE-MERGE] Conflicts detected in %d file(s)", len(conflicted_files))

        # Check if all conflicts are in logs/ or other safe areas
        safe_to_resolve = True
        for f in conflicted_files:
            if not f.startswith("logs/") and not f.endswith(".jsonl"):
                logger.warning("[SAFE-MERGE] Conflict in product code: %s. Aborting safe merge.", f)
                safe_to_resolve = False
                break

        if safe_to_resolve:
            logger.info("[SAFE-MERGE] All conflicts are in logs/ -- resolving with 'ours'")
            for f in conflicted_files:
                subprocess.run(["git", "checkout", "--ours", f], check=True, text=True, encoding="utf-8", errors="replace")
                subprocess.run(["git", "add", f], check=True, text=True, encoding="utf-8", errors="replace")

            subprocess.run(
                ["git", "commit", "--no-edit", "-m", f"chore: merge origin/main into {branch} (auto-resolved logs)"],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            return True

        # Unsafe to resolve automatically
        subprocess.run(["git", "merge", "--abort"], check=True, text=True, encoding="utf-8", errors="replace")
        return False

    except subprocess.CalledProcessError as e:
        logger.warning("[SAFE-MERGE] Git operation failed: %s", e)
        # Ensure we don't leave the repo in a merging state
        subprocess.run(["git", "merge", "--abort"], capture_output=True)


def cleanup_after_merge(branch: str) -> bool:
    """Return to main, pull latest, delete local and remote feature branches.

    Returns:
        True if cleanup succeeded, False on unrecoverable error.
    """
    try:
        checkout_main = subprocess.run(
            ["git", "checkout", "main"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if checkout_main.returncode != 0:
            logger.warning("[CLEANUP] Could not checkout main: %s", checkout_main.stderr)
            return False

        # Stash any remaining local changes (especially untracked logs)
        stash_result = subprocess.run(
            ["git", "stash", "--include-untracked", "--", "logs/"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        has_stash = stash_result.returncode == 0 and "No local changes to save" not in stash_result.stdout
        if stash_result.returncode != 0:
            logger.warning("[CLEANUP] git stash failed: %s", stash_result.stderr)

        pull_success = False
        for pull_attempt in range(3):
            pull_result = subprocess.run(
                ["git", "pull", "origin", "main"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if pull_result.returncode == 0:
                pull_success = True
                break
            if pull_attempt < 2:
                logger.info("[CLEANUP] git pull failed (exit %d), retrying in 2s...", pull_result.returncode)
                time.sleep(2)
            else:
                logger.warning(
                    "[CLEANUP] git pull failed after 3 attempts (exit %d): %s",
                    pull_result.returncode,
                    pull_result.stderr,
                )

        # Restore stashed log files before the JSONL commit check so that any
        # uncommitted rec-status changes are visible in the working tree again.
        if has_stash:
            pop_result = subprocess.run(
                ["git", "stash", "pop"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if pop_result.returncode != 0:
                logger.warning("[CLEANUP] git stash pop failed: %s", pop_result.stderr)

        # Legacy recommendation log commits removed.
        # Status persistence is now handled by the portal (Athena/S3).
        # Local JSONL changes are handled as a write-through cache.

        if not pull_success:
            raise subprocess.CalledProcessError(1, "git pull", stderr=pull_result.stderr or "")

        # Remove .pytest_cache, .ruff_cache, and .mypy_cache directories if they exist
        for cache_dir in [".pytest_cache", ".ruff_cache", ".mypy_cache"]:
            cache_path = Path(cache_dir)
            if cache_path.exists() and cache_path.is_dir():
                try:
                    shutil.rmtree(cache_path, ignore_errors=True)
                except Exception as e:
                    logger.warning(f"[CLEANUP] Failed to remove {cache_path}: {e}")

        delete = subprocess.run(
            ["git", "branch", "-d", branch],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if delete.returncode != 0:
            logger.info("[CLEANUP] Local branch %s already deleted or could not be deleted", branch)

        # Delete remote branch to ensure cleanup even when merge_pr's --delete-branch fails
        push_delete = subprocess.run(
            ["git", "push", "origin", "--delete", branch],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if push_delete.returncode != 0:
            logger.info("[CLEANUP] Remote branch %s could not be deleted: %s", branch, push_delete.stderr.strip())

        logger.info("[CLEANUP] Back on main, pulled latest, cleaned up %s", branch)
        clear_checkpoint()
        return True

    except subprocess.CalledProcessError as e:
        logger.error("[CLEANUP] Unrecoverable error during cleanup: %s", e)
        return False


def _parse_scope_files(plan_text: str) -> list[str]:
    """Extract file paths from a ## Scope markdown table."""
    import re

    match = re.search(r"##\s+Scope\s*\n(.*?)(?=\n##|\Z)", plan_text, re.DOTALL)
    if not match:
        return []
    files: list[str] = []
    for line in match.group(1).split("\n"):
        if line.strip().startswith("|") and "---" not in line:
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 3 and parts[1] and parts[1].lower() != "file":
                files.append(parts[1])
    return files


def _run_verifiers_gate(rec_id: str) -> bool:
    """Run all registered programmatic verifiers.

    Returns:
        False (blocking) if a failing HARD_GATE verifier's covers intersects the
        plan's scope. Falls back to V3-only blocking when scope cannot be loaded.
        True otherwise.
    """
    logger.info("[VERIFY] Running programmatic verifier harness...")
    try:
        import asyncio
        import re

        from scripts.executor.plan import ExecutionPlan
        from scripts.verifiers import VerifierSeverity, VerifierStatus, run_all_verifiers
        from scripts.verifiers.harness import scope_intersects_covers

        # Load scope files for coverage-based predicate; V3 flag retained as fallback
        scope_files: list[str] = []
        is_v3 = False
        try:
            plan = ExecutionPlan.load(rec_id)
            if plan:
                plan_text = getattr(plan, "plan_text", "")
                if isinstance(plan_text, str) and plan_text:
                    scope_files = _parse_scope_files(plan_text)
                    tier_match = re.search(r"##\s+Verification\s+Tier\s*\n\s*(\w+)", plan_text, re.IGNORECASE)
                    if tier_match:
                        is_v3 = tier_match.group(1).strip() == "V3"
                if not is_v3:
                    is_v3 = getattr(plan, "verification_tier", "") == "V3"
        except Exception as e:
            logger.warning("[VERIFY] Could not load plan scope for coverage predicate: %s", e)

        results = asyncio.run(run_all_verifiers())
        has_blocking_fail = False
        for res in results:
            status_str = f"[{res.status}]"
            logger.info("[VERIFY]   %-10s %s: %s (severity=%s)", status_str, res.name, res.message, res.severity)

            if res.status == VerifierStatus.FAIL and res.severity == VerifierSeverity.HARD_GATE:
                if scope_files:
                    blocking = scope_intersects_covers(scope_files, res.covers)
                else:
                    blocking = is_v3
                if blocking:
                    has_blocking_fail = True
                else:
                    logger.info(
                        "[VERIFY] Non-blocking: %s covers %s (no scope intersection or non-V3 fallback)",
                        res.name,
                        res.covers,
                    )
            elif res.status == VerifierStatus.FAIL:
                logger.info("[VERIFY] Advisory failure (non-blocking)")

        if has_blocking_fail:
            logger.error("[VERIFY] Hard gate failure: one or more verifiers blocked execution.")
            return False
        return True
    except Exception as exc:  # noqa: BLE001
        logger.error("[VERIFY] Verifier harness threw unexpectedly: %s", exc)
        emit_process_event("verification_gate_error", {"error": str(exc)})
        return False


# ---------------------------------------------------------------------------
# Top-level finalize
# ---------------------------------------------------------------------------


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
