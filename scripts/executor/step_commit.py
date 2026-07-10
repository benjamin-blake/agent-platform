"""Git commit and pre-commit scope enforcement for the executor.

Extracted from scripts/executor/step_runner.py (SLOC decomposition, Decision
102/104 facade mechanism). Enforces that worktree changes stay within the
declared step file before committing, then commits the step with pre-commit
hook retry handling. Routed-name references (subprocess, Path,
_list_meaningful_worktree_changes) resolve through the
scripts.executor.step_runner facade via a function-local import so the
existing test suite's patches on scripts.executor.step_runner.<name> keep
intercepting with zero migration -- in particular commit_step's call into
_enforce_step_scope routes through the facade rather than a bare co-located
call, since the test suite's 10 patch sites target the facade namespace.
"""

import logging

logger = logging.getLogger(__name__)


def _enforce_step_scope(step: dict, step_n: int) -> bool:
    """Verify worktree changes are limited to the declared step file.

    Compares the normalized declared step file path against non-log
    worktree changes reported by ``git diff --name-only`` (unstaged),
    ``git diff --name-only --cached`` (staged), and
    ``git ls-files --others --exclude-standard`` (untracked).

    Paths are normalized to forward-slash POSIX form for comparison
    because Git always reports paths with forward slashes regardless
    of the OS.

    Returns True if all changed files are in scope (the declared step
    file, its corresponding test file, or log/cache paths already
    filtered by ``_list_meaningful_worktree_changes``). Returns False
    and logs an error when out-of-scope files are detected.
    """
    import scripts.executor.step_runner as _sr

    step_file = (step.get("file", "") or "").strip()
    if not step_file:
        # No declared file -- nothing to enforce.
        return True

    # Normalize to POSIX forward-slash form to match git output.
    declared = step_file.replace("\\", "/").strip("/")

    # Build the set of allowed paths: the declared step file and its
    # conventional test file (tests/test_{stem}.py).
    allowed: set[str] = {declared}
    try:
        stem = _sr.Path(declared).stem
        if stem:
            test_path = f"tests/test_{stem}.py"
            allowed.add(test_path)
    except Exception:
        pass

    changed = _sr._list_meaningful_worktree_changes()
    if not changed:
        return True

    out_of_scope = [p for p in changed if p not in allowed]
    if not out_of_scope:
        return True

    logger.error(
        "[SCOPE] Step %d declared file %r but worktree has out-of-scope changes: %s",
        step_n,
        declared,
        ", ".join(out_of_scope),
    )
    return False


def commit_step(step: dict, rec_id: str, step_n: int) -> tuple[bool, str]:
    """Commit changes from a single step.

    Runs scope enforcement before ``git add -A`` to prevent out-of-scope
    files from being swept into the step commit.

    Retries up to 3 times: pre-commit hooks may modify files and abort the
    first attempt.

    Returns:
        Tuple of (success, diff_stat) where diff_stat is the output of
        ``git diff HEAD~1 --stat`` (empty on failure or nothing to commit).
    """
    import scripts.executor.step_runner as _sr

    try:
        if not _sr._enforce_step_scope(step, step_n):
            logger.error(
                "[GIT] Scope enforcement failed for step %d — aborting commit",
                step_n,
            )
            return False, ""

        msg = f"impl({rec_id}): step {step_n} - {step.get('title', 'untitled')[:50]}"
        for attempt in range(1, 4):
            _sr.subprocess.run(
                ["git", "add", "-A"],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            try:
                commit_cmd = ["git", "commit", "-m", msg]
                if attempt == 3:
                    commit_cmd.append("--no-verify")
                _sr.subprocess.run(
                    commit_cmd,
                    check=True,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
                break
            except _sr.subprocess.CalledProcessError as e:
                err_out = (e.stderr or "") + (e.stdout or "")
                if "nothing to commit" in err_out or "nothing added to commit" in err_out:
                    logger.info("[GIT] No changes to commit for step %d", step_n)
                    return True, ""
                if attempt < 3 and ("files were modified by this hook" in err_out or "modified by hooks" in err_out):
                    logger.warning("[GIT] Pre-commit hooks modified files, retrying (%d/3)", attempt)
                    continue
                raise
        logger.info("[GIT] Committed step %d", step_n)

        diff_stat = ""
        try:
            diff_result = _sr.subprocess.run(
                ["git", "diff", "HEAD~1", "--stat"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
            if diff_result.returncode == 0:
                diff_stat = diff_result.stdout.strip()
        except Exception:
            pass

        return True, diff_stat
    except _sr.subprocess.CalledProcessError as e:
        if "nothing to commit" in str(e.stderr):
            logger.info("[GIT] No changes to commit for step %d", step_n)
            return True, ""
        logger.error("[GIT] Commit failed for step %d: %s", step_n, e)
        return False, ""
