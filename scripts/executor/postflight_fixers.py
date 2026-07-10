# complexity-waiver: decision-43
"""LLM-escalation fixers for CI failures and code-review findings.

Extracted from scripts/executor/postflight.py (Decision 102/104 SLOC decomposition). The
scripts.executor.postflight facade re-exports these symbols and remains the sole import path
for callers and tests; bodies reach shared collaborators through that facade at call time.
"""

import logging
import re
import sys
from pathlib import Path

from scripts.executor.ci_triage import triage_ci_failure

logger = logging.getLogger(__name__)


def _get_ci_failure_details(branch: str) -> str:
    """Fetch human-readable CI failure details from gh pr checks.

    Returns a short (capped) string suitable for inclusion in a fix prompt.
    """
    import scripts.executor.postflight as _pf

    try:
        result = _pf.subprocess.run(
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
    import scripts.executor.postflight as _pf

    logger.info("[CI-FIX] Attempting automated fix for %s (reason=%s)...", branch, ci_reason)

    ci_details = _pf._get_ci_failure_details(branch)

    # --- Deterministic triage (no LLM cost) ---
    triage = triage_ci_failure(ci_details or ci_reason)
    logger.info("[CI-FIX] Triage: category=%s fixed=%s escalate=%s", triage.category, triage.fixed, triage.escalate_to_llm)

    if triage.fixed and triage.files_changed:
        # Auto-fix applied (e.g. ruff --fix) — commit and push
        return _pf._git_commit_and_push_with_retry(
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
        with _pf.subprocess.Popen(
            [sys.executable, "scripts/validate.py"],
            stdout=_pf.subprocess.PIPE,
            stderr=_pf.subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        ) as val_proc:
            try:
                val_stdout, val_stderr = val_proc.communicate(timeout=120)
                local_errors = (val_stdout + val_stderr).strip() if val_proc.returncode != 0 else ""
            except _pf.subprocess.TimeoutExpired:
                _pf.kill_process_tree(val_proc.pid)
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
        context_path = _pf.build_context_path("ci-fix", rec_id)
        result = _pf.llm_call(
            prompt,
            model=_pf.MODEL_EXECUTION if _pf.MODEL_EXECUTION else None,
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

    changed = _pf.subprocess.run(
        ["git", "diff", "--name-only"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()
    staged = _pf.subprocess.run(
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
        return _pf._git_commit_and_push_with_retry(
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
    import scripts.executor.postflight as _pf

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
        context_path = _pf.build_context_path("review-fix", rec_id)
        result = _pf.llm_call(
            prompt,
            model=_pf.MODEL_EXECUTION if _pf.MODEL_EXECUTION else None,
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

    changed = _pf.subprocess.run(
        ["git", "diff", "--name-only"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    ).stdout.strip()
    staged = _pf.subprocess.run(
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
        return _pf._git_commit_and_push_with_retry(
            branch=branch,
            commit_message=f"fix(review): address findings for {rec_id}",
            files_to_add=files_to_add,
        )
    except Exception as exc:
        logger.warning("[REVIEW-FIX] Post-LLM fix application failed: %s", exc)
        return False
