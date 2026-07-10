"""Run and failure summary artifacts for the executor.

Extracted from scripts/execute_recommendation.py (SLOC decomposition, Decision
102/104 facade mechanism, operator-descoped per the plan's ORCHESTRATOR
RATIFICATION context bullet -- this is a low-risk cluster extraction, not part
of the phase-shatter). Writes per-run summaries (write_run_summary) and
structured failure summaries (emit_failure_summary), plus their shared git/
telemetry/classification helpers.

Routed-name references (subprocess, Path, _infer_failure_class,
_latest_transcript_path, _get_git_diff_stat) resolve through the
scripts.execute_recommendation facade via a function-local import so the
existing test suite's patches on scripts.execute_recommendation.<name> keep
intercepting with zero migration -- in particular emit_failure_summary's
calls into its sibling helpers and its own Path/subprocess usage route through
the facade rather than a bare co-located reference, since the test suite's
patch sites (including the sole Path patch) target the facade namespace.
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional, TypedDict

if TYPE_CHECKING:
    from scripts.executor.plan import ExecutionPlan

logger = logging.getLogger(__name__)


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
    plan: "Optional[ExecutionPlan]" = None,
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

    import scripts.execute_recommendation as _er

    if os.environ.get("PYTEST_CURRENT_TEST"):
        logger.warning(
            "Skipping run summary for %s (PYTEST_CURRENT_TEST set)",
            rec_id,
        )
        return

    timestamp_now = datetime.now(timezone.utc)
    run_dir = _er.Path("logs/runs")
    run_dir.mkdir(parents=True, exist_ok=True)

    # Load per-step outcomes from .execution-step-telemetry.jsonl
    per_step_outcomes = []
    step_telemetry_path = _er.Path("logs/.execution-step-telemetry.jsonl")
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
    import scripts.execute_recommendation as _er

    try:
        result = _er.subprocess.run(
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
    import scripts.execute_recommendation as _er

    transcript_dir = _er.Path("logs/transcripts")
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
    import scripts.execute_recommendation as _er

    if os.environ.get("PYTEST_CURRENT_TEST"):
        return

    if not failure_class:
        failure_class = _er._infer_failure_class(
            failure_phase,
            failure_reason,
        )

    summary: FailureSummary = {
        "rec_id": rec_id,
        "attempt": attempt,
        "failure_phase": failure_phase,
        "failure_class": failure_class,
        "last_transcript_path": _er._latest_transcript_path(rec_id),
        "git_diff_stat": _er._get_git_diff_stat(),
        "validation_output": (validation_output[:2000] if validation_output else ""),
        "acceptance_output": (acceptance_output[:2000] if acceptance_output else ""),
        "failure_reason": (failure_reason[:1000] if failure_reason else ""),
    }

    out_dir = _er.Path("logs/failure-summaries")
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    out_path = out_dir / f"{rec_id}-{ts}.json"
    with open(out_path, "w", encoding="utf-8", errors="replace") as f:
        json.dump(summary, f, indent=2)
    logger.info(
        "[FAILURE-SUMMARY] Written to %s",
        out_path,
    )
