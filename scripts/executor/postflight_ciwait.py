"""CI polling and agent-mediated merge recovery for the executor.

Extracted from scripts/executor/postflight.py (Decision 102/104 SLOC decomposition). The
scripts.executor.postflight facade re-exports these symbols and remains the sole import path
for callers and tests; bodies reach shared collaborators through that facade at call time.
"""

import json
import logging
import os

logger = logging.getLogger(__name__)


def wait_for_ci(branch: str, timeout: int = 600, interval: int = 30) -> tuple[bool, str]:
    """Poll CI status for the PR associated with branch until pass/fail/timeout.

    Returns:
        (True, "success") on CI pass
        (False, "timeout") after timeout
        (False, "failure") on CI failure
        (False, "checks_unavailable") when gh pr checks keeps failing
    """
    import scripts.executor.postflight as _pf

    start = _pf.time.time()
    consecutive_check_failures = 0
    max_check_failures = int(os.getenv("CI_CHECKS_FAIL_THRESHOLD", "5"))
    early_poll_count = int(os.getenv("CI_EARLY_POLL_COUNT", "3"))
    early_poll_interval = int(os.getenv("CI_EARLY_POLL_INTERVAL", "10"))
    poll_number = 0

    while True:
        elapsed = _pf.time.time() - start
        remaining = timeout - elapsed
        if remaining <= 0:
            logger.warning("[CI] Timeout after %ds waiting for CI on %s", timeout, branch)
            return False, "timeout"

        try:
            result = _pf.subprocess.run(
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

        except _pf.subprocess.TimeoutExpired:
            logger.warning("[CI] gh pr checks timed out, will retry...")

        poll_number += 1
        _sleep = early_poll_interval if poll_number <= early_poll_count else interval
        _pf.time.sleep(_sleep)


def _agent_merge_recovery(rec_id: str, branch: str, merge_err: str, attempt: int) -> tuple[bool, str]:
    """Hand merge failure entirely to the implementation agent for autonomous recovery.

    Returns:
        (True, pr_url) if the PR state is MERGED after the agent call.
        (False, reason) otherwise.
    """
    import scripts.executor.postflight as _pf

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
        context_path = _pf.build_context_path("merge-recovery", rec_id)
        result = _pf.llm_call(
            prompt,
            model=_pf.MODEL_EXECUTION if _pf.MODEL_EXECUTION else None,
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
        state_result = _pf.subprocess.run(
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
        url_result = _pf.subprocess.run(
            ["gh", "pr", "view", branch, "--json", "url", "-q", ".url"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        pr_url = url_result.stdout.strip() if url_result.returncode == 0 else ""
        _pf.cleanup_after_merge(branch)
        return True, pr_url

    reason = f"PR state is {pr_state!r} after agent recovery (expected MERGED)"
    logger.error("[MERGE-RECOVERY] Attempt %d failed: %s", attempt, reason)
    return False, reason
