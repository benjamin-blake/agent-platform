"""Executor package — thin imports for backward compatibility.

The recommendation executor is split into submodules:
  errors      — Structured error types and enums
  jsonl_store — Unified JSONL read/write
  plan        — Plan generation, critique, parsing
  step_runner — Step implementation and acceptance verification
  postflight  — Finalisation, CI wait, merge, cleanup
  ci_triage   — Deterministic CI failure classification

Re-exports are provided so ``from scripts.executor import X`` continues to
work as callers migrate away from the old monolith import path.
"""

from scripts.executor.acceptance_lint import (
    AcceptanceFeasibility,
    lint_acceptance_command,
    validate_acceptance_feasibility,
)
from scripts.executor.batch import execute_batch, execute_compound, select_next_batch
from scripts.executor.ci_triage import TriageResult, triage_ci_failure
from scripts.executor.errors import (
    AcceptanceCommandError,
    CheckpointError,
    CIFailureCategory,
    ExecutorError,
    MergeFailureReason,
    PlanParseError,
)
from scripts.executor.formatters import auto_format_test_files
from scripts.executor.jsonl_store import (
    _create_postmortem_recommendation,
    _reset_rec_status,
    load_all_recommendations,
    load_recommendation,
    update_recommendation_status,
)
from scripts.executor.model_routing import (
    escalate_implementation_model,
    escalate_planning_model,
    get_planning_model,
)
from scripts.executor.plan import (
    ExecutionPlan,
    PlanStep,
    critique_plan,
    generate_initial_plan,
    get_latest_plan,
    load_prompt,
    parse_steps_from_plan,
    refine_plan,
    save_plan,
)
from scripts.executor.postflight import (
    _code_review_gate,
    _commits_ahead_of_main,
    _fix_ci_failure,
    _fix_code_review_findings,
    _handle_failure,
    _scope_drift_check,
    cleanup_after_merge,
    finalize,
    merge_pr,
    wait_for_ci,
)
from scripts.executor.step_runner import (
    _append_step_telemetry,
    commit_step,
    gather_step_context,
    implement_step,
    run_acceptance,
)


# Top-level orchestration functions (from the thin entrypoint)
# imported lazily to avoid circular imports at package level
def execute_recommendation(*args, **kwargs):  # type: ignore[misc]
    from scripts.execute_recommendation import execute_recommendation as _er

    return _er(*args, **kwargs)


__all__ = [
    # errors
    "AcceptanceCommandError",
    "CIFailureCategory",
    "CheckpointError",
    "ExecutorError",
    "MergeFailureReason",
    "PlanParseError",
    # jsonl_store
    "_create_postmortem_recommendation",
    "_reset_rec_status",
    "load_all_recommendations",
    "load_recommendation",
    "update_recommendation_status",
    # plan
    "ExecutionPlan",
    "PlanStep",
    "critique_plan",
    "generate_initial_plan",
    "get_latest_plan",
    "load_prompt",
    "parse_steps_from_plan",
    "refine_plan",
    "save_plan",
    # postflight
    "_code_review_gate",
    "_commits_ahead_of_main",
    "_fix_ci_failure",
    "_fix_code_review_findings",
    "_handle_failure",
    "_scope_drift_check",
    "cleanup_after_merge",
    "finalize",
    "merge_pr",
    "wait_for_ci",
    # step_runner
    "_append_step_telemetry",
    "commit_step",
    "gather_step_context",
    "implement_step",
    "run_acceptance",
    # acceptance_lint
    "AcceptanceFeasibility",
    "lint_acceptance_command",
    "validate_acceptance_feasibility",
    # batch
    "execute_batch",
    "execute_compound",
    "select_next_batch",
    # formatters
    "auto_format_test_files",
    # model_routing
    "escalate_implementation_model",
    "escalate_planning_model",
    "get_planning_model",
    # ci_triage
    "TriageResult",
    "triage_ci_failure",
    # orchestration (lazy)
    "execute_recommendation",
]
