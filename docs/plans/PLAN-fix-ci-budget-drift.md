# Plan

## Intent
Restore the token-budget kill-switch that was silently dropped during the ExecutionPlan
migration from `cost_usd` to `tokens_used`, and add a conftest.py sentinel that blocks
unit tests from calling LLM CLI subprocesses - preventing the class of CI/local environment
drift that hid this regression for 10+ days.

## Plan Type
IMPLEMENTATION

## Verification Tier
V2

## Branch
agent/fix-ci-budget-drift

## Phase
Phase 1: Core Infrastructure - COMPLETE (maintenance fix)

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `scripts/execute_recommendation.py` | Modify | Re-add `PLAN_TOKEN_BUDGET` check after plan generation |
| `tests/test_execute_recommendation.py` | Modify | Patch `PLAN_TOKEN_BUDGET=500` so `tokens_used=1000` triggers abort |
| `tests/conftest.py` | Modify | Add autouse sentinel blocking LLM CLI subprocess calls in unit tests |

## Bundled Recommendations
None. rec-499 (`_load_prompt_compliance` sys.path injection) was already implemented
in validate.py lines 93-102 - the rec status was not updated to closed.

## Acceptance Criteria
- [ ] `pytest tests/test_execute_recommendation.py::TestExecuteRecommendation::test_cost_budget_exceeded -v` passes
- [ ] Full test suite passes: `pytest tests/ -v -m "not integration"` (no regressions from sentinel)
- [ ] Sentinel fires correctly: a bare subprocess call to `gemini` in a unit test raises `RuntimeError`
- [ ] `validate.py --quick` passes (lint/format clean)

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-------------------|--------|
| 1 | pre-deploy | Run previously-failing test | `.venv/Scripts/python.exe -m pytest tests/test_execute_recommendation.py::TestExecuteRecommendation::test_cost_budget_exceeded -v` | `PASSED` | Budget check absent or env var not set in test |
| 2 | pre-deploy | Confirm no subprocess escape | `.venv/Scripts/python.exe -m pytest tests/test_execute_recommendation.py::TestExecuteRecommendation::test_cost_budget_exceeded -v -s` | Clean pass, no `FileNotFoundError: gemini` in output | Sentinel not applied; verify autouse scope |
| 3 | pre-deploy | Full suite - no regressions | `.venv/Scripts/python.exe -m pytest tests/ -m "not integration" -x -q` | All tests pass | If `RuntimeError: Unit test reached LLM CLI`, the failing test is missing a mock - fix the mock, do not widen `_LLM_CLI_NAMES` |
| 4 | pre-deploy | Lint and format | `.venv/Scripts/python.exe -m scripts.validate --quick` | `All checks passed!` | Run `ruff format` on modified files and re-run |

## Constraints
- The sentinel must not block `subprocess.run` calls to `git`, `python`, `aws`, `gh` - only LLM CLI tools.
- The sentinel must explicitly skip tests carrying the `integration` marker (via `request.node.own_markers`) so it does not interfere if integration tests are run directly outside of CI.
- Do not modify `validate.py` or any boundary file as part of this fix.
- Default `PLAN_TOKEN_BUDGET=200000` (200K tokens) - permits normal planning calls (5K-150K tokens) while catching runaway plans.

## Context
- **Root cause:** Commit `e049c77` (March 31) added a `PLAN_COST_BUDGET_USD` kill-switch
  and `test_cost_budget_exceeded`. A later refactor replaced `cost_usd` with `tokens_used`
  on `ExecutionPlan`. The test was updated to `tokens_used=1000` but the production-code
  check was never re-implemented.
- **Why it surfaced May 1:** April 28-30 CI failures were GitHub Actions billing (spending
  limit - jobs never started). Once billing resolved, the test failure was exposed.
- **Systemic gap:** The gemini CLI exists on Windows (dev) but not on Ubuntu CI. Without
  the budget check the test fell through to `critique_plan` -> `_gemini_call` ->
  `subprocess.run(["gemini", ...])` -> `FileNotFoundError`. The sentinel closes this class
  of drift for any future LLM CLI tool.
- **rec-499 not bundled:** `_load_prompt_compliance()` in validate.py already has sys.path
  injection at lines 93-102. Code is fixed; rec status needs updating separately.

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main`
- [ ] `docs/PROJECT_CONTEXT.md` read
- [ ] `docs/DECISIONS.md` read
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps

1. Read `docs/PROJECT_CONTEXT.md` and `docs/DECISIONS.md` (pre-implementation checklist).

2. **`scripts/execute_recommendation.py`** - Locate the block inside
   `if not skip_to_postflight and not fast_mode:` after the plan-generation retry loop,
   immediately after the `save_plan(plan)` call and before
   `if plan.status == "acceptance_challenged":`. Insert:

   ```python
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
   ```

3. **`tests/test_execute_recommendation.py`** - In `test_cost_budget_exceeded`, add
   `patch.dict("os.environ", {"PLAN_TOKEN_BUDGET": "500"})` to the existing `with (...):`
   context manager stack (string form avoids needing an `os` import), so
   `tokens_used=1000` exceeds the 500-token test limit.

4. **`tests/conftest.py`** - Add at module level after existing imports:

   ```python
   _LLM_CLI_NAMES: frozenset[str] = frozenset({"gemini", "gemini.CMD", "claude", "copilot"})
   ```

   Then add a new autouse fixture after the existing `_patch_write_run_summary` fixture:

   ```python
   @pytest.fixture(autouse=True)
   def _block_llm_cli_subprocess(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
       """Prevent unit tests from reaching LLM CLI subprocesses.

       Intercepts subprocess.run calls to known LLM CLI tools and raises
       RuntimeError with a diagnostic message. Guards against CI/local
       environment drift where a CLI tool exists on the developer machine
       but not on Ubuntu CI runners.

       Tests exercising LLM CLI code paths must mock subprocess.run (or the
       higher-level function) before reaching this guard. Tests marked
       @pytest.mark.integration are exempt.
       """
       if "integration" in [m.name for m in request.node.own_markers]:
           return

       import subprocess as _sp

       _orig_run = _sp.run

       def _guarded_run(args, *a, **kw):  # type: ignore[no-untyped-def]
           cmd = args[0] if isinstance(args, (list, tuple)) else args
           name = Path(str(cmd)).name
           if name in _LLM_CLI_NAMES:
               raise RuntimeError(
                   f"Unit test reached LLM CLI '{cmd}' without mocking. "
                   "Patch subprocess.run or the calling function before this point, "
                   "or mark the test @pytest.mark.integration."
               )
           return _orig_run(args, *a, **kw)

       monkeypatch.setattr(_sp, "run", _guarded_run)
   ```

5. **Execute Verification Plan** - run each VP step in order. Loop until all pass.
   If VP step 3 fails with `RuntimeError: Unit test reached LLM CLI`, fix the missing
   mock in that test - do NOT widen `_LLM_CLI_NAMES`.

6. Report: confirm `tests/test_execute_recommendation.py::TestExecuteRecommendation::test_cost_budget_exceeded`
   is the specific test that was failing before the fix, what the fix was, and VP results for all 4 steps.
