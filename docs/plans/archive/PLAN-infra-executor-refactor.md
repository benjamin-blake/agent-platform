# Plan

## Intent
Refactor the recommendation executor from a 3,100-line monolith into a maintainable package structure with deterministic CI triage, unified JSONL handling, and a VS Code development prompt. This directly advances the North Star by making the autonomous execution system easier to debug, extend, and improve — enabling faster iteration on the self-improving feedback loop infrastructure.

## Plan Type
IMPLEMENTATION

## Branch
agent/infra-executor-refactor

## Phase
Phase-infra (infrastructure/tooling work supporting future phases)

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `scripts/executor/__init__.py` | Create | Package entry point with re-exports for backward compatibility |
| `scripts/executor/jsonl_store.py` | Create | Unified JSONL read/write with consistent encoding and atomic writes |
| `scripts/executor/errors.py` | Create | Structured error types (enums for CI failure categories, merge failures) |
| `scripts/executor/plan.py` | Create | Plan generation, critique, refinement, parsing logic |
| `scripts/executor/step_runner.py` | Create | Step implementation, acceptance verification, context gathering |
| `scripts/executor/postflight.py` | Create | Finalize, CI wait, merge, cleanup, agent recovery |
| `scripts/executor/ci_triage.py` | Create | Deterministic CI failure classification and auto-fix |
| `scripts/execute_recommendation.py` | Modify | Thin CLI entrypoint importing from scripts/executor/ |
| `config/prompts/executor/planning.prompt.md` | Modify | Verify strict acceptance format, add missing constraints |
| `config/prompts/executor/critique.prompt.md` | Modify | Require machine-parseable VERDICT format |
| `config/prompts/executor/implement-step.prompt.md` | Modify | Tighten response format rules |
| `config/prompts/executor/refine.prompt.md` | Modify | Match planning format rules exactly |
| `config/prompts/executor/code-review.prompt.md` | Modify | Structured severity format for reliable parsing |
| `.github/prompts/develop-executor.prompt.md` | Create | VS Code agent prompt for executor development/debugging |
| `tests/test_executor_jsonl_store.py` | Create | Tests for JSONL module |
| `tests/test_executor_plan.py` | Create | Tests for plan module |
| `tests/test_executor_step_runner.py` | Create | Tests for step runner |
| `tests/test_executor_postflight.py` | Create | Tests for postflight |
| `tests/test_executor_ci_triage.py` | Create | Tests for CI triage |
| `tests/test_executor_errors.py` | Create | Tests for error types |

## Acceptance Criteria
- [ ] `python -m scripts.execute_recommendation rec-test --dry-run` works identically to before refactor
- [ ] All existing tests in `tests/test_execute_recommendation.py` pass
- [ ] New per-module test files achieve 80%+ coverage of their respective modules
- [ ] `scripts/executor/ci_triage.py` can classify lint/import errors and run `ruff check --fix` without LLM
- [ ] All 5 executor prompts have strict, machine-parseable output formats
- [ ] `run_acceptance()` fails loudly on non-parseable acceptance commands instead of guessing
- [ ] `.github/prompts/develop-executor.prompt.md` enables an agent to run executor in test mode and diagnose failures
- [ ] `python scripts/validate.py` passes
- [ ] No increase in premium request cost for equivalent executor runs

## Constraints
- Python 3.12+, type hints required (from copilot_instructions.md)
- No Docker (Windows VM constraint)
- Shell commands must use bash syntax, not PowerShell
- Backward compatibility: `python -m scripts.execute_recommendation` must continue to work
- Existing JSONL schema must not change (only internal handling improves)
- Premium request costs must not increase (deterministic triage should reduce them)

## Context
- Decision 32 (API Specification Precision): Requires explicit before/after signatures for any function contract changes
- Decision 31 (Subagent CLI Invocation): Subagents cannot invoke CLI commands; VS Code prompt targets human-driven sessions
- Current executor has 5 JSONL handling functions with inconsistent encoding
- `run_acceptance()` has ~80 lines of format-guessing that should be strict
- CI failures currently use LLM for 100% of cases; ~40-50% are deterministically fixable (lint, imports)

## Pre-Implementation Checklist
> The implementing agent must verify all items before editing any file.
- [ ] Branch confirmed not on `main`
- [ ] copilot_instructions.md read (rules, gotchas, file router)
- [ ] DECISIONS.md read (no conflicts with prior decisions)
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable
- [ ] Current `execute_recommendation.py` read and understood
- [ ] Existing test file `tests/test_execute_recommendation.py` read

## Ordered Execution Steps

> **Phase A: Module Structure and Core Extraction**

### Step 1: Create executor package with error types
**Files**: `scripts/executor/__init__.py`, `scripts/executor/errors.py`
**Action**: Create
**Description**: Create the `scripts/executor/` package. `errors.py` defines structured error types: `ExecutorError` base exception, `CIFailureCategory` enum (lint, import, type, test, unknown), `MergeFailureReason` enum (conflict, dirty_tree, draft_pr, unknown). `__init__.py` re-exports key functions for backward compatibility.
**Acceptance**: `python -c "from scripts.executor.errors import CIFailureCategory, MergeFailureReason; print(CIFailureCategory.LINT.value)"`

### Step 2: Create jsonl_store.py with unified JSONL handling
**File**: `scripts/executor/jsonl_store.py`
**Action**: Create
**Description**: Extract and consolidate JSONL functions: `load_recommendation()`, `load_all_recommendations()`, `update_recommendation_status()`, `_reset_rec_status()`, `_create_postmortem_recommendation()`. Use consistent `encoding="utf-8"`, atomic temp-file writes, and unified comment-line/blank-line handling. Add `RECS_JSONL` and `PLANS_JSONL` path constants.
**Acceptance**: `python -c "from scripts.executor.jsonl_store import load_all_recommendations; print(type(load_all_recommendations()))"`

### Step 3: Create plan.py with plan generation/parsing logic
**File**: `scripts/executor/plan.py`
**Action**: Create
**Description**: Extract plan-related code: `PlanStep` dataclass, `ExecutionPlan` dataclass, `load_prompt()`, `parse_steps_from_plan()`, `generate_initial_plan()`, `critique_plan()`, `refine_plan()`, `save_plan()`, `get_latest_plan()`. Import `CopilotResponseError` from `copilot_wrapper` and `requests_for_model` from `premium_requests`.
**Acceptance**: `python -c "from scripts.executor.plan import ExecutionPlan, parse_steps_from_plan; print(ExecutionPlan.__annotations__)"`

### Step 4: Create step_runner.py with implementation logic
**File**: `scripts/executor/step_runner.py`
**Action**: Create
**Description**: Extract step execution code: `gather_step_context()`, `run_acceptance()`, `implement_step()`, `commit_step()`, `_append_step_telemetry()`. Modify `run_acceptance()` to fail loudly (return False with clear log) when no parseable command is found, instead of returning True. Keep the strict format requirement from planning prompt.
**Acceptance**: `python -c "from scripts.executor.step_runner import implement_step, run_acceptance; print(implement_step.__annotations__)"`

### Step 5: Create postflight.py with finalization logic
**File**: `scripts/executor/postflight.py`
**Action**: Create
**Description**: Extract postflight code: `finalize()`, `wait_for_ci()`, `merge_pr()`, `cleanup_after_merge()`, `_fix_ci_failure()`, `_get_ci_failure_details()`, `_fix_code_review_findings()`, `_agent_merge_recovery()`, `_commits_ahead_of_main()`, `_create_postmortem_recommendation()` (import from jsonl_store), `_scope_drift_check()`, `_code_review_gate()`, `_handle_failure()`.
**Acceptance**: `python -c "from scripts.executor.postflight import finalize, wait_for_ci, merge_pr; print(finalize.__annotations__)"`

### Step 6: Create ci_triage.py with deterministic CI classification
**File**: `scripts/executor/ci_triage.py`
**Action**: Create
**Description**: New module for deterministic CI failure triage. `TriageResult` dataclass with fields: `category: CIFailureCategory`, `fixed: bool`, `files_changed: list[str]`, `escalate_to_llm: bool`, `context_for_llm: str`. `triage_ci_failure(error_output: str) -> TriageResult` function that: (1) parses ruff errors and runs `ruff check --fix` for lint category, (2) parses import errors and runs `ruff check --select I --fix` for import category, (3) returns `escalate_to_llm=True` with focused context for test/unknown categories.
**Acceptance**: `python -c "from scripts.executor.ci_triage import triage_ci_failure, TriageResult; print(TriageResult.__annotations__)"`

### Step 7: Refactor execute_recommendation.py to thin entrypoint
**File**: `scripts/execute_recommendation.py`
**Action**: Modify
**Description**: Replace the 3,100-line implementation with imports from `scripts/executor/` submodules. Keep `execute_recommendation()`, `_execute_recommendation_inner()`, `execute_batch()`, `get_eligible_recs()`, `topological_sort_recs()`, and `main()` in this file as orchestration logic. All helper functions move to submodules. Update `_fix_ci_failure()` to call `triage_ci_failure()` first and only escalate to LLM when `escalate_to_llm=True`.
**Acceptance**: `python -m scripts.execute_recommendation --help`

### Step 8: Update __init__.py with full re-exports
**File**: `scripts/executor/__init__.py`
**Action**: Modify
**Description**: Add re-exports for all public functions from submodules so that `from scripts.executor import execute_recommendation` and similar imports work. This maintains backward compatibility for any code that imported from the old monolith location.
**Acceptance**: `python -c "from scripts.executor import load_recommendation, execute_recommendation, triage_ci_failure"`

> **Phase B: Prompt Improvements**

### Step 9: Improve critique.prompt.md for machine-parseable output
**File**: `config/prompts/executor/critique.prompt.md`
**Action**: Modify
**Description**: Add explicit instruction that VERDICT must appear on its own line with exact format `VERDICT: APPROVED` or `VERDICT: NEEDS_REVISION`. No prose on the same line. Add instruction that violations must be numbered and cite the specific hard-fail rule. This enables reliable regex parsing in `critique_plan()`.
**Acceptance**: `grep -q "VERDICT must appear on its own line" config/prompts/executor/critique.prompt.md`

### Step 10: Improve implement-step.prompt.md for strict response format
**File**: `config/prompts/executor/implement-step.prompt.md`
**Action**: Modify
**Description**: Add rule: "Do not emit markdown headers, explanatory text, or summaries. Your entire response is file edit tool calls only." Add rule about Windows line endings: "Ensure all file writes use LF line endings, not CRLF." This reduces post-processing failures.
**Acceptance**: `grep -q "Do not emit markdown headers" config/prompts/executor/implement-step.prompt.md`

### Step 11: Improve refine.prompt.md to match planning format
**File**: `config/prompts/executor/refine.prompt.md`
**Action**: Modify
**Description**: Copy the acceptance command rules from planning.prompt.md: strict inline backtick format, relative paths, `python -m scripts.MODULE` form, no fenced code blocks, no prose after backtick. This ensures refined plans have the same parseable format as initial plans.
**Acceptance**: `grep -q "python -m scripts.MODULE" config/prompts/executor/refine.prompt.md`

### Step 12: Improve code-review.prompt.md for structured severity
**File**: `config/prompts/executor/code-review.prompt.md`
**Action**: Modify
**Description**: Add explicit instruction: "Each finding MUST start with exactly `CRITICAL:`, `HIGH:`, `MEDIUM:`, or `LOW:` followed by a space, then the file path, then a colon, then the description. No other formats are parseable." Add `GATE:` line requirement at end. This enables reliable regex parsing in `_code_review_gate()`.
**Acceptance**: `grep -q "Each finding MUST start with exactly" config/prompts/executor/code-review.prompt.md`

### Step 13: Create develop-executor.prompt.md for VS Code development
**File**: `.github/prompts/develop-executor.prompt.md`
**Action**: Create
**Description**: VS Code agent prompt for developing/debugging the executor. Includes: (1) module map showing which file handles which functionality, (2) instructions to run executor in test mode (`--dry-run`, `--step-limit 1`, `--no-merge`), (3) how to read telemetry logs and transcripts, (4) common failure patterns and their root causes, (5) how to add tests for edge cases. References the INTENT document.
**Acceptance**: `grep -q "develop-executor" .github/prompts/develop-executor.prompt.md`

> **Phase C: Tests**

### Step 14: Create tests for errors module
**File**: `tests/test_executor_errors.py`
**Action**: Create
**Description**: Tests for `scripts/executor/errors.py`: verify enum values exist, verify exception inheritance, verify string representations are useful for logging.
**Acceptance**: `python -m pytest tests/test_executor_errors.py -v`

### Step 15: Create tests for jsonl_store module
**File**: `tests/test_executor_jsonl_store.py`
**Action**: Create
**Description**: Tests for `scripts/executor/jsonl_store.py`: test `load_recommendation()` with found/not-found cases, test `load_all_recommendations()` with comment lines and blank lines, test `update_recommendation_status()` atomic write behavior, test encoding consistency (UTF-8).
**Acceptance**: `python -m pytest tests/test_executor_jsonl_store.py -v`

### Step 16: Create tests for plan module
**File**: `tests/test_executor_plan.py`
**Action**: Create
**Description**: Tests for `scripts/executor/plan.py`: test `parse_steps_from_plan()` with structured and numbered-list formats, test `ExecutionPlan` serialization, test `load_prompt()` with hash verification. Mock `copilot_call` for `generate_initial_plan` and `critique_plan` tests.
**Acceptance**: `python -m pytest tests/test_executor_plan.py -v`

### Step 17: Create tests for step_runner module
**File**: `tests/test_executor_step_runner.py`
**Action**: Create
**Description**: Tests for `scripts/executor/step_runner.py`: test `gather_step_context()` with modify/create actions, test `run_acceptance()` with valid commands, test `run_acceptance()` returns False (not True) for unparseable commands, test `commit_step()` retry logic.
**Acceptance**: `python -m pytest tests/test_executor_step_runner.py -v`

### Step 18: Create tests for postflight module
**File**: `tests/test_executor_postflight.py`
**Action**: Create
**Description**: Tests for `scripts/executor/postflight.py`: test `wait_for_ci()` polling logic, test `merge_pr()` stash/pop behavior, test `_scope_drift_check()` exclusion patterns. Mock subprocess calls throughout.
**Acceptance**: `python -m pytest tests/test_executor_postflight.py -v`

### Step 19: Create tests for ci_triage module
**File**: `tests/test_executor_ci_triage.py`
**Action**: Create
**Description**: Tests for `scripts/executor/ci_triage.py`: test lint error classification, test import error classification, test unknown error escalation, test `ruff check --fix` is called for lint category, test `escalate_to_llm=True` for test failures.
**Acceptance**: `python -m pytest tests/test_executor_ci_triage.py -v`

> **Phase D: Validation**

### Step 20: Run full test suite
**File**: N/A
**Action**: Validate
**Description**: Run `pytest tests/` to verify all existing and new tests pass. This includes the original `tests/test_execute_recommendation.py` which must still pass after the refactor.
**Acceptance**: `python -m pytest tests/ -v --tb=short`

### Step 21: Run validate.py
**File**: N/A
**Action**: Validate
**Description**: Run `python scripts/validate.py` to verify code quality (ruff, mypy, imports).
**Acceptance**: `python scripts/validate.py`

### Step 22: Report implementation summary
**File**: N/A
**Action**: Report
**Description**: Summarize what was implemented, any design decisions made during implementation, and any deviations from the plan.
**Acceptance**: N/A (reporting step)
