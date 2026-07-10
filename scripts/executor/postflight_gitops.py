"""Git commit/push, PR merge, safe origin/main merge, and post-merge cleanup for the executor.

Extracted from scripts/executor/postflight.py (Decision 102/104 SLOC decomposition). The
scripts.executor.postflight facade re-exports these symbols and remains the sole import path
for callers and tests; bodies reach shared collaborators through that facade at call time.
"""

import logging
import shutil
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


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
    import scripts.executor.postflight as _pf

    try:
        if files_to_add:
            _pf.subprocess.run(
                ["git", "add"] + files_to_add,
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )

        for attempt in range(retry_count):
            commit_r = _pf.subprocess.run(
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
                    _pf.subprocess.run(
                        ["git", "add"] + files_to_add,
                        check=True,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                    )
                else:
                    # If we didn't have a file list, add all changes
                    _pf.subprocess.run(
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

        _pf.subprocess.run(
            ["git", "push"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        return True
    except _pf.subprocess.CalledProcessError as e:
        logger.warning("[GIT-COMMIT] Process failed: %s", e)
        return False


def merge_pr(branch: str) -> tuple[bool, Optional[str]]:
    """Squash-merge the PR for branch and delete the remote branch.

    Returns:
        (True, None) on success
        (False, error_message) on failure
    """
    import scripts.executor.postflight as _pf

    try:
        stash_result = _pf.subprocess.run(
            ["git", "stash", "--include-untracked"],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        stashed = "No local changes to save" not in stash_result.stdout
        try:
            _pf.subprocess.run(
                ["gh", "pr", "merge", branch, "--squash", "--delete-branch"],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
        finally:
            if stashed:
                _pf.subprocess.run(
                    ["git", "stash", "pop"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                )
        logger.info("[MERGE] PR for %s squash-merged", branch)
        return True, None
    except _pf.subprocess.CalledProcessError as e:
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
    import scripts.executor.postflight as _pf

    try:
        _pf.subprocess.run(
            ["git", "fetch", "origin", "main"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        # Attempt a regular merge without committing yet
        merge_r = _pf.subprocess.run(
            ["git", "merge", "origin/main", "--no-commit", "--no-ff"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        if merge_r.returncode == 0:
            # Clean merge
            _pf.subprocess.run(
                ["git", "commit", "--no-edit", "-m", f"chore: merge origin/main into {branch}"],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            return True

        # Handle conflicts
        conflict_result = _pf.subprocess.run(
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
                _pf.subprocess.run(["git", "checkout", "--ours", f], check=True, text=True, encoding="utf-8", errors="replace")
                _pf.subprocess.run(["git", "add", f], check=True, text=True, encoding="utf-8", errors="replace")

            _pf.subprocess.run(
                ["git", "commit", "--no-edit", "-m", f"chore: merge origin/main into {branch} (auto-resolved logs)"],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            return True

        # Unsafe to resolve automatically
        _pf.subprocess.run(["git", "merge", "--abort"], check=True, text=True, encoding="utf-8", errors="replace")
        return False

    except _pf.subprocess.CalledProcessError as e:
        logger.warning("[SAFE-MERGE] Git operation failed: %s", e)
        # Ensure we don't leave the repo in a merging state
        _pf.subprocess.run(["git", "merge", "--abort"], capture_output=True)


def cleanup_after_merge(branch: str) -> bool:
    """Return to main, pull latest, delete local and remote feature branches.

    Returns:
        True if cleanup succeeded, False on unrecoverable error.
    """
    import scripts.executor.postflight as _pf

    try:
        checkout_main = _pf.subprocess.run(
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
        stash_result = _pf.subprocess.run(
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
            pull_result = _pf.subprocess.run(
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
                _pf.time.sleep(2)
            else:
                logger.warning(
                    "[CLEANUP] git pull failed after 3 attempts (exit %d): %s",
                    pull_result.returncode,
                    pull_result.stderr,
                )

        # Restore stashed log files before the JSONL commit check so that any
        # uncommitted rec-status changes are visible in the working tree again.
        if has_stash:
            pop_result = _pf.subprocess.run(
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
            raise _pf.subprocess.CalledProcessError(1, "git pull", stderr=pull_result.stderr or "")

        # Remove .pytest_cache, .ruff_cache, and .mypy_cache directories if they exist
        for cache_dir in [".pytest_cache", ".ruff_cache", ".mypy_cache"]:
            cache_path = Path(cache_dir)
            if cache_path.exists() and cache_path.is_dir():
                try:
                    shutil.rmtree(cache_path, ignore_errors=True)
                except Exception as e:
                    logger.warning(f"[CLEANUP] Failed to remove {cache_path}: {e}")

        delete = _pf.subprocess.run(
            ["git", "branch", "-d", branch],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if delete.returncode != 0:
            logger.info("[CLEANUP] Local branch %s already deleted or could not be deleted", branch)

        # Delete remote branch to ensure cleanup even when merge_pr's --delete-branch fails
        push_delete = _pf.subprocess.run(
            ["git", "push", "origin", "--delete", branch],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if push_delete.returncode != 0:
            logger.info("[CLEANUP] Remote branch %s could not be deleted: %s", branch, push_delete.stderr.strip())

        logger.info("[CLEANUP] Back on main, pulled latest, cleaned up %s", branch)
        _pf.clear_checkpoint()
        return True

    except _pf.subprocess.CalledProcessError as e:
        logger.error("[CLEANUP] Unrecoverable error during cleanup: %s", e)
        return False
