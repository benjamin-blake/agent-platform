# complexity-waiver: decision-43
"""Recommendation executor — thin CLI entrypoint.

The implementation logic is split across scripts/executor/ submodules:
  errors      — Structured error types and enums
  jsonl_store — Unified JSONL read/write
  plan        — Plan generation, critique, parsing
  step_runner — Step implementation and acceptance verification
  postflight  — Finalisation, CI wait, merge, cleanup
  ci_triage   — Deterministic CI failure classification

This file retains orchestration-level logic only:
  is_eligible(), ensure_feature_branch(),
  execute_recommendation(), _execute_recommendation_inner(),
  get_eligible_recs(), topological_sort_recs(), execute_batch(), main()

Intent document: docs/INTENT-recommendation-executor.md
"""

import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, TypedDict

from scripts.execution_state import clear_checkpoint, load_checkpoint, save_checkpoint
from scripts.executor.jsonl_store import (
    RECS_JSONL,  # noqa: F401
    _reset_rec_status,
    load_all_recommendations,
    load_recommendation,
    update_recommendation_status,
)
from scripts.executor.plan import (  # noqa: F401  (re-exported for backward compat)
    ExecutionPlan,
    _detect_critique_cycling,
    critique_plan,
    escalate_planning_model,
    generate_compound_plan,
    generate_initial_plan,
    get_latest_plan,
    get_planning_model,
    load_prompt,
    parse_steps_from_plan,
    refine_plan,
    save_plan,
)
from scripts.executor.postflight import (
    _code_review_gate,
    _commits_ahead_of_main,
    _fix_ci_failure,  # noqa: F401
    _fix_code_review_findings,
    _get_ci_failure_details,  # noqa: F401
    _handle_failure,
    _scope_drift_check,
    cleanup_after_merge,  # noqa: F401
    finalize,
    merge_pr,  # noqa: F401
    wait_for_ci,  # noqa: F401
)
from scripts.executor.step_runner import (
    StepOutcome,
    _append_step_telemetry,
    commit_step,
    gather_step_context,  # noqa: F401
    get_implementation_model,  # noqa: F401
    get_last_acceptance_output,
    implement_step,
    run_acceptance,
    run_verification,
)
from scripts.executor.telemetry import (
    close_phase,
    close_session,
    emit_process_event,
    open_phase,
    open_session,
)
from scripts.llm_utils import (
    MODEL_EXECUTION,
    LLMResponseError,
    _assign_job_object,
    check_process_killswitch,
    check_recursion_guard,
    kill_process_tree,
)

logger = logging.getLogger(__name__)


# Explicit postflight quarantine for baseline-red tests already reproduced
# outside the current rec branch. This is only consulted in the local
# postflight validation path and is recorded in the run summary when used.
_POSTFLIGHT_VALIDATION_QUARANTINE = {
    "tests/test_execute_recommendation.py::TestPlanningContextInjection::test_empty_context_does_not_fail": (
        "Known planner-context baseline failure reproduced outside the current rec branch"
    ),
}


def _extract_validation_failed_checks(validate_output: str) -> list[str]:
    """Parse the blocking check names from validate.py summary output."""
    failed_checks: list[str] = []
    in_failed_checks = False

    for raw_line in validate_output.splitlines():
        stripped = raw_line.strip()
        if stripped == "Failed checks:":
            in_failed_checks = True
            continue
        if not in_failed_checks:
            continue
        if stripped.startswith("- "):
            failed_checks.append(stripped[2:].strip())
            continue
        if failed_checks and (not stripped or stripped.startswith("Fix all failures") or stripped.startswith("===")):
            break

    return failed_checks


def _extract_failed_pytest_nodes(validate_output: str) -> list[str]:
    """Extract pytest node IDs from validate.py output."""
    failed_nodes: list[str] = []

    for raw_line in validate_output.splitlines():
        stripped = raw_line.strip()
        if not stripped.startswith("FAILED "):
            continue
        node_id = stripped[len("FAILED ") :].split(" - ", 1)[0].strip()
        if node_id:
            failed_nodes.append(node_id.replace("\\", "/"))

    return failed_nodes


def _get_quarantined_validation_failures(validate_output: str) -> list[str]:
    """Return known baseline-red pytest failures eligible for postflight quarantine."""
    failed_checks = _extract_validation_failed_checks(validate_output)
    if failed_checks != ["Unit tests + coverage"]:
        return []

    failed_nodes = sorted(set(_extract_failed_pytest_nodes(validate_output)))
    if not failed_nodes:
        return []

    if any(node not in _POSTFLIGHT_VALIDATION_QUARANTINE for node in failed_nodes):
        return []

    return failed_nodes


# ---------------------------------------------------------------------------
# Acceptance feasibility validation (extracted to scripts/executor/acceptance_lint.py)
# ---------------------------------------------------------------------------

from scripts.executor.acceptance_lint import (  # noqa: E402, F401
    AcceptanceFeasibility,
    _check_acceptance_on_main,
    _checkout_main_safely,
    lint_acceptance_command,
    validate_acceptance_feasibility,
)

# ---------------------------------------------------------------------------
# Telemetry helpers
# ---------------------------------------------------------------------------


def _capture_executor_telemetry(
    *,
    rec_id: str,
    branch: str,
    outcome: str,
    failure_reason: Optional[str],
    steps_completed: int,
    total_steps: int,
    plan: object = None,
) -> None:
    """No-op stub -- telemetry now written by scripts/executor/telemetry.py (Phase B).

    The 10+ call sites are retained to avoid a large cascading refactor; they
    now call a harmless no-op.  Full removal is tracked as a follow-up refactor.
    """
    return  # deliberately empty


def write_run_summary(
    rec_id: str,
    branch: str,
    outcome: str,
    failure_reason: Optional[str],
    steps_completed: int,
    total_steps: int,
    plan: Optional[ExecutionPlan] = None,
    current_phase: str = "",
    postflight_validation: Optional[dict] = None,
    acceptance_output: Optional[str] = None,
) -> None:
    """Write per-run summary artifact to logs/runs/{rec_id}-{timestamp}.json.

    Captures outcome, timing, premium request cost, per-step telemetry,
    and optional structured postflight validation metadata.

    Args:
        postflight_validation: Optional dict with keys ``mode``
            (e.g. ``""`` for presubmit, ``"--pre"`` for edit-loop), ``result``
            (``"pass"``/``"fail"``/``"timeout"``/``"error"``),
            ``returncode``, and ``fallback_mode`` when a doc-only
            fallback was attempted. Omitted from the summary when
            ``None`` so that non-postflight callers are unaffected.
    """
    import json

    if os.environ.get("PYTEST_CURRENT_TEST"):
        logger.warning(
            "Skipping run summary for %s (PYTEST_CURRENT_TEST set)",
            rec_id,
        )
        return

    timestamp_now = datetime.now(timezone.utc)
    run_dir = Path("logs/runs")
    run_dir.mkdir(parents=True, exist_ok=True)

    # Load per-step outcomes from .execution-step-telemetry.jsonl
    per_step_outcomes = []
    step_telemetry_path = Path("logs/.execution-step-telemetry.jsonl")
    if step_telemetry_path.exists():
        with open(step_telemetry_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                entry = json.loads(line)
                if entry.get("rec_id") == rec_id:
                    per_step_outcomes.append(
                        {
                            "step_n": entry.get("step_n"),
                            "outcome": entry.get("outcome"),
                            "model": entry.get("model"),
                        }
                    )

    summary: dict = {
        "rec_id": rec_id,
        "branch": branch,
        "outcome": outcome,
        "timestamp_start": timestamp_now.isoformat(),
        "timestamp_end": timestamp_now.isoformat(),
        "phase_completed": current_phase or outcome,
        "steps_completed": steps_completed,
        "total_steps": total_steps,
        "failure_reason": failure_reason,
        "per_step_outcomes": per_step_outcomes,
    }
    if postflight_validation is not None:
        summary["postflight_validation"] = postflight_validation
    if acceptance_output is not None:
        summary["acceptance_output"] = acceptance_output

    filename = run_dir / f"{rec_id}-{timestamp_now.strftime('%Y%m%dT%H%M%S')}.json"
    with open(filename, "w", encoding="utf-8", errors="replace") as f:
        json.dump(summary, f, indent=2)
    logger.info("[TELEMETRY] Run summary written to %s", filename)


# ---------------------------------------------------------------------------
# Structured failure summaries
# ---------------------------------------------------------------------------


class FailureSummary(TypedDict, total=False):
    """Structured snapshot of a single executor failure."""

    rec_id: str
    attempt: int
    failure_phase: str
    failure_class: str
    last_transcript_path: str
    git_diff_stat: str
    validation_output: str
    acceptance_output: str
    failure_reason: str


def _get_git_diff_stat() -> str:
    """Best-effort capture of ``git diff --stat HEAD``."""
    try:
        result = subprocess.run(
            ["git", "diff", "--stat", "HEAD"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return ""


def _infer_failure_class(
    failure_phase: str,
    failure_reason: str,
) -> str:
    """Heuristically classify the failure from reason text."""
    reason_lower = failure_reason.lower() if failure_reason else ""
    if "timeout" in reason_lower or "timed out" in reason_lower:
        return "cli_timeout"
    if "parse" in reason_lower or "json" in reason_lower:
        return "parse_error"
    if "test" in reason_lower or "pytest" in reason_lower or "validation failed" in reason_lower:
        return "test_failure"
    if "scope" in reason_lower or "drift" in reason_lower:
        return "scope_creep"
    if "ghost" in reason_lower:
        return "ghost_step"
    if "acceptance" in reason_lower:
        return "acceptance_mismatch"
    return "unknown"


def _latest_transcript_path(rec_id: str) -> str:
    """Return the most recent transcript path for *rec_id*."""
    transcript_dir = Path("logs/transcripts")
    if not transcript_dir.exists():
        return ""
    candidates = sorted(
        transcript_dir.glob(f"{rec_id}*"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return str(candidates[0]) if candidates else ""


def emit_failure_summary(
    *,
    rec_id: str,
    failure_phase: str,
    failure_reason: str,
    attempt: int = 1,
    failure_class: str = "",
    validation_output: str = "",
    acceptance_output: str = "",
) -> None:
    """Write a structured failure summary JSON file.

    Skipped when ``PYTEST_CURRENT_TEST`` is set (mirrors
    ``write_run_summary`` behaviour).
    """
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return

    if not failure_class:
        failure_class = _infer_failure_class(
            failure_phase,
            failure_reason,
        )

    summary: FailureSummary = {
        "rec_id": rec_id,
        "attempt": attempt,
        "failure_phase": failure_phase,
        "failure_class": failure_class,
        "last_transcript_path": _latest_transcript_path(rec_id),
        "git_diff_stat": _get_git_diff_stat(),
        "validation_output": (validation_output[:2000] if validation_output else ""),
        "acceptance_output": (acceptance_output[:2000] if acceptance_output else ""),
        "failure_reason": (failure_reason[:1000] if failure_reason else ""),
    }

    out_dir = Path("logs/failure-summaries")
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    out_path = out_dir / f"{rec_id}-{ts}.json"
    with open(out_path, "w", encoding="utf-8", errors="replace") as f:
        json.dump(summary, f, indent=2)
    logger.info(
        "[FAILURE-SUMMARY] Written to %s",
        out_path,
    )


# ---------------------------------------------------------------------------
# Session status dashboard
# ---------------------------------------------------------------------------


def print_session_status(*, root: Optional[Path] = None) -> None:
    """Print an aggregated session dashboard from today's run summaries.

    Args:
        root: Repository root directory. Defaults to cwd.
    """
    base = root or Path(".")
    today_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    run_dir = base / "logs" / "runs"

    # -- (a) Aggregate run summaries for today --
    recs_attempted: set[str] = set()
    recs_closed: set[str] = set()
    recs_failed: set[str] = set()
    first_ts: Optional[datetime] = None

    if run_dir.exists():
        for fpath in sorted(run_dir.glob("*.json")):
            if today_str not in fpath.stem:
                continue
            try:
                data = json.loads(fpath.read_text(encoding="utf-8", errors="replace"))
            except (json.JSONDecodeError, OSError):
                continue
            rid = data.get("rec_id", "")
            recs_attempted.add(rid)
            outcome = data.get("outcome", "")
            if outcome == "success":
                recs_closed.add(rid)
            elif outcome in ("failure", "error"):
                recs_failed.add(rid)
            ts_str = data.get("timestamp_start")
            if ts_str:
                try:
                    ts = datetime.fromisoformat(ts_str)
                    if first_ts is None or ts < first_ts:
                        first_ts = ts
                except ValueError:
                    pass

    # -- (b) Friction recs drafted today --
    friction_count = 0
    recs_jsonl = base / "logs" / ".recommendations-log.jsonl"
    if recs_jsonl.exists():
        for line in recs_jsonl.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("source") == "executor-supervision" and entry.get("date", "").replace("-", "") == today_str:
                friction_count += 1

    # -- (c) Hotfix commits today --
    hotfix_count = 0
    try:
        result = subprocess.run(
            [
                "git",
                "--no-pager",
                "log",
                "--oneline",
                "--all",
                "--since=midnight",
                "--grep=hotfix",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        if result.returncode == 0:
            hotfix_count = len([ln for ln in result.stdout.splitlines() if ln.strip()])
    except (subprocess.TimeoutExpired, OSError):
        pass

    # -- (d) Machinery failure ratio --
    total_runs = len(recs_attempted) if recs_attempted else 0
    fail_count = len(recs_failed)
    ratio = f"{fail_count}/{total_runs}" if total_runs else "n/a"

    # -- (e) Elapsed time --
    if first_ts is not None:
        now = datetime.now(timezone.utc)
        if first_ts.tzinfo is None:
            first_ts = first_ts.replace(tzinfo=timezone.utc)
        elapsed = now - first_ts
        hours, remainder = divmod(int(elapsed.total_seconds()), 3600)
        minutes = remainder // 60
        elapsed_str = f"{hours}h {minutes}m"
    else:
        elapsed_str = "n/a"

    # -- Print dashboard --
    print("=== Executor Session Status ===")
    print(f"Recs attempted: {total_runs}  closed: {len(recs_closed)}  failed: {fail_count}")
    print(f"Friction recs drafted: {friction_count}")
    print(f"Hotfix commits: {hotfix_count}")
    print(f"Machinery failure ratio: {ratio}")
    print(f"Elapsed since first run: {elapsed_str}")


# ---------------------------------------------------------------------------
# Eligibility and branch management
# ---------------------------------------------------------------------------


def _discard_commit_range_files(num_commits: int) -> None:
    """Discard working tree changes for all files modified in a commit range.

    Uses git show to list files modified in HEAD~{num_commits}..HEAD,
    then runs git checkout -- on each file to discard working tree changes.

    Args:
        num_commits: Number of commits to look back from HEAD.
    """
    try:
        result = subprocess.run(
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
                subprocess.run(
                    ["git", "checkout", "--", file_path],
                    check=True,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=10,
                )
            except subprocess.TimeoutExpired:
                logger.warning("[DISCARD] Timeout discarding changes for %s", file_path)
            except Exception as e:
                logger.warning("[DISCARD] Failed to discard changes for %s: %s", file_path, e)

    except subprocess.TimeoutExpired:
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
    from scripts.llm_client import llm_call

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
    try:
        result = subprocess.run(
            ["git", "merge-base", "--is-ancestor", branch, "main"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        logger.warning("Timeout checking if %s is ancestor of main", branch)
        return False
    except Exception as e:
        logger.warning("Error checking if %s is ancestor of main: %s", branch, e)
        return False


def is_eligible(rec: dict, recs_by_id: dict[str, dict] | None = None) -> bool:
    """Check if recommendation is eligible for execution.

    Returns True only if risk==low, automatable==True, status is not
    closed/failed/declined, and all dependency IDs resolve to closed entries.
    Missing dependency IDs are treated as unresolved (conservative).
    """
    status = rec.get("status", "open")
    if status in ("closed", "failed", "declined"):
        return False
    if not (rec.get("risk") == "low" and rec.get("automatable") is True):
        return False

    # Effort gate: only XS/S recs are eligible for automated execution
    if rec.get("effort", "M") not in ("XS", "S"):
        return False

    # SLOC gate: target files over 800 SLOC exceed the context budget
    target_file = rec.get("file", "")
    if target_file and Path(target_file).exists():
        sloc = sum(1 for line in Path(target_file).read_text(encoding="utf-8").splitlines() if line.strip())
        if sloc > 800:
            return False

    dependencies: list[str] = rec.get("dependencies", [])
    if not dependencies:
        return True

    if recs_by_id is None:
        recs_by_id = load_all_recommendations()

    for dep_id in dependencies:
        dep = recs_by_id.get(dep_id)
        if dep is None or dep.get("status") != "closed":
            return False

    return True


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
    jsonl_path = "logs/.recommendations-log.jsonl"
    try:
        result = subprocess.run(
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
    except subprocess.TimeoutExpired:
        logger.warning("[PREFLIGHT] Timeout checking uncommitted recommendations log state")
        return False
    except Exception as exc:
        logger.warning("[PREFLIGHT] Failed to check uncommitted recommendations log: %s", exc)
        return False


def ensure_feature_branch(rec_id: str) -> bool:
    """Create agent/{rec_id} branch from main if needed. Returns True if ready."""
    expected_branch = f"agent/{rec_id}"
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        current = result.stdout.strip()

        if current == "main":
            if not _check_jsonl_clean():
                print("ERROR: Recommendations JSONL has uncommitted changes -- commit or stash before branching")
                return False
            logger.info("[BRANCH] On main, creating branch %s", expected_branch)
            subprocess.run(
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
                subprocess.run(
                    ["git", "checkout", "-b", expected_branch],
                    check=True,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
                logger.info("[BRANCH] Created new branch %s", expected_branch)
            except subprocess.CalledProcessError as branch_err:
                if branch_err.returncode == 128:
                    logger.info(
                        "[BRANCH] Branch %s already exists -- checking it out (previous aborted run detected)",
                        expected_branch,
                    )
                    subprocess.run(
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
    except subprocess.CalledProcessError as e:
        logger.error("[BRANCH] Git operation failed: %s", e)
        return False


def prune_merged_agent_branches() -> None:
    """Delete local agent/ branches whose tips are ancestors of main (already merged)."""
    try:
        list_result = subprocess.run(
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
                is_ancestor = subprocess.run(
                    ["git", "merge-base", "--is-ancestor", branch, "main"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
                if is_ancestor.returncode == 0:
                    delete_result = subprocess.run(
                        ["git", "branch", "-d", branch],
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                    )
                    if delete_result.returncode == 0:
                        logger.info("[PRUNE] Deleted merged branch: %s", branch)
                        remote_delete_result = subprocess.run(
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
            except subprocess.CalledProcessError:
                continue
    except subprocess.CalledProcessError:
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
    branch_name = f"agent/rec-{rec_id}-hotfix-{slug}"
    subprocess.run(
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


# ---------------------------------------------------------------------------
# Retry cleanup
# ---------------------------------------------------------------------------


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
    branch = f"agent/{rec_id}"
    logger.info("[CLEAN_SLATE] Starting cleanup for %s", rec_id)

    # (a) Delete local branch if it exists
    try:
        result = subprocess.run(
            ["git", "branch", "--list", branch],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        if result.stdout.strip():
            subprocess.run(
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
        subprocess.run(
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
        cp = load_checkpoint()
        if cp is not None and cp.get("plan_file") == rec_id:
            clear_checkpoint()
            logger.info(
                "[CLEAN_SLATE] Cleared stale checkpoint for %s",
                rec_id,
            )
    except Exception as exc:
        logger.warning("[CLEAN_SLATE] Failed to clear checkpoint: %s", exc)

    # (d) Close any open draft PRs for the branch
    try:
        subprocess.run(
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
        rec = load_recommendation(rec_id)
        if rec is not None and rec.get("status") == "failed":
            _reset_rec_status(rec_id)
            logger.info(
                "[CLEAN_SLATE] Reset status to 'open' for %s",
                rec_id,
            )
    except Exception as exc:
        logger.warning("[CLEAN_SLATE] Failed to reset rec status: %s", exc)

    logger.info("[CLEAN_SLATE] Cleanup complete for %s", rec_id)


# ---------------------------------------------------------------------------
# Main executor
# ---------------------------------------------------------------------------


def execute_recommendation(
    rec_id: str,
    step_limit: Optional[int] = None,
    skip_critique: bool = False,
    no_merge: bool = False,
    no_review: bool = False,
    restart: bool = False,
    resume: bool = False,
    resume_postflight: bool = False,
    fast_mode: bool = False,
    plan_json: Optional[str] = None,
    auto_resume: bool = False,
) -> bool:
    """Main executor with atomized plan/critique/execute flow.

    Args:
        rec_id: The recommendation ID to execute (e.g., 'rec-009')
        step_limit: Implement only first N steps (for inspection)
        skip_critique: Skip plan critique loop
        no_merge: If True, stop after PR creation without CI wait or merging
        no_review: If True, skip the code review gate
        restart: If True, clear any existing checkpoint before execution
        resume: If True, resume from existing checkpoint
        resume_postflight: If True, skip plan/impl phases and jump
            straight to postflight (requires prior IMPL_COMPLETE checkpoint)
        fast_mode: If True, skip planning, critique, and code review.
            Requires a prebuilt plan via *plan_json* or stdin.
        plan_json: JSON string containing a prebuilt 1-step plan for
            fast mode. When *fast_mode* is True and this is None, the
            plan is read from stdin.
        auto_resume: If True, read checkpoint status and dispatch to the
            correct phase automatically. Mutually exclusive with --resume
            and --resume-postflight.

    Flow:
        1. PREFLIGHT: Load rec, check eligibility, ensure branch
        2. PLAN: Generate initial plan via CLI, save to JSONL
           (skipped in fast mode -- uses supplied plan)
        3. CRITIQUE LOOP: Critique and refine until approved
           (skipped in fast mode)
        4. IMPL LOOP: Execute each step via CLI, validate, commit, checkpoint
        5. POSTFLIGHT: Push, create PR, (optionally) wait for CI and merge
           (code review skipped in fast mode)
    """
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    try:
        return _execute_recommendation_inner(
            rec_id,
            step_limit,
            skip_critique,
            no_merge,
            no_review,
            restart,
            resume,
            resume_postflight,
            fast_mode=fast_mode,
            plan_json=plan_json,
            auto_resume=auto_resume,
        )
    except LLMResponseError as exc:
        try:
            print(f"\nERROR: {exc}")
        except UnicodeEncodeError:
            print(f"\nERROR: {str(exc).encode('ascii', errors='replace').decode('ascii')}")
        return False
    except subprocess.TimeoutExpired as exc:
        print(f"\nERROR: CLI timed out after {exc.timeout}s")
        return False


def _execute_recommendation_inner(
    rec_id: str,
    step_limit: Optional[int],
    skip_critique: bool,
    no_merge: bool = False,
    no_review: bool = False,
    restart: bool = False,
    resume: bool = False,
    resume_postflight: bool = False,
    fast_mode: bool = False,
    plan_json: Optional[str] = None,
    auto_resume: bool = False,
) -> bool:
    """Inner implementation -- LLMResponseError propagates to execute_recommendation."""

    steps_completed: int = 0
    total_steps: int = 0
    failure_step: Optional[int] = None
    failure_reason: Optional[str] = None
    plan: Optional["ExecutionPlan"] = None
    branch: str = f"agent/{rec_id}"

    open_session(workflow="executor", rec_ids=[rec_id], branch=branch, execution_attempt=1)

    # ========== PHASE 1: PREFLIGHT ==========
    _phase_sep = "=" * 60
    print("\n" + _phase_sep)
    print("PHASE 1: PREFLIGHT")
    print(_phase_sep)
    logger.info("[PHASE] PREFLIGHT started -- rec_id=%s", rec_id)
    open_phase(phase="preflight", phase_order=1)

    # ------ Read-only gates (no git side effects) ------

    rec = load_recommendation(rec_id)
    if not rec:
        print(f"ERROR: Recommendation {rec_id} not found")
        write_run_summary(
            rec_id,
            f"agent/{rec_id}",
            "preflight_fail",
            f"Recommendation {rec_id} not found",
            steps_completed,
            total_steps,
            plan,
            "preflight",
        )
        emit_failure_summary(
            rec_id=rec_id,
            failure_phase="preflight",
            failure_reason=f"Recommendation {rec_id} not found",
        )
        close_phase(outcome="failed")
        close_session(
            outcome="failed",
            failure_phase="preflight",
            failure_reason=f"Recommendation {rec_id} not found",
        )
        return False

    acceptance_cmd = rec.get("acceptance", "")
    verification_cmd = rec.get("verification", "")
    if acceptance_cmd:
        lint_ok, lint_error = lint_acceptance_command(acceptance_cmd)
        if not lint_ok:
            print(lint_error)
            write_run_summary(
                rec_id,
                branch,
                "preflight_fail",
                f"Acceptance command lint failed: {lint_error}",
                steps_completed,
                total_steps,
                plan,
                "preflight",
            )
            emit_failure_summary(
                rec_id=rec_id,
                failure_phase="preflight",
                failure_reason=(f"Acceptance command lint failed: {lint_error}"),
            )
            close_phase(outcome="failed")
            close_session(
                outcome="failed",
                failure_phase="preflight",
                failure_reason=f"Acceptance command lint failed: {lint_error}",
            )
            return False

        feasibility, reason = validate_acceptance_feasibility(
            acceptance_cmd,
        )
        if feasibility == AcceptanceFeasibility.INFEASIBLE:
            print(f"ERROR: Acceptance command references non-existent files: {reason}")
            update_recommendation_status(
                rec_id,
                {"status": "failed"},
            )
            write_run_summary(
                rec_id,
                branch,
                "preflight_fail",
                f"acceptance_infeasible: {reason}",
                steps_completed,
                total_steps,
                plan,
                "preflight",
            )
            emit_failure_summary(
                rec_id=rec_id,
                failure_phase="preflight",
                failure_reason=f"acceptance_infeasible: {reason}",
            )
            close_phase(outcome="failed")
            close_session(
                outcome="failed",
                failure_phase="preflight",
                failure_reason=f"acceptance_infeasible: {reason}",
            )
            return False

    print(
        f"Recommendation: {rec.get('title')}",
    )
    print(
        f"Risk: {rec.get('risk', 'unclassified')} | Automatable: {rec.get('automatable', False)}",
    )

    if not is_eligible(rec):
        print(
            "ERROR: Not eligible (must be risk=low AND automatable=true)",
        )
        write_run_summary(
            rec_id,
            branch,
            "preflight_fail",
            "Not eligible (must be risk=low AND automatable=true)",
            steps_completed,
            total_steps,
            plan,
            "preflight",
        )
        emit_failure_summary(
            rec_id=rec_id,
            failure_phase="preflight",
            failure_reason=("Not eligible (risk=low AND automatable=true)"),
        )
        close_phase(outcome="failed")
        close_session(
            outcome="failed",
            failure_phase="preflight",
            failure_reason="Not eligible (risk=low AND automatable=true)",
        )
        return False

    if _is_poisoned_rec(rec_id):
        _reason = f"Skipping {rec_id}: an open executor-postmortem exists. Set ALLOW_POISONED_RECS=true to override."
        print(f"ERROR: {_reason}")
        logger.warning("[PREFLIGHT] %s", _reason)
        write_run_summary(rec_id, branch, "preflight_fail", _reason, steps_completed, total_steps, plan, "preflight")
        emit_failure_summary(rec_id=rec_id, failure_phase="preflight", failure_reason=_reason)
        close_phase(outcome="failed")
        close_session(outcome="failed", failure_phase="preflight", failure_reason=_reason)
        return False

    # Checkpoint / --resume-postflight conflict handling
    resume_from_step: int = 0
    checkpoint = load_checkpoint()
    if checkpoint is not None:
        if checkpoint.get("plan_file") == rec_id:
            resume_from_step = checkpoint.get("current_step", 0)
            print(
                f"[CHECKPOINT] Resuming {rec_id} from step {resume_from_step + 1}",
            )
        elif resume or resume_postflight:
            stale_plan_file = checkpoint.get("plan_file")
            clear_checkpoint()
            checkpoint = None
            logger.info(
                "[CHECKPOINT] Cleared stale checkpoint for '%s' due to --resume/--resume-postflight",
                stale_plan_file,
            )
        else:
            checkpoint_branch = f"agent/{checkpoint.get('plan_file')}"
            if _is_checkpoint_branch_merged(checkpoint_branch):
                clear_checkpoint()
                logger.info(
                    "[CHECKPOINT] Cleared checkpoint for '%s' — branch has been merged to main",
                    checkpoint.get("plan_file"),
                )
            else:
                print(
                    f"ERROR: Checkpoint exists for different "
                    f"rec '{checkpoint.get('plan_file')}'. "
                    f"Use --restart to clear it before "
                    f"executing {rec_id}."
                )
                write_run_summary(
                    rec_id,
                    f"agent/{rec_id}",
                    "preflight_fail",
                    f"Checkpoint exists for different rec '{checkpoint.get('plan_file')}'",
                    steps_completed,
                    total_steps,
                    plan,
                    "preflight",
                )
                emit_failure_summary(
                    rec_id=rec_id,
                    failure_phase="preflight",
                    failure_reason=(f"Checkpoint exists for different rec '{checkpoint.get('plan_file')}'"),
                )
                close_phase(outcome="failed")
                close_session(
                    outcome="failed",
                    failure_phase="preflight",
                    failure_reason=f"Checkpoint exists for different rec '{checkpoint.get('plan_file')}'",
                )
                return False

    skip_to_postflight = False
    if resume_postflight:
        if checkpoint is not None and checkpoint.get("plan_file") == rec_id and checkpoint.get("status") == "IMPL_COMPLETE":
            steps_completed = checkpoint.get("current_step", 0)
            total_steps = checkpoint.get("total_steps", 0)
            plan = get_latest_plan(rec_id)
            if plan is None:
                failure_reason = "resume-postflight requires an existing plan for checkpointed recommendation"
                print(f"ERROR: {failure_reason}")
                write_run_summary(
                    rec_id,
                    branch,
                    "preflight_fail",
                    failure_reason,
                    steps_completed,
                    total_steps,
                    plan,
                    "preflight",
                )
                emit_failure_summary(
                    rec_id=rec_id,
                    failure_phase="preflight",
                    failure_reason=failure_reason,
                )
                close_phase(outcome="failed")
                close_session(
                    outcome="failed",
                    failure_phase="preflight",
                    failure_reason=failure_reason,
                )
                return False
            skip_to_postflight = True
            print(
                f"[RESUME-POSTFLIGHT] Skipping phases 2-4, jumping to postflight ({steps_completed}/{total_steps} steps)",
            )
        else:
            cp_status = checkpoint.get("status") if checkpoint else None
            print(
                f"ERROR: --resume-postflight requires an IMPL_COMPLETE checkpoint for {rec_id} (found: {cp_status})",
            )
            write_run_summary(
                rec_id,
                branch,
                "preflight_fail",
                "resume-postflight without IMPL_COMPLETE checkpoint",
                steps_completed,
                total_steps,
                plan,
                "preflight",
            )
            emit_failure_summary(
                rec_id=rec_id,
                failure_phase="preflight",
                failure_reason=("resume-postflight without IMPL_COMPLETE checkpoint"),
            )
            close_phase(outcome="failed")
            close_session(
                outcome="failed",
                failure_phase="preflight",
                failure_reason="resume-postflight without IMPL_COMPLETE checkpoint",
            )
            return False

    skip_to_finalize: bool = False
    if auto_resume and checkpoint is not None and checkpoint.get("plan_file") == rec_id:
        cp_status = checkpoint.get("status", "")
        if cp_status == "CI_PENDING":
            skip_to_postflight = True
            skip_to_finalize = True
            steps_completed = checkpoint.get("current_step", 0)
            total_steps = checkpoint.get("total_steps", 0)
            plan = get_latest_plan(rec_id)
            logger.info("[AUTO-RESUME] Status=%s -- jumping to CI poll + merge", cp_status)
            print(f"[AUTO-RESUME] Detected status={cp_status} -- jumping to CI poll + merge")
        elif cp_status == "REVIEW_COMPLETE":
            skip_to_postflight = True
            skip_to_finalize = True
            steps_completed = checkpoint.get("current_step", 0)
            total_steps = checkpoint.get("total_steps", 0)
            plan = get_latest_plan(rec_id)
            logger.info("[AUTO-RESUME] Status=%s -- jumping to push + PR + CI", cp_status)
            print(f"[AUTO-RESUME] Detected status={cp_status} -- jumping to push + PR + CI")
        elif cp_status == "IMPL_COMPLETE":
            skip_to_postflight = True
            steps_completed = checkpoint.get("current_step", 0)
            total_steps = checkpoint.get("total_steps", 0)
            plan = get_latest_plan(rec_id)
            logger.info("[AUTO-RESUME] Status=%s -- jumping to postflight", cp_status)
            print(f"[AUTO-RESUME] Detected status={cp_status} -- jumping to postflight (code review)")
        elif cp_status == "PLAN_COMPLETE":
            resume_from_step = 0
            logger.info("[AUTO-RESUME] Status=%s -- jumping to implementation loop", cp_status)
            print(f"[AUTO-RESUME] Detected status={cp_status} -- jumping to implementation loop")
        elif cp_status == "IN_PROGRESS":
            resume_from_step = checkpoint.get("current_step", 0)
            logger.info("[AUTO-RESUME] Status=%s -- resuming from step %d", cp_status, resume_from_step + 1)
            print(f"[AUTO-RESUME] Detected status={cp_status} -- resuming from step {resume_from_step + 1}")

    # ------ Side-effecting preflight (git / cleanup) ------

    # Auto-cleanup: invoke clean_slate if prior run left stale state
    try:
        _pre_rec = load_recommendation(rec_id)
        _pre_cp = load_checkpoint()
        _needs_clean = False
        if _pre_rec is not None and _pre_rec.get("execution_result") == "failure":
            _needs_clean = True
        if _pre_cp is not None and _pre_cp.get("plan_file") == rec_id:
            _needs_clean = True
        if _needs_clean:
            logger.info(
                "[PREFLIGHT] Stale state detected for %s -- invoking clean_slate",
                rec_id,
            )
            clean_slate(rec_id)
    except Exception as _cs_exc:
        logger.warning(
            "[PREFLIGHT] clean_slate pre-check failed: %s",
            _cs_exc,
        )

    if restart:
        clear_checkpoint()
        logger.info(
            "[CHECKPOINT] Cleared checkpoint due to --restart flag",
        )
        _reset_rec_status(rec_id)

    if not ensure_feature_branch(rec_id):
        print("ERROR: Failed to set up feature branch")
        write_run_summary(
            rec_id,
            f"agent/{rec_id}",
            "preflight_fail",
            "Failed to set up feature branch",
            steps_completed,
            total_steps,
            plan,
            "preflight",
        )
        emit_failure_summary(
            rec_id=rec_id,
            failure_phase="preflight",
            failure_reason="Failed to set up feature branch",
        )
        close_phase(outcome="failed")
        close_session(
            outcome="failed",
            failure_phase="preflight",
            failure_reason="Failed to set up feature branch",
        )
        return False

    prune_merged_agent_branches()

    print("Preflight: OK")
    branch = f"agent/{rec_id}"

    # Warn if the script itself is stale relative to origin/main.
    try:
        _behind = subprocess.run(
            ["git", "rev-list", "--count", "HEAD..origin/main"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        _behind_n = int(_behind.stdout.strip()) if _behind.returncode == 0 else 0
        if _behind_n > 0:
            logger.warning(
                "[PREFLIGHT] This checkout is %d commit(s) "
                "behind origin/main. Pending bugfix PRs may "
                "not be active. Consider merging main first.",
                _behind_n,
            )
            print(
                f"WARNING: checkout is {_behind_n} commit(s) behind origin/main -- recent executor bugfixes may not be active."
            )
    except Exception:
        pass  # non-critical; never block execution

    if not skip_to_postflight:
        # Re-evaluate from commit history only when --resume-postflight
        # did not already set skip_to_postflight earlier.
        if not restart and resume_from_step == 0:
            commits_ahead = _commits_ahead_of_main()
            if commits_ahead > 0:
                # Validate: (1) target file touched, (2) max commits threshold
                target_file = rec.get("file", "")
                max_commits_ahead = 20

                # Check if target file is modified in any commit
                target_file_touched = False
                if target_file:
                    try:
                        result = subprocess.run(
                            ["git", "log", "origin/main..HEAD", "--name-only", "--oneline", "--", target_file],
                            capture_output=True,
                            text=True,
                            encoding="utf-8",
                            errors="replace",
                            timeout=15,
                        )
                        if result.returncode == 0 and result.stdout.strip():
                            target_file_touched = True
                    except Exception:
                        pass  # Continue with conservative default (False)

                # Only skip to postflight if validations pass
                if target_file_touched and commits_ahead <= max_commits_ahead:
                    logger.info(
                        "[PREFLIGHT] Branch is %d commit(s) ahead of origin/main -- skipping to postflight",
                        commits_ahead,
                    )
                    print(
                        f"[SKIP] Branch has {commits_ahead} commit(s) not on "
                        "origin/main -- previous work detected. "
                        "Skipping to postflight."
                    )
                    skip_to_postflight = True
                    steps_completed = commits_ahead
                else:
                    if not target_file_touched:
                        logger.warning(
                            "[PREFLIGHT] Branch has %d commit(s) but target "
                            "file %s not modified -- continuing with "
                            "normal workflow",
                            commits_ahead,
                            target_file,
                        )
                    if commits_ahead > max_commits_ahead:
                        logger.warning(
                            "[PREFLIGHT] Branch has %d commit(s) exceeding "
                            "max threshold of %d -- continuing with "
                            "normal workflow",
                            commits_ahead,
                            max_commits_ahead,
                        )

    # ========== FAST MODE: parse prebuilt plan ==========
    if fast_mode and not skip_to_postflight:
        raw_json = plan_json
        if raw_json is None:
            raw_json = sys.stdin.read()
        if not raw_json or not raw_json.strip():
            print("ERROR: --fast requires a plan via --plan-json or stdin")
            write_run_summary(
                rec_id,
                branch,
                "preflight_fail",
                "fast mode: no plan JSON provided",
                steps_completed,
                total_steps,
                plan,
                "preflight",
            )
            emit_failure_summary(
                rec_id=rec_id,
                failure_phase="preflight",
                failure_reason="fast mode: no plan JSON provided",
            )
            close_phase(outcome="failed")
            close_session(
                outcome="failed",
                failure_phase="preflight",
                failure_reason="fast mode: no plan JSON provided",
            )
            return False
        try:
            plan_payload = json.loads(raw_json)
        except json.JSONDecodeError as exc:
            print(f"ERROR: invalid plan JSON: {exc}")
            write_run_summary(
                rec_id,
                branch,
                "preflight_fail",
                f"fast mode: invalid JSON: {exc}",
                steps_completed,
                total_steps,
                plan,
                "preflight",
            )
            emit_failure_summary(
                rec_id=rec_id,
                failure_phase="preflight",
                failure_reason=f"fast mode: invalid JSON: {exc}",
                failure_class="parse_error",
            )
            close_phase(outcome="failed")
            close_session(
                outcome="failed",
                failure_phase="preflight",
                failure_reason=f"fast mode: invalid JSON: {exc}",
            )
            return False

        # Accept either a bare list of steps or a dict with a
        # "steps" key so callers can use the simplest format.
        if isinstance(plan_payload, list):
            fast_steps = plan_payload
        elif isinstance(plan_payload, dict):
            fast_steps = plan_payload.get("steps", [])
        else:
            fast_steps = []

        if not fast_steps:
            print("ERROR: plan JSON contains no steps")
            write_run_summary(
                rec_id,
                branch,
                "preflight_fail",
                "fast mode: plan JSON has no steps",
                steps_completed,
                total_steps,
                plan,
                "preflight",
            )
            emit_failure_summary(
                rec_id=rec_id,
                failure_phase="preflight",
                failure_reason=("fast mode: plan JSON has no steps"),
            )
            close_phase(outcome="failed")
            close_session(
                outcome="failed",
                failure_phase="preflight",
                failure_reason="fast mode: plan JSON has no steps",
            )
            return False

        # Normalise each step dict so downstream code finds the
        # keys it expects (n, title, file, action, description,
        # acceptance).
        normalised: list[dict] = []
        for idx, raw_step in enumerate(fast_steps, 1):
            normalised.append(
                {
                    "n": raw_step.get("n", idx),
                    "title": raw_step.get("title", f"Step {idx}"),
                    "file": raw_step.get("file", ""),
                    "action": raw_step.get("action", "modify"),
                    "description": raw_step.get("description", ""),
                    "acceptance": raw_step.get("acceptance", ""),
                }
            )

        plan = ExecutionPlan(
            rec_id=rec_id,
            slug=rec_id,
            revision=0,
            timestamp=datetime.now(timezone.utc).isoformat(),
            status="approved",
            model="fast-mode",
            tokens_used=0,
            steps=normalised,
            critique_history=[],
            plan_text=raw_json,
        )
        save_plan(plan)
        print(f"[FAST] Loaded prebuilt plan: {len(normalised)} step(s)")
        # Skip Phase 2 and Phase 3 entirely — jump to Phase 4.

    # ========== PHASE 2: PLAN GENERATION ==========
    close_phase(outcome="success")  # close preflight
    if not skip_to_postflight and not fast_mode:
        plan = None
        print("\n" + _phase_sep)
        print("PHASE 2: PLAN GENERATION")
        print(_phase_sep)
        logger.info("[PHASE] PLAN GENERATION started")
        open_phase(phase="plan_generation", phase_order=2)

        if resume_from_step > 0:
            plan = get_latest_plan(rec_id)
            if plan and plan.status in ("approved", "failed"):
                print(f"[CHECKPOINT] Reusing existing plan (revision {plan.revision}) for resume")

        if plan is None or plan.status not in ("approved", "failed", "acceptance_challenged", "no_changes_needed"):
            # Seed GEMINI.md into a warm Gemini session so the planning call and all
            # subsequent impl steps can resume from the cached context (saves ~50K cold-start
            # tokens per call).  No-op when provider is not gemini or seeding fails.
            # Skip entirely for XS/S effort: the resume overhead exceeds any savings for small tasks.
            _effort = rec.get("effort", "").upper()
            _resume_enabled = os.getenv("PLAN_SESSION_RESUME", "true").lower() not in ("false", "0")
            _base_session_id: str = ""
            from scripts.model_registry import resolve_provider

            if _resume_enabled and resolve_provider() == "gemini" and _effort not in ("XS", "S"):
                _base_session_id = _seed_gemini_session()
            elif _effort in ("XS", "S"):
                logger.info("[WARM] Skipping session seed for effort=%s (token cost optimisation)", _effort)

            # Retry plan generation with model escalation (up to 3 attempts).
            # escalate_planning_model() tracks per-rec failure count and returns
            # the next model tier after repeated failures. Empty string means
            # the hierarchy is exhausted and human intervention is required.
            _plan_model: Optional[str] = get_planning_model(rec.get("effort", ""))
            for _plan_attempt in range(3):
                try:
                    plan = generate_initial_plan(
                        rec,
                        model_override=_plan_model if _plan_attempt > 0 else None,
                        base_session_id=_base_session_id or None,
                    )
                    break
                except LLMResponseError as _plan_err:
                    if _plan_attempt < 2:
                        _next_model = escalate_planning_model(rec_id, _plan_model or "gpt-5.4")
                        logger.warning(
                            "[PLAN] Attempt %d failed — escalating to %s. Error: %s",
                            _plan_attempt + 1,
                            _next_model or "human-intervention",
                            str(_plan_err)[:200],
                        )
                        emit_process_event(
                            tier="decision",
                            category="model_escalation_plan",
                            severity="warning",
                            description=f"Escalating planning model to {_next_model or 'human-intervention'}",
                        )
                        if not _next_model:
                            emit_process_event(
                                tier="exception",
                                category="escalation_exhausted_plan",
                                severity="error",
                                description="Planning model escalation exhausted",
                            )
                            raise LLMResponseError(
                                f"[PLAN] Escalation exhausted for {rec_id} — human intervention required."
                            ) from _plan_err
                        _plan_model = _next_model
                    else:
                        raise
            if getattr(plan, "status", "") != "no_changes_needed":
                save_plan(plan)
            _token_budget = int(os.getenv("PLAN_TOKEN_BUDGET", "200000"))
            if _token_budget > 0 and (plan.tokens_used or 0) > _token_budget:
                _budget_reason = (
                    f"Plan token budget exceeded: {plan.tokens_used} > {_token_budget} "
                    f"(set PLAN_TOKEN_BUDGET env var to raise limit)"
                )
                logger.warning("[PLAN] %s", _budget_reason)
                print(f"[PLAN] BUDGET EXCEEDED: {_budget_reason}")
                emit_failure_summary(
                    rec_id=rec_id,
                    failure_phase="planning",
                    failure_reason=_budget_reason,
                    failure_class="budget_exceeded",
                )
                close_phase(outcome="failed")
                close_session(
                    outcome="failed",
                    failure_phase="plan_generation",
                    failure_reason=_budget_reason,
                )
                return False
            if plan.status == "acceptance_challenged":
                challenge_reason = rec.get("challenge_reason", "Acceptance command validation failed")
                logger.warning("[PLAN] Acceptance challenged: %s", challenge_reason)
                print(f"[PLAN] ACCEPTANCE CHALLENGED: {challenge_reason}")
                write_run_summary(
                    rec_id,
                    branch,
                    "acceptance_challenged",
                    challenge_reason,
                    steps_completed,
                    total_steps,
                    plan,
                    "plan",
                )
                emit_failure_summary(
                    rec_id=rec_id,
                    failure_phase="planning",
                    failure_reason=challenge_reason,
                    failure_class="acceptance_mismatch",
                )
                close_phase(outcome="failed")
                close_session(
                    outcome="failed",
                    failure_phase="plan_generation",
                    failure_reason=challenge_reason,
                )
                return False
            if plan.status == "no_changes_needed":
                print("[PLAN] Model indicates no changes needed -- may already be implemented.")
            else:
                print(f"Plan generated: {len(plan.steps)} steps")
                for step in plan.steps:
                    print(f"  Step {step['n']}: {step.get('title', 'untitled')} ({step.get('file', 'no file')})")

        if plan.status == "no_changes_needed":
            rec_acceptance = rec.get("acceptance", "")
            _shell_cmd_prefixes = (
                "python",
                "pytest",
                "grep",
                "git",
                "gh",
                "bash",
                "sh",
                "cat",
                "ls",
                "find",
                "echo",
                "wc",
                "awk",
                "sed",
                "test",
                "curl",
                "jq",
                "terraform",
            )
            rec_acceptance_clean = rec_acceptance.strip().strip("`")
            _looks_like_cmd = rec_acceptance_clean.startswith(tuple(_shell_cmd_prefixes))
            print("\n[NO CHANGES NEEDED] Model determined file already meets acceptance criteria.")
            if _looks_like_cmd:
                print("[NO CHANGES NEEDED] Verifying with shell acceptance check...")
                # Check for dirty working tree before running acceptance (exclude logs/ -- planner
                # always writes execution-plans.jsonl during planning; log changes are legitimate
                # planner artifacts and should not block acceptance verification)
                _diff_result = subprocess.run(
                    ["git", "diff", "--quiet", "HEAD", "--", ".", ":(exclude)logs/"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
                if _diff_result.returncode != 0:
                    raise LLMResponseError(
                        "[PLAN] Cannot verify acceptance: dirty tree detected. "
                        "Working tree has uncommitted changes from previous attempts. "
                        "Commit or stash changes, then re-run with --restart."
                    )
                if not run_acceptance(rec_acceptance):
                    raise LLMResponseError(
                        "[PLAN] Model produced no steps AND shell acceptance check failed. "
                        "Use --restart to force a fresh plan, or implement manually."
                    )
            else:
                print("[NO CHANGES NEEDED] Acceptance is prose (not runnable) -- trusting model verdict.")
            print("[ACCEPT] Marking recommendation complete.")
            update_recommendation_status(
                rec_id,
                {
                    "status": "closed",
                    "execution_result": "already_implemented",
                    "execution_date": datetime.now(timezone.utc).isoformat(),
                    "execution_branch": branch,
                    "execution_steps": 0,
                    "execution_steps_total": 0,
                },
            )
            clear_checkpoint()
            # Return to main and delete the empty feature branch (no commits were made)
            try:
                _checkout_main_safely()
                subprocess.run(
                    ["git", "branch", "-d", branch],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=10,
                )
                logger.info("[CLEANUP] Returned to main, deleted empty branch %s", branch)
            except subprocess.CalledProcessError as _cleanup_err:
                logger.warning("[CLEANUP] Could not return to main (non-fatal): %s", _cleanup_err)
            write_run_summary(
                rec_id,
                branch,
                "already_implemented",
                None,
                steps_completed,
                total_steps,
                plan,
                "plan",
            )
            emit_process_event(
                tier="decision",
                category="no_changes_needed",
                severity="info",
                description="Model determined no changes needed -- already implemented",
            )
            close_phase(outcome="success")
            close_session(outcome="success")
            return True

    # ========== PHASE 3: CRITIQUE LOOP ==========
    close_phase(outcome="success")  # close plan_generation
    if not skip_to_postflight and not fast_mode:
        print("\n" + _phase_sep)
        print("PHASE 3: CRITIQUE LOOP")
        print(_phase_sep)
        logger.info("[PHASE] CRITIQUE LOOP started")
        open_phase(phase="critique", phase_order=3)

        if resume_from_step > 0 and plan.status == "approved":
            print("[CHECKPOINT] Skipping critique loop -- plan already approved")
        elif skip_critique or plan.status == "no_changes_needed":
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
                emit_process_event(
                    tier="rework",
                    category="critique_needs_revision",
                    severity="info",
                    description=f"Critique iteration {iteration + 1}: plan needs revision",
                )
                if _detect_critique_cycling(plan.critique_history):
                    print("[CRITIQUE-CYCLING] Cycling detected -- auto-approving plan to break loop")
                    emit_process_event(
                        tier="exception",
                        category="critique_cycling_detected",
                        severity="warning",
                        description="Cycling detected, auto-approving",
                    )
                    plan.status = "approved"
                    if getattr(plan, "status", "") != "no_changes_needed":
                        save_plan(plan)
                    break

                if iteration < max_revisions - 1:
                    plan = refine_plan(plan, critique, rec)
            else:
                raise LLMResponseError(
                    f"Plan still needs revision after {max_revisions} critique iteration(s). "
                    "Increase PLAN_MAX_REVISIONS or use --skip-critique to override."
                )

    # ========== PHASE 4: IMPLEMENTATION LOOP ==========
    close_phase(outcome="success")  # close critique

    # Post-planning dirty-tree guard: planning runs with tools=True (yolo) for
    # session-chaining but is prompt-instructed not to edit files.  If the LLM
    # disobeyed, catch it here BEFORE implementation starts to prevent cascading
    # scope creep.  Exclude logs/ (legitimate planner artifacts).
    if not skip_to_postflight:
        _dirty_check = subprocess.run(
            ["git", "diff", "--name-only", "--", ".", ":(exclude)logs/"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        _dirty_files = [f for f in _dirty_check.stdout.strip().splitlines() if f.strip()]
        if _dirty_files:
            for _df in _dirty_files:
                subprocess.run(
                    ["git", "checkout", "--", _df],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
            logger.error(
                "[PLAN-GUARD] Planning phase wrote files (reverted %d): %s",
                len(_dirty_files),
                ", ".join(_dirty_files),
            )

    if not skip_to_postflight:
        print("\n" + _phase_sep)
        print("PHASE 4: IMPLEMENTATION")
        print(_phase_sep)
        logger.info("[PHASE] IMPLEMENTATION started -- %d step(s) planned", len(plan.steps))
        open_phase(phase="implementation", phase_order=4)

        steps = plan.steps
        if step_limit:
            steps = steps[:step_limit]
            print(f"[LIMIT] Implementing first {step_limit} of {len(plan.steps)} steps")

        total_steps = len(steps)
        save_checkpoint(
            branch=branch,
            plan_file=rec_id,
            current_step=0,
            total_steps=total_steps,
            status="PLAN_COMPLETE",
        )
        # Use the planning session ID for all impl steps so each step resumes
        # from the cached GEMINI.md context rather than cold-starting per step.
        _plan_session_id: str = getattr(plan, "planning_session_id", "") or ""
        if _plan_session_id:
            logger.info("[IMPL] All steps will resume planning session %s", _plan_session_id[:8])
        impl_session_id: str = ""  # kept for return value capture only

        if resume_from_step > len(steps):
            logger.warning(
                "[CHECKPOINT] resume_from_step (%d) > num_steps (%d); resetting to 0",
                resume_from_step,
                len(steps),
            )
            resume_from_step = 0

        for i, step in enumerate(steps, 1):
            if i <= resume_from_step:
                print(f"[CHECKPOINT] Skipping step {i}/{total_steps} (already completed)")
                steps_completed += 1
                continue

            print(f"\n--- Step {i}/{total_steps} ---")

            step_success, step_reqs, impl_prompt_hash, impl_session_id = implement_step(
                step,
                rec_id,
                i,
                total_steps,
                resume_session_id=_plan_session_id or None,
                recommendation_target_file=rec.get("file", ""),
                effort=rec.get("effort", ""),
            )
            if step_success != StepOutcome.SUCCESS:
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
                        logger.info("[STEP-FAILURE] Reverted step file: %s", step_file)
                    except Exception as e:
                        logger.warning("[STEP-FAILURE] Failed to revert step file %s: %s", step_file, e)
                print(f"ERROR: Step {i} failed")
                failure_step = i
                failure_reason = f"implement_step failed: step {i} - {step.get('title', 'untitled')}"
                plan.status = "failed"
                if getattr(plan, "status", "") != "no_changes_needed":
                    save_plan(plan)
                update_recommendation_status(
                    rec_id,
                    {
                        "status": "failed",
                        "execution_result": "failure",
                        "execution_date": datetime.now(timezone.utc).isoformat(),
                        "execution_branch": branch,
                        "failure_step": failure_step,
                        "failure_reason": failure_reason[:500],
                        "execution_steps_attempted": steps_completed,
                        "execution_steps_total": len(plan.steps) if plan is not None else total_steps,
                    },
                )
                _handle_failure(
                    rec_id,
                    rec,
                    failure_step,
                    failure_reason,
                    steps_completed,
                    total_steps,
                )
                _capture_executor_telemetry(
                    rec_id=rec_id,
                    branch=branch,
                    outcome="failed",
                    failure_reason=failure_reason,
                    steps_completed=steps_completed,
                    total_steps=total_steps,
                    plan=plan,
                )
                write_run_summary(
                    rec_id,
                    branch,
                    "step_fail",
                    failure_reason,
                    steps_completed,
                    total_steps,
                    plan,
                    "implementation",
                )
                emit_failure_summary(
                    rec_id=rec_id,
                    failure_phase="implementation",
                    failure_reason=failure_reason or "",
                )
                close_phase(outcome="failed")
                close_session(
                    outcome="failed",
                    failure_phase="implementation",
                    failure_reason=failure_reason,
                    steps_total=total_steps,
                    steps_completed=steps_completed,
                )
                return False

            commit_ok, diff_stat = commit_step(step, rec_id, i)
            if not commit_ok:
                print(f"WARNING: Commit for step {i} had issues")
            if diff_stat:
                logger.info("[GIT] Step %d diff stat:\n%s", i, diff_stat)

            _append_step_telemetry(
                rec_id=rec_id,
                step_n=i,
                total_steps=total_steps,
                prompt_hash=impl_prompt_hash,
                diff_stat=diff_stat,
                model=MODEL_EXECUTION or "",
            )

            save_checkpoint(
                branch=branch,
                plan_file=rec_id,
                current_step=i,
                total_steps=total_steps,
            )

        print("\nAll steps completed successfully")
        save_checkpoint(
            branch=branch,
            plan_file=rec_id,
            current_step=total_steps,
            total_steps=total_steps,
            status="IMPL_COMPLETE",
        )

    # ========== PHASE 5: POSTFLIGHT ==========
    close_phase(outcome="success")  # close implementation
    print("\n" + _phase_sep)
    print("PHASE 5: POSTFLIGHT")
    print(_phase_sep)
    logger.info("[PHASE] POSTFLIGHT started -- %d step(s) completed", steps_completed)
    open_phase(phase="postflight", phase_order=5)

    if plan is not None:
        unplanned = _scope_drift_check(plan.steps)
        if unplanned:
            logger.warning("[SCOPE] %d unplanned file(s) changed: %s", len(unplanned), unplanned)
            print(f"WARNING: {len(unplanned)} unplanned file(s) changed: {', '.join(unplanned)}")
        else:
            logger.info("[SCOPE] No scope drift detected")
    else:
        logger.info("[SCOPE] No plan available -- scope drift check skipped")

    review_skip = no_review or fast_mode or skip_to_finalize or os.getenv("SKIP_CODE_REVIEW", "false").lower() in ("true", "1")
    if not review_skip and plan is not None:
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

        max_review_retries = int(os.getenv("REVIEW_FIX_RETRIES", "2"))
        _rec_effort = rec.get("effort", "")
        review_passed, review_cost, blocking = _code_review_gate(rec, plan, changed_files, effort=_rec_effort)
        for review_attempt in range(max_review_retries):
            if not blocking:
                break
            logger.warning(
                "[REVIEW] %d finding(s) (attempt %d/%d) -- requesting fix...",
                len(blocking),
                review_attempt + 1,
                max_review_retries,
            )
            emit_process_event(
                tier="rework",
                category="code_review_fix_attempt",
                severity="warning",
                description=f"{len(blocking)} blocking finding(s)",
            )
            fixed = _fix_code_review_findings(rec_id, blocking)
            if not fixed:
                break
            review_passed, review_cost, blocking = _code_review_gate(rec, plan, changed_files, effort=_rec_effort)
        if blocking:
            emit_process_event(
                tier="exception",
                category="code_review_fail",
                severity="error",
                description=f"{len(blocking)} finding(s) remain",
            )
            failure_reason = (
                "code review gate failed: "
                f"{len(blocking)} blocking finding(s) remain after "
                f"{max_review_retries} retry attempt(s)"
            )
            logger.error("[REVIEW] %s", failure_reason)
            update_recommendation_status(
                rec_id,
                {
                    "status": "failed",
                    "execution_result": "failure",
                    "execution_date": datetime.now(timezone.utc).isoformat(),
                    "execution_branch": branch,
                    "failure_step": None,
                    "failure_reason": failure_reason,
                    "execution_steps_attempted": steps_completed,
                    "execution_steps_total": total_steps,
                },
            )
            _handle_failure(
                rec_id=rec_id,
                rec=rec,
                failure_step=None,
                failure_reason=failure_reason,
                steps_completed=steps_completed,
                total_steps=total_steps,
            )
            _capture_executor_telemetry(
                rec_id=rec_id,
                branch=branch,
                outcome="failed",
                failure_reason=failure_reason,
                steps_completed=steps_completed,
                total_steps=total_steps,
                plan=plan,
            )
            write_run_summary(
                rec_id,
                branch,
                "review_fail",
                failure_reason,
                steps_completed,
                total_steps,
                plan,
                "postflight",
            )
            emit_failure_summary(
                rec_id=rec_id,
                failure_phase="postflight",
                failure_reason=failure_reason or "",
            )
            close_phase(outcome="failed")
            close_session(
                outcome="failed",
                failure_phase="postflight",
                failure_reason=failure_reason,
                steps_total=total_steps,
                steps_completed=steps_completed,
            )
            return False
        else:
            logger.info("[REVIEW] No CRITICAL/HIGH findings remaining -- review clean")
            save_checkpoint(
                branch=branch,
                plan_file=rec_id,
                current_step=steps_completed,
                total_steps=total_steps,
                status="REVIEW_COMPLETE",
            )
    else:
        logger.info("[REVIEW] Code review skipped")

    _skip_ci_wait = os.getenv("SKIP_CI_WAIT", "").lower() in ("1", "true", "yes")
    _validate_args = ["--pre"] if _skip_ci_wait else []
    _validate_label = "--pre" if _skip_ci_wait else "presubmit"
    _pf_validation: dict = {"mode": _validate_label, "result": "pending"}
    logger.info("[VALIDATE] Running validate.py %s before finalize...", _validate_label)
    # Strip executor-mode env vars so test isolation is preserved inside the
    # validate subprocess (e.g. SKIP_CI_WAIT=true must not leak into pytest).
    _validate_env = os.environ.copy()
    _validate_env.pop("SKIP_CI_WAIT", None)
    try:
        with subprocess.Popen(
            [sys.executable, "scripts/validate.py"] + _validate_args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=_validate_env,
        ) as full_val_proc:
            try:
                fv_stdout, fv_stderr = full_val_proc.communicate(timeout=600)
            except subprocess.TimeoutExpired:
                kill_process_tree(full_val_proc.pid)
                full_val_proc.wait()
                logger.error("[VALIDATE] Full CI validation timed out (600s)")
                _pf_validation.update({"result": "timeout", "returncode": None})
                write_run_summary(
                    rec_id,
                    branch,
                    "validation_fail",
                    "Full CI validation timed out (600s)",
                    steps_completed,
                    total_steps,
                    plan,
                    "postflight",
                    postflight_validation=_pf_validation,
                )
                emit_failure_summary(
                    rec_id=rec_id,
                    failure_phase="validation",
                    failure_reason=("Full CI validation timed out (600s)"),
                    failure_class="cli_timeout",
                )
                close_phase(outcome="failed")
                close_session(
                    outcome="failed",
                    failure_phase="postflight",
                    failure_reason="Full CI validation timed out (600s)",
                    steps_total=total_steps,
                    steps_completed=steps_completed,
                )
                return False
        if full_val_proc.returncode != 0:
            combined_ci = (fv_stdout + "\n" + fv_stderr).strip()
            quarantined_tests = _get_quarantined_validation_failures(combined_ci) if _skip_ci_wait else []
            if quarantined_tests:
                logger.warning(
                    "[VALIDATE] Quarantining known baseline-red local validation failures: %s",
                    ", ".join(quarantined_tests),
                )
                emit_process_event(
                    tier="decision",
                    category="validation_quarantine",
                    severity="warning",
                    description=f"Quarantined {len(quarantined_tests)} known baseline-red test(s)",
                )
                _pf_validation.update(
                    {
                        "result": "pass_with_quarantine",
                        "returncode": full_val_proc.returncode,
                        "quarantined_tests": quarantined_tests,
                    }
                )
            else:
                _skip_local_validate = os.getenv("SKIP_LOCAL_VALIDATE", "").lower() in (
                    "1",
                    "true",
                    "yes",
                )
                if _skip_local_validate:
                    logger.warning(
                        "[VALIDATE] SKIP_LOCAL_VALIDATE=1 set -- emergency bypass, "
                        "skipping validation failure. (rec-241 emergency bypass)"
                    )
                    logger.info("[VALIDATE] Full CI validation bypassed (emergency)")
                    emit_process_event(
                        tier="decision",
                        category="validation_emergency_bypass",
                        severity="warning",
                        description="SKIP_LOCAL_VALIDATE emergency bypass activated",
                    )
                    _pf_validation.update(
                        {
                            "result": "bypass",
                            "returncode": full_val_proc.returncode,
                        }
                    )
                else:
                    try:
                        git_diff_result = subprocess.run(
                            ["git", "diff", "--name-only", "origin/main"],
                            capture_output=True,
                            text=True,
                            encoding="utf-8",
                            errors="replace",
                            timeout=10,
                        )
                        if git_diff_result.returncode == 0:
                            changed_files = git_diff_result.stdout.strip().split("\n")
                            changed_files = [f for f in changed_files if f.strip()]
                            has_python_files = any(f.endswith(".py") for f in changed_files)

                            if not has_python_files and changed_files:
                                logger.info(
                                    "[VALIDATE] doc_only: All changed files are "
                                    "non_python (no .py extension) -- fallback to "
                                    "--scope prompts validation"
                                )
                                emit_process_event(
                                    tier="decision",
                                    category="validation_doc_only_fallback",
                                    severity="warning",
                                    description="doc-only diff: falling back to --scope prompts validation",
                                )
                                quick_val_env = os.environ.copy()
                                quick_val_env.pop("SKIP_CI_WAIT", None)
                                with subprocess.Popen(
                                    [
                                        sys.executable,
                                        "scripts/validate.py",
                                        "--scope",
                                        "prompts",
                                    ],
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE,
                                    text=True,
                                    encoding="utf-8",
                                    errors="replace",
                                    env=quick_val_env,
                                ) as quick_val_proc:
                                    try:
                                        qv_stdout, qv_stderr = quick_val_proc.communicate(timeout=300)
                                    except subprocess.TimeoutExpired:
                                        kill_process_tree(quick_val_proc.pid)
                                        quick_val_proc.wait()
                                        logger.error("[VALIDATE] Quick validation timed out (300s)")
                                        failure_reason = "quick validation timeout on doc-only diff"
                                        update_recommendation_status(
                                            rec_id,
                                            {
                                                "status": "failed",
                                                "execution_result": "failure",
                                                "execution_date": datetime.now(timezone.utc).isoformat(),
                                                "execution_branch": branch,
                                                "failure_step": None,
                                                "failure_reason": failure_reason,
                                                "execution_steps_attempted": steps_completed,
                                                "execution_steps_total": total_steps,
                                            },
                                        )
                                        _handle_failure(
                                            rec_id=rec_id,
                                            rec=rec,
                                            failure_step=None,
                                            failure_reason=failure_reason,
                                            steps_completed=steps_completed,
                                            total_steps=total_steps,
                                        )
                                        _capture_executor_telemetry(
                                            rec_id=rec_id,
                                            branch=branch,
                                            outcome="failed",
                                            failure_reason=failure_reason,
                                            steps_completed=steps_completed,
                                            total_steps=total_steps,
                                            plan=plan,
                                        )
                                        _pf_validation.update(
                                            {
                                                "result": "timeout",
                                                "returncode": None,
                                                "fallback_mode": "--scope prompts",
                                            }
                                        )
                                        write_run_summary(
                                            rec_id,
                                            branch,
                                            "validation_fail",
                                            failure_reason,
                                            steps_completed,
                                            total_steps,
                                            plan,
                                            "postflight",
                                            postflight_validation=_pf_validation,
                                        )
                                        emit_failure_summary(
                                            rec_id=rec_id,
                                            failure_phase="validation",
                                            failure_reason=failure_reason,
                                            failure_class="cli_timeout",
                                        )
                                        close_phase(outcome="failed")
                                        close_session(
                                            outcome="failed",
                                            failure_phase="postflight",
                                            failure_reason=failure_reason,
                                            steps_total=total_steps,
                                            steps_completed=steps_completed,
                                        )
                                        return False

                                if quick_val_proc.returncode != 0:
                                    combined_quick = (qv_stdout + "\n" + qv_stderr).strip()
                                    quick_lines = combined_quick.splitlines()
                                    capped_quick = "\n".join(quick_lines[-100:])
                                    if len(quick_lines) > 100:
                                        capped_quick = f"... ({len(quick_lines) - 100} earlier lines)\n" + capped_quick
                                    logger.error(
                                        "[VALIDATE] Quick validation also failed (non_python, scope auto):\n%s",
                                        capped_quick,
                                    )
                                    failure_reason = "quick validation failed on doc-only diff"
                                    update_recommendation_status(
                                        rec_id,
                                        {
                                            "status": "failed",
                                            "execution_result": "failure",
                                            "execution_date": datetime.now(timezone.utc).isoformat(),
                                            "execution_branch": branch,
                                            "failure_step": None,
                                            "failure_reason": failure_reason,
                                            "execution_steps_attempted": steps_completed,
                                            "execution_steps_total": total_steps,
                                        },
                                    )
                                    _handle_failure(
                                        rec_id=rec_id,
                                        rec=rec,
                                        failure_step=None,
                                        failure_reason=failure_reason,
                                        steps_completed=steps_completed,
                                        total_steps=total_steps,
                                    )
                                    _capture_executor_telemetry(
                                        rec_id=rec_id,
                                        branch=branch,
                                        outcome="failed",
                                        failure_reason=failure_reason,
                                        steps_completed=steps_completed,
                                        total_steps=total_steps,
                                        plan=plan,
                                    )
                                    _pf_validation.update(
                                        {
                                            "result": "fail",
                                            "returncode": quick_val_proc.returncode,
                                            "fallback_mode": "--scope prompts",
                                        }
                                    )
                                    write_run_summary(
                                        rec_id,
                                        branch,
                                        "validation_fail",
                                        failure_reason,
                                        steps_completed,
                                        total_steps,
                                        plan,
                                        "postflight",
                                        postflight_validation=_pf_validation,
                                    )
                                    emit_failure_summary(
                                        rec_id=rec_id,
                                        failure_phase="validation",
                                        failure_reason=failure_reason,
                                        failure_class="test_failure",
                                        validation_output=(capped_quick),
                                    )
                                    close_phase(outcome="failed")
                                    close_session(
                                        outcome="failed",
                                        failure_phase="postflight",
                                        failure_reason=failure_reason,
                                        steps_total=total_steps,
                                        steps_completed=steps_completed,
                                    )
                                    return False
                                logger.info("[VALIDATE] Quick validation passed (doc_only, non_python, scope prompts)")
                                _pf_validation.update(
                                    {
                                        "result": "pass",
                                        "returncode": 0,
                                        "fallback_mode": "--scope prompts",
                                    }
                                )
                            else:
                                ci_lines = combined_ci.splitlines()
                                capped_ci = "\n".join(ci_lines[-100:])
                                if len(ci_lines) > 100:
                                    capped_ci = f"... ({len(ci_lines) - 100} earlier lines)\n" + capped_ci
                                logger.error(
                                    "[VALIDATE] Full CI validation failed (Python files modified):\n%s",
                                    capped_ci,
                                )
                                failure_reason = "full CI validation failed before finalize"
                                update_recommendation_status(
                                    rec_id,
                                    {
                                        "status": "failed",
                                        "execution_result": "failure",
                                        "execution_date": datetime.now(timezone.utc).isoformat(),
                                        "execution_branch": branch,
                                        "failure_step": None,
                                        "failure_reason": failure_reason,
                                        "execution_steps_attempted": steps_completed,
                                        "execution_steps_total": total_steps,
                                    },
                                )
                                _handle_failure(
                                    rec_id=rec_id,
                                    rec=rec,
                                    failure_step=None,
                                    failure_reason=failure_reason,
                                    steps_completed=steps_completed,
                                    total_steps=total_steps,
                                )
                                _capture_executor_telemetry(
                                    rec_id=rec_id,
                                    branch=branch,
                                    outcome="failed",
                                    failure_reason=failure_reason,
                                    steps_completed=steps_completed,
                                    total_steps=total_steps,
                                    plan=plan,
                                )
                                _pf_validation.update(
                                    {
                                        "result": "fail",
                                        "returncode": full_val_proc.returncode,
                                    }
                                )
                                write_run_summary(
                                    rec_id,
                                    branch,
                                    "validation_fail",
                                    failure_reason,
                                    steps_completed,
                                    total_steps,
                                    plan,
                                    "postflight",
                                    postflight_validation=_pf_validation,
                                )
                                emit_failure_summary(
                                    rec_id=rec_id,
                                    failure_phase="validation",
                                    failure_reason=failure_reason,
                                    failure_class="test_failure",
                                    validation_output=capped_ci,
                                )
                                close_phase(outcome="failed")
                                close_session(
                                    outcome="failed",
                                    failure_phase="postflight",
                                    failure_reason=failure_reason,
                                    steps_total=total_steps,
                                    steps_completed=steps_completed,
                                )
                                return False
                    except Exception as e:
                        logger.warning(
                            "[VALIDATE] Could not detect doc-only diff: %s -- treating as regular validation failure",
                            e,
                        )
                        ci_lines = combined_ci.splitlines()
                        capped_ci = "\n".join(ci_lines[-100:])
                        if len(ci_lines) > 100:
                            capped_ci = f"... ({len(ci_lines) - 100} earlier lines)\n" + capped_ci
                        logger.error("[VALIDATE] Full CI validation failed:\n%s", capped_ci)
                        failure_reason = "full CI validation failed before finalize"
                        update_recommendation_status(
                            rec_id,
                            {
                                "status": "failed",
                                "execution_result": "failure",
                                "execution_date": datetime.now(timezone.utc).isoformat(),
                                "execution_branch": branch,
                                "failure_step": None,
                                "failure_reason": failure_reason,
                                "execution_steps_attempted": steps_completed,
                                "execution_steps_total": total_steps,
                            },
                        )
                        _handle_failure(
                            rec_id=rec_id,
                            rec=rec,
                            failure_step=None,
                            failure_reason=failure_reason,
                            steps_completed=steps_completed,
                            total_steps=total_steps,
                        )
                        _capture_executor_telemetry(
                            rec_id=rec_id,
                            branch=branch,
                            outcome="failed",
                            failure_reason=failure_reason,
                            steps_completed=steps_completed,
                            total_steps=total_steps,
                            plan=plan,
                        )
                        _pf_validation.update(
                            {
                                "result": "fail",
                                "returncode": full_val_proc.returncode,
                            }
                        )
                        write_run_summary(
                            rec_id,
                            branch,
                            "validation_fail",
                            failure_reason,
                            steps_completed,
                            total_steps,
                            plan,
                            "postflight",
                            postflight_validation=_pf_validation,
                        )
                        emit_failure_summary(
                            rec_id=rec_id,
                            failure_phase="validation",
                            failure_reason=failure_reason,
                            failure_class="test_failure",
                        )
                        close_phase(outcome="failed")
                        close_session(
                            outcome="failed",
                            failure_phase="postflight",
                            failure_reason=failure_reason,
                            steps_total=total_steps,
                            steps_completed=steps_completed,
                        )
                        return False
        if _pf_validation.get("result") == "pass_with_quarantine":
            logger.warning("[VALIDATE] Full CI validation passed under explicit baseline-test quarantine")
        else:
            logger.info("[VALIDATE] Full CI validation passed")
    except OSError:
        logger.error("[VALIDATE] Could not start validate.py")
        _pf_validation.update({"result": "error", "returncode": None})
        write_run_summary(
            rec_id,
            branch,
            "validation_fail",
            "Could not start validate.py",
            steps_completed,
            total_steps,
            plan,
            "postflight",
            postflight_validation=_pf_validation,
        )
        emit_failure_summary(
            rec_id=rec_id,
            failure_phase="validation",
            failure_reason="Could not start validate.py",
        )
        close_phase(outcome="failed")
        close_session(
            outcome="failed",
            failure_phase="postflight",
            failure_reason="Could not start validate.py",
            steps_total=total_steps,
            steps_completed=steps_completed,
        )
        return False

    if _pf_validation.get("result") == "pending":
        _pf_validation.update(
            {
                "result": "pass",
                "returncode": 0,
            }
        )

    # Post-validation acceptance check: verify acceptance criterion passes before finalize
    if acceptance_cmd:
        acceptance_result = run_acceptance(acceptance_cmd)
        if not acceptance_result:
            logger.error("[ACCEPTANCE] Post-validation acceptance check FAILED for rec %s", rec_id)
            acceptance_output = get_last_acceptance_output()
            failure_reason = "post-validation acceptance check failed"
            update_recommendation_status(
                rec_id,
                {
                    "status": "failed",
                    "execution_result": "failure",
                    "execution_date": datetime.now(timezone.utc).isoformat(),
                    "execution_branch": branch,
                    "failure_step": None,
                    "failure_reason": failure_reason,
                    "execution_steps_attempted": steps_completed,
                    "execution_steps_total": total_steps,
                },
            )
            _handle_failure(
                rec_id=rec_id,
                rec=rec,
                failure_step=None,
                failure_reason=failure_reason,
                steps_completed=steps_completed,
                total_steps=total_steps,
            )
            _capture_executor_telemetry(
                rec_id=rec_id,
                branch=branch,
                outcome="failed",
                failure_reason=failure_reason,
                steps_completed=steps_completed,
                total_steps=total_steps,
                plan=plan,
            )
            write_run_summary(
                rec_id,
                branch,
                "acceptance_fail",
                failure_reason,
                steps_completed,
                total_steps,
                plan,
                "postflight",
                postflight_validation=_pf_validation,
                acceptance_output=acceptance_output,
            )
            emit_failure_summary(
                rec_id=rec_id,
                failure_phase="acceptance",
                failure_reason=failure_reason or "",
                failure_class="acceptance_mismatch",
                acceptance_output=acceptance_output or "",
            )
            close_phase(outcome="failed")
            close_session(
                outcome="failed",
                failure_phase="postflight",
                failure_reason=failure_reason,
                steps_total=total_steps,
                steps_completed=steps_completed,
            )
            return False

    # Post-acceptance verification gate: behavioural end-to-end proof.
    # Runs only when the rec has a verification field. Failure is advisory
    # (warning + telemetry) -- it does NOT block the merge.
    if verification_cmd:
        verification_result = run_verification(verification_cmd)
        if verification_result.get("rejected"):
            logger.warning(
                "[VERIFICATION] Command rejected for rec %s: %s",
                rec_id,
                verification_result.get("error", ""),
            )
        elif not verification_result.get("skipped") and not verification_result.get("passed"):
            logger.warning(
                "[VERIFICATION] Behavioural verification FAILED (advisory) for rec %s. "
                "Acceptance passed so merge will proceed. Output: %s",
                rec_id,
                verification_result.get("output", "")[:500],
            )
        _capture_executor_telemetry(
            rec_id=rec_id,
            branch=branch,
            outcome="verification_warning" if not verification_result.get("passed") else "verification_pass",
            failure_reason=(
                f"verification failed (advisory): {verification_result.get('error', '')}"
                if not verification_result.get("passed") and not verification_result.get("skipped")
                else None
            ),
            steps_completed=steps_completed,
            total_steps=total_steps,
            plan=plan,
        )

    save_checkpoint(
        branch=branch,
        plan_file=rec_id,
        current_step=steps_completed,
        total_steps=total_steps,
        status="CI_PENDING",
    )
    pr_url = finalize(rec_id, no_merge=no_merge)
    if pr_url is None:
        print("ERROR: Finalization failed")
        failure_reason = "finalize() failed: push, PR creation, CI wait, or merge error"
        update_recommendation_status(
            rec_id,
            {
                "status": "failed",
                "execution_result": "failure",
                "execution_date": datetime.now(timezone.utc).isoformat(),
                "execution_branch": branch,
                "failure_step": None,
                "failure_reason": failure_reason,
                "execution_steps_attempted": steps_completed,
                "execution_steps_total": len(plan.steps) if plan is not None else total_steps,
            },
        )
        _handle_failure(rec_id, rec, None, failure_reason, steps_completed, total_steps)
        _capture_executor_telemetry(
            rec_id=rec_id,
            branch=branch,
            outcome="failed",
            failure_reason=failure_reason,
            steps_completed=steps_completed,
            total_steps=len(plan.steps) if plan is not None else total_steps,
            plan=plan,
        )
        write_run_summary(
            rec_id,
            branch,
            "finalize_fail",
            failure_reason,
            steps_completed,
            len(plan.steps) if plan is not None else total_steps,
            plan,
            "postflight",
            postflight_validation=_pf_validation,
        )
        emit_failure_summary(
            rec_id=rec_id,
            failure_phase="finalize",
            failure_reason=failure_reason,
        )
        close_phase(outcome="failed")
        close_session(
            outcome="failed",
            failure_phase="postflight",
            failure_reason=failure_reason,
            steps_total=total_steps,
            steps_completed=steps_completed,
        )
        return False

    print(f"SUCCESS: PR created -- {pr_url}")
    update_recommendation_status(
        rec_id,
        {
            "status": "closed",
            "execution_result": "success",
            "execution_date": datetime.now(timezone.utc).isoformat(),
            "execution_branch": branch,
            "execution_pr_url": pr_url,
            "execution_steps": steps_completed,
        },
    )
    clear_checkpoint()

    # Unified telemetry: friction capture + session envelope
    _capture_executor_telemetry(
        rec_id=rec_id,
        branch=branch,
        outcome="merged",
        failure_reason=None,
        steps_completed=steps_completed,
        total_steps=len(plan.steps) if plan is not None else total_steps,
        plan=plan,
    )

    write_run_summary(
        rec_id,
        branch,
        "success",
        None,
        steps_completed,
        len(plan.steps) if plan is not None else total_steps,
        plan,
        "finalize",
        postflight_validation=_pf_validation,
    )

    close_phase(outcome="success")
    close_session(
        outcome="success",
        steps_total=len(plan.steps) if plan is not None else total_steps,
        steps_completed=steps_completed,
        pr_url=pr_url,
        ci_outcome="success",
    )
    return True


# ---------------------------------------------------------------------------
# Batch orchestration (extracted to scripts/executor/batch.py)
# ---------------------------------------------------------------------------
from scripts.executor.batch import (  # noqa: E402, F401, I001
    DEFAULT_NEXT_BATCH_LIMIT,
    EFFORT_ORDER,
    EFFORT_WEIGHTS,
    MAX_BATCH_EFFORT,
    MAX_BATCH_SIZE,
    PRIORITY_ORDER,
    _ensure_compound_branch,
    execute_batch,
    execute_compound,
    get_eligible_recs,
    load_cluster,
    select_compound_batch,
    select_next_batch,
    topological_sort_recs,
)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI entry point."""
    import argparse

    # --session-status is a read-only dashboard; skip guards so it
    # works even when invoked from inside an executor session.
    if "--session-status" in sys.argv:
        print_session_status()
        sys.exit(0)

    # --next-batch is a read-only selector; skip guards.
    if "--next-batch" in sys.argv:
        import argparse as _nb_argparse

        _nb_parser = _nb_argparse.ArgumentParser()
        _nb_parser.add_argument("--next-batch", action="store_true")
        _nb_parser.add_argument(
            "--limit",
            type=int,
            default=DEFAULT_NEXT_BATCH_LIMIT,
            help="Max recommended recs to return",
        )
        _nb_args, _ = _nb_parser.parse_known_args()
        payload = select_next_batch(limit=_nb_args.limit)
        print(json.dumps(payload, indent=2))
        sys.exit(0)

    check_recursion_guard()
    check_process_killswitch(label="execute_recommendation")
    _assign_job_object()

    # Safety net: ensure Gemini CLI is used when the env var is not set.
    # Lambda handlers do not invoke this path -- they route via schedule.yaml.
    os.environ.setdefault("LLM_PROVIDER", "gemini")

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="Execute a recommendation from the JSONL log with atomized plan/critique/execute flow",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m scripts.execute_recommendation rec-009 --step-limit 2
  python -m scripts.execute_recommendation rec-009 --skip-critique
  python -m scripts.execute_recommendation rec-009 --no-merge
  python -m scripts.execute_recommendation rec-009 --restart
  python -m scripts.execute_recommendation rec-009 --resume
  python -m scripts.execute_recommendation rec-009 --resume-postflight
  python -m scripts.execute_recommendation rec-009 --fast --plan-json '[{{"n":1,...}}]'
  python -m scripts.execute_recommendation --batch --max-recs 5
  python -m scripts.execute_recommendation --single rec-009
  python -m scripts.execute_recommendation  (no args: compound default, auto-selects batch)

Environment variables:
  COPILOT_MODEL_PLANNING      Model for planning (default: CLI default)
  COPILOT_MODEL_EXECUTION     Model for implementation (default: CLI default)
  PLAN_MAX_REVISIONS          Max critique iterations (default: 3)
  CI_WAIT_TIMEOUT_SECS        Max seconds to wait for CI (default: 600)
""",
    )
    parser.add_argument("rec_id", nargs="?", help="Recommendation ID (e.g., rec-009); omit when using --batch or --compound")
    parser.add_argument("--step-limit", type=int, help="Implement only first N steps (inspection mode)")
    parser.add_argument("--skip-critique", action="store_true", help="Skip plan critique loop")
    parser.add_argument("--no-merge", action="store_true", help="Stop after PR creation without CI wait or merge")
    parser.add_argument("--no-review", action="store_true", help="Skip the code review gate")
    parser.add_argument("--restart", action="store_true", help="Clear checkpoint and reset JSONL status to 'open'")
    _resume_group = parser.add_mutually_exclusive_group()
    _resume_group.add_argument("--resume", action="store_true", help="Resume from existing checkpoint")
    _resume_group.add_argument(
        "--resume-postflight",
        action="store_true",
        help="Skip plan/impl phases and jump straight to postflight (requires prior IMPL_COMPLETE checkpoint)",
    )
    _resume_group.add_argument(
        "--auto-resume",
        action="store_true",
        help="Automatically resume from checkpoint state (dispatches to correct phase based on status)",
    )
    parser.add_argument("--single", action="store_true", help="Force single-rec execution (overrides compound default)")
    parser.add_argument(
        "--fast",
        action="store_true",
        help="Fast mode: skip planning, critique, and code review; requires --plan-json or stdin",
    )
    parser.add_argument(
        "--plan-json",
        type=str,
        default=None,
        help="JSON string with prebuilt plan steps for --fast mode",
    )
    parser.add_argument("--batch", action="store_true", help="Process all eligible recs in dependency order")
    parser.add_argument("--max-recs", type=int, default=10, help="Max recommendations to process in batch mode")
    parser.add_argument("--compound", type=str, help="Execute multiple rec-IDs (comma-separated) or a cluster ID")
    parser.add_argument(
        "--session-status",
        action="store_true",
        help="Print a session dashboard and exit",
    )
    parser.add_argument(
        "--next-batch",
        action="store_true",
        help=("Print JSON with recommended and skipped recs, then exit (read-only, no execution)"),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_NEXT_BATCH_LIMIT,
        help=(f"Max recommended recs for --next-batch (default: {DEFAULT_NEXT_BATCH_LIMIT})"),
    )

    args = parser.parse_args()

    if args.session_status:
        print_session_status()
        sys.exit(0)

    if args.compound:
        if args.compound.startswith("cluster-"):
            rec_ids = load_cluster(args.compound)
            cluster_id = args.compound
        else:
            rec_ids = [x.strip() for x in args.compound.split(",")]
            cluster_id = None

        summary = execute_compound(
            rec_ids,
            cluster_id=cluster_id,
            no_merge=args.no_merge,
            no_review=args.no_review,
            restart=args.restart,
            skip_critique=args.skip_critique,
        )
        sys.exit(0 if summary.get("failed", 0) == 0 else 1)
    elif args.batch:
        summary = execute_batch(no_merge=args.no_merge, max_recs=args.max_recs, restart=args.restart)
        sys.exit(0 if summary["failed"] == 0 else 1)
    elif args.single or args.rec_id or args.fast:
        # Single mode: explicit --single flag, --fast flag, or a specific rec_id with no compound/batch flags
        if not args.rec_id:
            parser.error("rec_id is required when not using --batch or --compound")
        success = execute_recommendation(
            args.rec_id,
            step_limit=args.step_limit,
            skip_critique=args.skip_critique,
            no_merge=args.no_merge,
            no_review=args.no_review,
            restart=args.restart,
            resume=args.resume,
            resume_postflight=args.resume_postflight,
            fast_mode=args.fast,
            plan_json=args.plan_json,
            auto_resume=args.auto_resume,
        )
        sys.exit(0 if success else 1)
    else:
        # Default: compound execution with auto-selected batch
        eligible = get_eligible_recs()
        batch = select_compound_batch(eligible)
        if not batch:
            print("No eligible recommendations for compound execution. Use --batch to see all eligible recs.")
            sys.exit(0)
        rec_ids = [r["id"] for r in batch]
        logger.info("[DEFAULT] Compound batch selected: %s", rec_ids)
        summary = execute_compound(
            rec_ids,
            cluster_id=None,
            no_merge=args.no_merge,
            no_review=args.no_review,
            restart=args.restart,
            skip_critique=args.skip_critique,
        )
        sys.exit(0 if summary.get("failed", 0) == 0 else 1)


if __name__ == "__main__":
    main()
