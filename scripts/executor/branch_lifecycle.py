"""Recommendation eligibility guards, branch lifecycle, and retry cleanup for the executor.

Extracted from scripts/execute_recommendation.py (SLOC decomposition, Decision
102/104 facade mechanism, operator-descoped per the plan's ORCHESTRATOR
RATIFICATION context bullet -- this is a low-risk cluster extraction, not part
of the phase-shatter). Covers feature-branch creation/pruning, hotfix branch
creation and filing, poisoned-rec / clean-JSONL preflight guards, and the
idempotent clean_slate retry-cleanup sequence.

Routed-name references (subprocess, load_checkpoint, clear_checkpoint,
load_recommendation, _reset_rec_status, _check_jsonl_clean) resolve through
the scripts.execute_recommendation facade via a function-local import so the
existing test suite's patches on scripts.execute_recommendation.<name> keep
intercepting with zero migration -- in particular ensure_feature_branch's
call into _check_jsonl_clean and clean_slate's calls into the checkpoint/
recommendation collaborators route through the facade rather than a bare
co-located reference. The function-local `from scripts.ops_data_portal import
file_rec / find_open_postmortem_for` and `from scripts.llm.client import
llm_call` imports stay lazy exactly as today -- their patch sites target
those source namespaces directly, not the facade.
"""

import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def _discard_commit_range_files(num_commits: int) -> None:
    """Discard working tree changes for all files modified in a commit range.

    Uses git show to list files modified in HEAD~{num_commits}..HEAD,
    then runs git checkout -- on each file to discard working tree changes.

    Args:
        num_commits: Number of commits to look back from HEAD.
    """
    import scripts.execute_recommendation as _er

    try:
        result = _er.subprocess.run(
            ["git", "show", f"HEAD~{num_commits}..HEAD", "--name-only", "--format="],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        if result.returncode != 0:
            logger.warning(
                "[DISCARD] Failed to list files in commit range: %s",
                "".strip(),
            )
            return

        modified_files = [line.strip() for line in result.stdout.splitlines() if line.strip()]

        if not modified_files:
            logger.info("[DISCARD] No modified files found in commit range")
            return

        logger.info(
            "[DISCARD] Discarding changes for %d file(s) in commit range",
            len(modified_files),
        )

        for file_path in modified_files:
            try:
                _er.subprocess.run(
                    ["git", "checkout", "--", file_path],
                    check=True,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=10,
                )
            except _er.subprocess.TimeoutExpired:
                logger.warning("[DISCARD] Timeout discarding changes for %s", file_path)
            except Exception as e:
                logger.warning("[DISCARD] Failed to discard changes for %s: %s", file_path, e)

    except _er.subprocess.TimeoutExpired:
        logger.warning("[DISCARD] Timeout listing files in commit range")
    except Exception as e:
        logger.warning("[DISCARD] Failed to discard commit range files: %s", e)


def _seed_gemini_session() -> str:
    """Pre-load GEMINI.md into a Gemini CLI session for token cache reuse.

    Makes a minimal inference call so the CLI loads and caches the GEMINI.md
    project context. All subsequent calls that pass the returned session_id
    via ``--resume`` will find GEMINI.md already in the server-side token cache,
    reducing cold-start input tokens.

    Only called when ``LLM_PROVIDER`` is ``gemini`` and
    ``PLAN_SESSION_RESUME`` is not ``false``/``0``.

    Returns:
        Gemini CLI session_id string from the ``init`` event, or ``""`` on
        failure (callers fall back to cold-start).
    """
    from scripts.llm.client import llm_call

    try:
        result = llm_call(
            "Ready.",
            model=None,  # flash (auto -- fastest for seeding)
            tools=True,  # register write tools so resumed sessions can use them
            purpose="warm_base",
            check=False,
        )
        if result.session_id:
            logger.info(
                "[WARM] GEMINI.md seeded into session %s (%d input tokens)",
                result.session_id[:8],
                result.tokens_in,
            )
        return result.session_id or ""
    except Exception:  # noqa: BLE001
        logger.warning("[WARM] Failed to seed GEMINI.md session -- planning will cold-start", exc_info=True)
        return ""


def _is_checkpoint_branch_merged(branch: str) -> bool:
    """Check if a branch has been merged to main using git merge-base.

    Args:
        branch: The branch name to check (e.g., 'agent/rec-061').

    Returns:
        True if the branch has been merged to main, False otherwise or on error.
    """
    import scripts.execute_recommendation as _er

    try:
        result = _er.subprocess.run(
            ["git", "merge-base", "--is-ancestor", branch, "main"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        return result.returncode == 0
    except _er.subprocess.TimeoutExpired:
        logger.warning("Timeout checking if %s is ancestor of main", branch)
        return False
    except Exception as e:
        logger.warning("Error checking if %s is ancestor of main: %s", branch, e)
        return False


def _is_poisoned_rec(rec_id: str) -> bool:
    """Return True if an open executor-postmortem exists for rec_id and the env override is not set.

    Skipped when ``PYTEST_CURRENT_TEST`` is set (mirrors ``write_run_summary`` behaviour).
    Tests must not consult global JSONL state; callers that need production behaviour should
    unset the env var and monkeypatch ``find_open_postmortem_for``.
    """
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return False
    if os.environ.get("ALLOW_POISONED_RECS", "").lower() == "true":
        return False
    from scripts.ops_data_portal import find_open_postmortem_for  # noqa: PLC0415

    return find_open_postmortem_for(rec_id) is not None


def _check_jsonl_clean() -> bool:
    """Guard against branching with uncommitted recommendations JSONL changes.

    Delivery contract: The executor reads recommendation metadata from
    ``logs/.recommendations-log.jsonl`` (docs/AGENT_WORKFLOW.md). If that file
    has uncommitted working-tree changes at branch-creation time, the executor
    would run against stale or in-progress recommendation metadata, silently
    contaminating the run.

    Uses ``git diff HEAD --quiet -- <path>`` pathspec semantics so both staged
    and unstaged edits to this one tracked file are detected without broadening
    to unrelated workspace changes. If those semantics were misunderstood (e.g.
    omitting ``HEAD``), staged JSONL edits could be missed and branch execution
    could proceed on inconsistent recommendation metadata.

    Returns:
        True if the file is clean (no uncommitted changes), False otherwise.
    """
    import scripts.execute_recommendation as _er

    jsonl_path = "logs/.recommendations-log.jsonl"
    try:
        result = _er.subprocess.run(
            ["git", "diff", "HEAD", "--quiet", "--", jsonl_path],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        if result.returncode != 0:
            logger.warning(
                "[PREFLIGHT] uncommitted changes to recommendations log detected (%s) -- commit or stash before branching",
                jsonl_path,
            )
            return False
        return True
    except _er.subprocess.TimeoutExpired:
        logger.warning("[PREFLIGHT] Timeout checking uncommitted recommendations log state")
        return False
    except Exception as exc:
        logger.warning("[PREFLIGHT] Failed to check uncommitted recommendations log: %s", exc)
        return False


def ensure_feature_branch(rec_id: str) -> bool:
    """Create agent/{rec_id} branch from main if needed. Returns True if ready."""
    import scripts.execute_recommendation as _er

    expected_branch = f"agent/{rec_id}"
    try:
        result = _er.subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        current = result.stdout.strip()

        if current == "main":
            if not _er._check_jsonl_clean():
                print("ERROR: Recommendations JSONL has uncommitted changes -- commit or stash before branching")
                return False
            logger.info("[BRANCH] On main, creating branch %s", expected_branch)
            _er.subprocess.run(
                ["git", "fetch", "origin", "main"],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            # Try to create the branch; fall back to checking out the existing one
            # (exit code 128 = branch already exists from a previous aborted run).
            try:
                _er.subprocess.run(
                    ["git", "checkout", "-b", expected_branch],
                    check=True,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
                logger.info("[BRANCH] Created new branch %s", expected_branch)
            except _er.subprocess.CalledProcessError as branch_err:
                if branch_err.returncode == 128:
                    logger.info(
                        "[BRANCH] Branch %s already exists -- checking it out (previous aborted run detected)",
                        expected_branch,
                    )
                    _er.subprocess.run(
                        ["git", "checkout", expected_branch],
                        check=True,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                    )
                else:
                    raise
            return True
        elif current == expected_branch:
            logger.info("[BRANCH] Already on correct feature branch: %s", current)
            return True
        elif current.startswith("agent/"):
            logger.warning(
                "[BRANCH] On wrong feature branch '%s' -- expected '%s'. Checkout main first or use --restart.",
                current,
                expected_branch,
            )
            return False
        else:
            logger.warning("[BRANCH] On unexpected branch '%s' -- expected main or %s", current, expected_branch)
            return False
    except _er.subprocess.CalledProcessError as e:
        logger.error("[BRANCH] Git operation failed: %s", e)
        return False


def prune_merged_agent_branches() -> None:
    """Delete local agent/ branches whose tips are ancestors of main (already merged)."""
    import scripts.execute_recommendation as _er

    try:
        list_result = _er.subprocess.run(
            ["git", "branch", "--list", "agent/*"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if list_result.returncode != 0:
            return

        branches = [line.strip().lstrip("* ") for line in list_result.stdout.splitlines() if line.strip()]
        for branch in branches:
            try:
                is_ancestor = _er.subprocess.run(
                    ["git", "merge-base", "--is-ancestor", branch, "main"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
                if is_ancestor.returncode == 0:
                    delete_result = _er.subprocess.run(
                        ["git", "branch", "-d", branch],
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                    )
                    if delete_result.returncode == 0:
                        logger.info("[PRUNE] Deleted merged branch: %s", branch)
                        remote_delete_result = _er.subprocess.run(
                            ["git", "push", "origin", "--delete", branch],
                            capture_output=True,
                            text=True,
                            encoding="utf-8",
                            errors="replace",
                        )
                        if remote_delete_result.returncode == 0:
                            logger.info("[PRUNE] Deleted remote branch: %s", branch)
                        else:
                            logger.debug(
                                "[PRUNE] Could not delete remote %s: %s",
                                branch,
                                remote_delete_result.stderr.strip(),
                            )
                    else:
                        logger.debug("[PRUNE] Could not delete %s: %s", branch, delete_result.stderr.strip())
            except _er.subprocess.CalledProcessError:
                continue
    except _er.subprocess.CalledProcessError:
        pass


def create_hotfix_branch(rec_id: str, slug: str) -> str:
    """Create a hotfix branch for mid-flight executor machinery fixes.

    Branch name format: agent/rec-{rec_id}-hotfix-{slug}

    Args:
        rec_id: The recommendation ID being processed (e.g., 'rec-170').
        slug: Short descriptor of the fix (e.g., 'acceptance-cmd').

    Returns:
        The created branch name.
    """
    import scripts.execute_recommendation as _er

    branch_name = f"agent/rec-{rec_id}-hotfix-{slug}"
    _er.subprocess.run(
        ["git", "checkout", "-b", branch_name],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    logger.info("[HOTFIX] Created hotfix branch: %s", branch_name)
    return branch_name


def file_hotfix_rec(rec_id: str, hotfix_slug: str, description: str) -> str:
    """File a new recommendation for a hotfix applied during an executor run.

    Creates an open rec referencing the parent rec so the fix is tracked and
    can be reviewed to determine if it addresses root cause vs symptom.

    Delegates to scripts.ops_data_portal.file_rec() for centralised ID
    allocation (DynamoDB) and S3 staging via OpsWriter.

    Args:
        rec_id: The parent recommendation ID (e.g., 'rec-170').
        hotfix_slug: Short descriptor of what was fixed (e.g., 'acceptance-cmd').
        description: Human-readable description of what was fixed and why.

    Returns:
        The new recommendation ID (e.g., 'rec-522') or 'pending-<uuid>'
        when DynamoDB is temporarily unreachable.
    """
    from scripts.ops_data_portal import file_rec  # noqa: PLC0415

    hotfix_fields: dict = {
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "title": f"Hotfix applied during {rec_id}: {hotfix_slug}",
        "source": "executor-hotfix",
        "effort": "XS",
        "priority": "High",
        "status": "open",
        "automatable": True,
        "risk": "low",
        "file": "scripts/execute_recommendation.py",
        "context": (
            f"Hotfix applied mid-flight during execution of {rec_id}. "
            f"Branch: agent/rec-{rec_id}-hotfix-{hotfix_slug}. "
            f"Description: {description}"
        ),
        "acceptance": f"grep -q '{hotfix_slug}' scripts/execute_recommendation.py",
    }

    new_id = file_rec(hotfix_fields)
    logger.info("[HOTFIX] Filed new rec %s for hotfix of %s", new_id, rec_id)
    return new_id


def clean_slate(rec_id: str) -> None:
    """Idempotent retry cleanup for a recommendation before re-execution.

    Performs all cleanup steps, logging failures but never raising so
    the caller can proceed regardless:
      (a) Delete local branch agent/{rec_id} if it exists
      (b) Delete remote branch via git push origin --delete (ignore errors)
      (c) Clear execution-state.json checkpoint if it references this rec
      (d) Close any open draft PRs for the branch via gh pr close
      (e) Reset rec status to "open" if currently "failed"
    """
    import scripts.execute_recommendation as _er

    branch = f"agent/{rec_id}"
    logger.info("[CLEAN_SLATE] Starting cleanup for %s", rec_id)

    # (a) Delete local branch if it exists
    try:
        result = _er.subprocess.run(
            ["git", "branch", "--list", branch],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        if result.stdout.strip():
            _er.subprocess.run(
                ["git", "branch", "-D", branch],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
            )
            logger.info("[CLEAN_SLATE] Deleted local branch %s", branch)
    except Exception as exc:
        logger.warning(
            "[CLEAN_SLATE] Failed to delete local branch %s: %s",
            branch,
            exc,
        )

    # (b) Delete remote branch (ignore errors)
    try:
        _er.subprocess.run(
            ["git", "push", "origin", "--delete", branch],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        logger.info("[CLEAN_SLATE] Deleted remote branch %s", branch)
    except Exception as exc:
        logger.warning(
            "[CLEAN_SLATE] Failed to delete remote branch %s: %s",
            branch,
            exc,
        )

    # (c) Clear checkpoint if it references this rec
    try:
        cp = _er.load_checkpoint()
        if cp is not None and cp.get("plan_file") == rec_id:
            _er.clear_checkpoint()
            logger.info(
                "[CLEAN_SLATE] Cleared stale checkpoint for %s",
                rec_id,
            )
    except Exception as exc:
        logger.warning("[CLEAN_SLATE] Failed to clear checkpoint: %s", exc)

    # (d) Close any open draft PRs for the branch
    try:
        _er.subprocess.run(
            ["gh", "pr", "close", branch],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        logger.info("[CLEAN_SLATE] Closed open PR for branch %s", branch)
    except Exception as exc:
        logger.warning(
            "[CLEAN_SLATE] Failed to close PR for %s: %s",
            branch,
            exc,
        )

    # (e) Reset rec status to "open" if currently "failed"
    try:
        rec = _er.load_recommendation(rec_id)
        if rec is not None and rec.get("status") == "failed":
            _er._reset_rec_status(rec_id)
            logger.info(
                "[CLEAN_SLATE] Reset status to 'open' for %s",
                rec_id,
            )
    except Exception as exc:
        logger.warning("[CLEAN_SLATE] Failed to reset rec status: %s", exc)

    logger.info("[CLEAN_SLATE] Cleanup complete for %s", rec_id)
