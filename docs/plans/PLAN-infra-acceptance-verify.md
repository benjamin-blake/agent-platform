# Plan

## Intent
Strengthen the autonomous execution loop with functional verification and cost guardrails, ensuring steps are validated against their stated goals and budget limits prevent runaway spending.

## Plan Type
IMPLEMENTATION

## Branch
agent/infra-acceptance-verify

## Phase
Workflow Infrastructure (self-improving loop refinement)

## Recommendations Implemented
- rec-032: Acceptance criteria verification
- rec-038: Cost budget kill switch

## Scope
| File | Action | Purpose |
|------|--------|---------|
| scripts/execute_recommendation.py | Modify | Add `run_acceptance()` helper and integrate in `implement_step()`; add cost tracking + budget check |
| config/prompts/executor/planning.prompt.md | Modify | Require runnable acceptance commands in step definitions |
| docs/GETTING_STARTED.md | Modify | Document acceptance command requirements for planners |
| tests/test_execute_recommendation.py | Modify | Tests for acceptance execution and cost budget scenarios |

## Acceptance Criteria
- [ ] `implement_step()` executes the step's acceptance command after `validate.py` passes
- [ ] Non-zero exit code from acceptance command fails the step
- [ ] Steps with empty acceptance fields use `validate.py` only (no error)
- [ ] Acceptance command execution has a 60-second timeout
- [ ] `execute_recommendation()` accepts `max_cost_usd` parameter (default $2.00)
- [ ] Cumulative cost tracked across plan generation, critique, and implementation calls
- [ ] Execution aborted with clear error when budget exceeded
- [ ] `--max-cost` CLI flag overrides default
- [ ] Test covers: acceptance pass, acceptance fail, empty acceptance, shlex parse error
- [ ] Test covers: budget exceeded mid-execution, cost=None handled gracefully

## Constraints
- Use `shlex.split()` to parse acceptance commands (never `shell=True`)
- Trust and execute any non-empty acceptance command — refine from telemetry later
- Handle `cost_usd=None` gracefully (OTel telemetry may not return cost)
- Windows-compatible command parsing

## Context
- rec-009 (recommendation executor) is closed — dependency satisfied
- `copilot_call()` already returns `cost_usd` from OTel telemetry
- Briefings: docs/plans/briefings/BRIEFING-rec-032.md, docs/plans/briefings/BRIEFING-rec-038.md

## Pre-Implementation Checklist
> The implementing agent must verify all items before editing any file.
- [ ] Branch confirmed not on `main`
- [ ] copilot_instructions.md read (rules, gotchas, file router)
- [ ] DECISIONS.md read (no conflicts with prior decisions)
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps

### Step 1: Add `run_acceptance()` helper function
**File:** scripts/execute_recommendation.py
**What:** Add a new function `run_acceptance(acceptance_cmd: str) -> bool` that:
- Returns `True` immediately if `acceptance_cmd` is empty or whitespace
- Uses `shlex.split()` to parse the command; if parse fails, log warning and return `False`
- Executes with `subprocess.run()`, `capture_output=True`, `timeout=60`
- Returns `True` on exit code 0, `False` otherwise
- Logs acceptance pass/fail with command and exit code
- Trust the planning agent — execute any non-empty command without filtering

### Step 2: Integrate acceptance verification into `implement_step()`
**File:** scripts/execute_recommendation.py
**What:** After the existing `validate.py` block (after line ~700), add:
- Extract `step.get("acceptance", "")`
- Call `run_acceptance(acceptance_cmd)`
- If returns `False`, log error and return `(False, step_cost)`
- Log success message if acceptance passed

### Step 3: Add cost tracking to `execute_recommendation()`
**File:** scripts/execute_recommendation.py
**What:**
- Add `max_cost_usd: float = 2.0` parameter to `execute_recommendation()` signature
- Initialize `cumulative_cost = 0.0` at function start
- After `generate_initial_plan()` call, add its cost to cumulative
- After `critique_plan()` call, add its cost to cumulative
- After each `implement_step()` call in the loop, add its cost to cumulative
- After each cost addition, check `if cumulative_cost > max_cost_usd:` and raise `CopilotResponseError(f"Cost budget exceeded: ${cumulative_cost:.2f} > ${max_cost_usd:.2f}")`

### Step 4: Add `--max-cost` CLI flag
**File:** scripts/execute_recommendation.py
**What:**
- Add argparse argument: `parser.add_argument("--max-cost", type=float, default=2.0, help="Maximum cost in USD before aborting")`
- Pass `max_cost_usd=args.max_cost` to `execute_recommendation()` call in `main()`

### Step 5: Update planning prompt for acceptance requirements
**File:** config/prompts/executor/planning.prompt.md
**What:** Update the Acceptance field instruction from:
```
**Acceptance**: Command to verify step (e.g., pytest tests/test_x.py -k test_name)
```
To:
```
**Acceptance**: REQUIRED runnable shell command that exits 0 on success (pytest, python -c, grep, git). Must be executable, not descriptive text.
```

### Step 6: Add tests for acceptance execution
**File:** tests/test_execute_recommendation.py
**What:** Add tests in a new `TestRunAcceptance` class:
- `test_run_acceptance_pass`: Mock subprocess returning exit code 0, assert returns `True`
- `test_run_acceptance_fail`: Mock subprocess returning exit code 1, assert returns `False`
- `test_run_acceptance_empty`: Empty string input, assert returns `True` without subprocess call
- `test_run_acceptance_parse_error`: Malformed command string, assert returns `False` with warning log
- `test_run_acceptance_timeout`: Mock subprocess.TimeoutExpired, assert returns `False`

### Step 7: Add tests for cost budget
**File:** tests/test_execute_recommendation.py
**What:** Add tests in `TestExecuteRecommendation` class:
- `test_cost_budget_exceeded`: Mock copilot_call returning cost that exceeds limit, assert raises `CopilotResponseError`
- `test_cost_none_handled`: Mock copilot_call returning `cost_usd=None`, assert continues without error (treat as 0)

### Step 8: Update GETTING_STARTED.md with acceptance requirements
**File:** docs/GETTING_STARTED.md
**What:** Add a section or paragraph explaining:
- Acceptance commands in plan steps must be runnable shell commands
- Commands are executed with 60s timeout and must exit 0 to pass
- Empty acceptance fields fall back to validate.py only
- Examples: `pytest tests/test_x.py -k test_name`, `python -c "import x; assert x.func()"`

### Step 9: Run pytest
**Command:** `pytest tests/test_execute_recommendation.py -v`
**What:** All tests must pass, including new acceptance and cost budget tests.

### Step 10: Run validate.py
**Command:** `python scripts/validate.py`
**What:** Must exit 0 with no lint or type errors.

### Step 11: Report implementation summary
**What:** Summarize what was implemented and any design decisions made during implementation.
