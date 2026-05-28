# Plan

## Intent
Reduce Gemini CLI executor token consumption by 800x for XS/S tasks (from ~340K tokens / $2.39 to ~16K tokens / $0.002 per implementation step), enabling the autonomous self-improvement loop to operate within the 30 GBP/month Gemini API budget at scale. This is foundational infrastructure for the North Star: every rec the system can execute cheaply is one more iteration of the feedback loop.

## Plan Type
IMPLEMENTATION

## Verification Tier
V2

## Branch
agent/platform-gemini-token-opt

## Phase
Platform (phase-independent governance)

## Scope
| File | Action | Purpose |
|------|--------|---------|
| GEMINI.md | Modify | Replace @copilot-instructions.md reference with inline executor-only context (~800 bytes) |
| scripts/executor/step_runner.py | Modify | Skip resume_session_id for XS/S effort; add Known Gotcha injection in gather_step_context() |
| scripts/execute_recommendation.py | Modify | Skip _seed_gemini_session() when effort is XS/S; save checkpoints at each phase boundary; add --auto-resume CLI flag |
| scripts/execution_state.py | Modify | Add PLAN_COMPLETE, REVIEW_COMPLETE, CI_PENDING checkpoint statuses |
| scripts/executor/postflight.py | Modify | Thread rec effort through to _code_review_gate so MODEL_REVIEW uses per-effort routing instead of hardcoded "M" |
| tests/test_execution_state.py | Modify | Add tests for new checkpoint statuses and transitions |
| tests/test_executor_step_runner.py | Modify | Add tests for resume_session_id skip and gotcha injection |
| tests/test_executor_postflight.py | Modify | Add test for effort-threaded review model resolution |
| tests/test_execute_recommendation.py | Modify | Add tests for warm_base skip, phase-boundary checkpoints, and --auto-resume dispatch |

## Bundled Recommendations
None -- this plan originates from a rec-325 post-mortem analysis session. Related open recs (rec-395: IMPL_COMPLETE checkpoint) are partially addressed by the state machine work in Area C.

## Acceptance Criteria
- [ ] GEMINI.md is < 1000 bytes and does NOT contain `@.github/copilot-instructions.md`
- [ ] XS/S implementation steps do NOT pass `resume_session_id` to `llm_call()`
- [ ] XS/S recs skip `_seed_gemini_session()` entirely
- [ ] `_code_review_gate()` receives the rec's actual effort level, not hardcoded "M"
- [ ] `execution_state.py` supports PLAN_COMPLETE, REVIEW_COMPLETE, CI_PENDING statuses
- [ ] `--auto-resume` flag reads checkpoint status and dispatches to the correct phase
- [ ] `gather_step_context()` injects relevant Known Gotchas based on target file path
- [ ] All existing tests pass (`python -m pytest tests/`)
- [ ] `python -m scripts.validate --scope all` exits 0

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-------------------|--------|
| 1 | pre-deploy | Confirm GEMINI.md has no @-reference and is < 1000 bytes | `python -c "p='GEMINI.md'; c=open(p).read(); assert '@' not in c, f'Found @ in {p}'; assert len(c)<1000, f'{len(c)} bytes'; print(f'OK: {len(c)} bytes, no @ refs')"` | Prints OK with byte count < 1000 | GEMINI.md still has @-reference or is too large |
| 2 | pre-deploy | Confirm gotcha injection returns correct content for known paths | `python -c "from scripts.executor.step_runner import _get_relevant_gotchas; g=_get_relevant_gotchas('tests/test_foo.py'); assert 'Test Isolation' in g, f'Missing gotcha: {g[:200]}'; g2=_get_relevant_gotchas('terraform/main.tf'); assert 'try()' in g2; g3=_get_relevant_gotchas('README.md'); assert g3==''; print('All gotcha paths OK')"` | Prints "All gotcha paths OK" | _get_relevant_gotchas returns wrong content or crashes |
| 3 | pre-deploy | Confirm new checkpoint statuses are valid | `python -c "from scripts.execution_state import save_checkpoint, load_checkpoint; save_checkpoint(branch='test', plan_file='test', current_step=1, total_steps=1, status='PLAN_COMPLETE'); s=load_checkpoint(); assert s['status']=='PLAN_COMPLETE'; print('PLAN_COMPLETE OK')"` | Prints "PLAN_COMPLETE OK" | Status rejected or not persisted |
| 4 | pre-deploy | Confirm gotcha content appears in gather_step_context output | `python -c "from scripts.executor.step_runner import gather_step_context; ctx=gather_step_context({'file':'terraform/iceberg_tables.tf','action':'modify'}); assert 'Known Gotcha' in ctx.get('file_content','') or 'try()' in ctx.get('file_content',''), 'Gotcha not injected'; print('Gotcha injection OK')"` | Prints "Gotcha injection OK" | gather_step_context does not inject gotchas for .tf files |
| 5 | pre-deploy | Run full test suite | `python -m pytest tests/ -x -q` | All tests pass | Test failures indicate regression |
| 6 | pre-deploy | Run full validation | `python -m scripts.validate --scope all` | Exit code 0 | Validation failure |

## Constraints
- Executor self-modification boundary: `scripts/executor/step_runner.py`, `scripts/executor/postflight.py`, and `scripts/execute_recommendation.py` are boundary files. This plan is implemented via `/implement` (not the executor itself). See Decision 44.
- Windows Git Bash: No PowerShell. Python scripts for automation.
- GEMINI.md is loaded by the Gemini CLI on every invocation -- cannot be skipped, only slimmed.
- `--resume` (Gemini session) saves latency but NOT cost -- Google bills all cached tokens as input_tokens.

## Context
- **Source:** rec-325 post-mortem. First successful Gemini CLI executor run consumed 340K tokens ($2.39) for a single-line XS edit. 7 prior failures consumed another ~2M tokens ($12+). Total daily spend: 11.64 GBP against a 30 GBP monthly cap.
- **Root causes:** (1) `--resume` replays planning session in full (~300K tokens). (2) copilot-instructions.md (30K chars) appears ~4x in context. (3) Pro model for all effort levels. (4) warm_base session adds autonomous file reads to resume payload.
- **Briefing:** `docs/plans/briefings/BRIEFING-token-optimisation.md` has the full analysis.
- **Existing infrastructure:** `execution_state.py` already has IN_PROGRESS and IMPL_COMPLETE checkpoints. `copilot_model_routing.yaml` already has XS=flash, S=auto effort bands for implementation. `--resume-postflight` flag exists but requires manual invocation.
- **PLAN-infra-autonomous-executor (related):** Strategic plan for rescue agents and full autonomy. This plan provides the deterministic checkpoint foundation that rescue agents would plug into. No overlap in scope.
- **Decision 53:** Gemini CLI is active executor provider. Flash for planning, Pro for implementation (current). This plan changes implementation to Flash for XS/S.

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main`
- [ ] copilot-instructions.md read (rules, gotchas, file router)
- [ ] DECISIONS.md read (no conflicts with prior decisions)
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps

### Step 1: Rewrite GEMINI.md as slim executor context
**File:** `GEMINI.md`
**Action:** Modify

Remove the `@.github/copilot-instructions.md` reference. Replace the entire file with a purpose-built executor context containing only:
- Role declaration: "You are an executor. Implement the requested code change. Do not plan, ask questions, or act as a supervisor."
- Code style: "Python 3.12+, type hints required. No emojis. Use sympy for formula evaluation, never eval()/exec()."
- Safety: "Only modify files explicitly listed in the step. Do not create new files unless instructed."
- Formatting: "Follow ruff formatting. Line length limit 127 chars."

The file must be < 1000 bytes total. Do NOT reference any other file via `@`.

**Acceptance:** `python -c "c=open('GEMINI.md').read(); assert '@' not in c; assert len(c)<1000; print('OK')"`

### Step 2: Add Known Gotcha injection to gather_step_context()
**File:** `scripts/executor/step_runner.py`
**Action:** Modify

Add a new helper function `_get_relevant_gotchas(file_path: str) -> str` that returns a string of relevant Known Gotchas based on the target file path. The mapping should be a module-level dict `_GOTCHA_MAP` with entries like:

```python
_GOTCHA_MAP: dict[str, list[str]] = {
    "terraform/": [
        "Terraform File-Optional Operations: Always wrap filemd5() and file() calls on optional artifacts with try().",
    ],
    "scripts/executor/": [
        "replace_string_in_file context boundary: Include 3-5 lines of unchanged code before and after target text.",
        "ruff E501 and multi-line section builders: Define intermediate variables for long f-strings to stay under 127 chars.",
    ],
    ".github/copilot-instructions.md": [
        "replace_string_in_file context boundary: Include 3-5 lines of unchanged code before and after target text.",
    ],
    "tests/": [
        "Test Isolation Patterns: Never spawn pytest tests/ from a script any test imports.",
        "ruff format duplicate import consolidation: Never split the same module imports across two blocks.",
    ],
    "src/data/handlers/": [
        "Import Safety Patterns: Never raise exceptions during module import.",
        "Lambda deployment pipeline: Any plan modifying Lambda-packaged files must include build and deploy steps.",
    ],
}
```

In `gather_step_context()`, after assembling the result dict, check if any `_GOTCHA_MAP` key is a prefix of (or substring in) the step's file path. If matches found, append a `## Relevant Known Gotchas` section to `result["file_content"]` with the matched gotcha strings. Cap the gotcha injection at 2000 chars to stay within the context budget.

**Acceptance:** `python -c "from scripts.executor.step_runner import _get_relevant_gotchas; g=_get_relevant_gotchas('terraform/main.tf'); assert 'try()' in g; print('OK')"`

### Step 3: Skip resume_session_id for XS/S effort in implement_step()
**File:** `scripts/executor/step_runner.py`
**Action:** Modify

In the `implement_step()` function, add a guard before the `resume_session_id` is passed to `llm_call()`. If `effort` (after resolution at line ~993) is in `("XS", "S")`, set `resume_session_id = None` and log:
```python
if effort.upper() in ("XS", "S") and resume_session_id:
    logger.info("[IMPL] Step %d: effort=%s -- skipping session resume (token cost optimisation)", step_n, effort)
    resume_session_id = None
```

Place this immediately after line `effort = effort or step.get("effort", "")` (line ~993) and before the prompt assembly.

**Acceptance:** `grep -q "skipping session resume" scripts/executor/step_runner.py`

### Step 4: Skip _seed_gemini_session() for XS/S effort
**File:** `scripts/execute_recommendation.py`
**Action:** Modify

In the main `execute_recommendation()` function, where `_seed_gemini_session()` is called (around line 2026), wrap it in an effort check:
```python
_effort = rec.get("effort", "").upper()
_resume_enabled = os.getenv("PLAN_SESSION_RESUME", "true").lower() not in ("false", "0")
_base_session_id: str = ""
from scripts.model_registry import resolve_provider

if _resume_enabled and resolve_provider() == "gemini" and _effort not in ("XS", "S"):
    _base_session_id = _seed_gemini_session()
elif _effort in ("XS", "S"):
    logger.info("[WARM] Skipping session seed for effort=%s (token cost optimisation)", _effort)
```

This ensures XS/S recs never pay the warm_base token cost.

**Acceptance:** `grep -q "Skipping session seed for effort" scripts/execute_recommendation.py`

### Step 5: Thread rec effort through to _code_review_gate()
**File:** `scripts/executor/postflight.py`
**Action:** Modify

1. Remove the module-level `MODEL_REVIEW` constant (line 36).
2. Change `_code_review_gate()` signature to accept an `effort: str = ""` parameter.
3. Inside `_code_review_gate()`, replace the reference to `MODEL_REVIEW` with a local resolution: `review_model = model_registry.resolve_model("review", effort or "M")`.
4. Update the `llm_call()` inside `_code_review_gate()` to use `model=review_model if review_model else None`.
5. Also update `_fix_code_review_findings()` if it references `MODEL_REVIEW` -- use the same pattern.

**File:** `scripts/execute_recommendation.py`
**Action:** Modify

Update ALL call sites for `_code_review_gate()` to pass `effort=rec.get("effort", "")`. There are 4 call sites:
- Single-rec path: lines ~2514 and ~2535 in `execute_recommendation()`
- Compound path: lines ~3870 and ~3885 in compound execution

For compound batches (lines ~3870/3885), the synthetic `compound_rec` may aggregate multiple effort levels. Pass `effort=""` (empty string) to trigger the "M" fallback default, since compound batches do not have a single effort level.

**Acceptance:** `python -c "import ast; t=ast.parse(open('scripts/executor/postflight.py').read()); funcs=[n for n in ast.walk(t) if isinstance(n, ast.FunctionDef) and n.name=='_code_review_gate']; args=[a.arg for a in funcs[0].args.args]; assert 'effort' in args; print('OK')"`

### Step 6: Add new checkpoint statuses to execution_state.py
**File:** `scripts/execution_state.py`
**Action:** Modify

1. Add a module-level constant for valid statuses:
```python
VALID_STATUSES = frozenset({
    "IN_PROGRESS",
    "PLAN_COMPLETE",
    "IMPL_COMPLETE",
    "REVIEW_COMPLETE",
    "CI_PENDING",
    "COMPLETED",
})
```

2. In `save_checkpoint()`, add validation: `if status not in VALID_STATUSES: logger.warning("Unknown checkpoint status: %s", status)`.

3. Update the `ExecutionState` TypedDict docstring to list all valid statuses.

**Acceptance:** `python -c "from scripts.execution_state import VALID_STATUSES; assert 'CI_PENDING' in VALID_STATUSES; assert 'REVIEW_COMPLETE' in VALID_STATUSES; print('OK')"`

### Step 7: Save checkpoints at each phase boundary in execute_recommendation()
**File:** `scripts/execute_recommendation.py`
**Action:** Modify

Add `save_checkpoint()` calls at these phase transitions (all in `execute_recommendation()`):

1. After plan + critique passes (before implementation loop starts):
```python
save_checkpoint(branch=branch, plan_file=rec_id, current_step=0, total_steps=total_steps, status="PLAN_COMPLETE")
```

2. After code review passes (before finalize):
```python
save_checkpoint(branch=branch, plan_file=rec_id, current_step=steps_completed, total_steps=total_steps, status="REVIEW_COMPLETE")
```

3. After PR is created but before CI poll (inside `finalize()` or just before `finalize()` call):
```python
save_checkpoint(branch=branch, plan_file=rec_id, current_step=steps_completed, total_steps=total_steps, status="CI_PENDING")
```

The existing IN_PROGRESS and IMPL_COMPLETE saves remain unchanged.

**Acceptance:** `grep -c "save_checkpoint" scripts/execute_recommendation.py | python -c "import sys; n=int(sys.stdin.read().strip()); assert n>=5, f'Expected >=5 save_checkpoint calls, found {n}'; print(f'OK: {n} calls')"`

### Step 8: Add --auto-resume flag and dispatch logic
**File:** `scripts/execute_recommendation.py`
**Action:** Modify

1. Add `--auto-resume` argument to the argparser:
```python
parser.add_argument(
    "--auto-resume",
    action="store_true",
    help="Automatically resume from checkpoint state (dispatches to correct phase based on status)",
)
```

2. In `execute_recommendation()`, add the `auto_resume: bool = False` parameter.

3. In the checkpoint handling section (around line 1604), add auto-resume dispatch logic:
```python
if auto_resume and checkpoint is not None and checkpoint.get("plan_file") == rec_id:
    cp_status = checkpoint.get("status", "")
    if cp_status == "CI_PENDING":
        # Jump straight to finalize (CI poll + merge)
        skip_to_postflight = True
        skip_to_finalize = True
        logger.info("[AUTO-RESUME] Status=%s -- jumping to CI poll + merge", cp_status)
    elif cp_status == "REVIEW_COMPLETE":
        # Jump to finalize (push + PR + CI)
        skip_to_postflight = True
        skip_to_finalize = True
        logger.info("[AUTO-RESUME] Status=%s -- jumping to push + PR + CI", cp_status)
    elif cp_status == "IMPL_COMPLETE":
        # Jump to postflight (code review + finalize)
        skip_to_postflight = True
        logger.info("[AUTO-RESUME] Status=%s -- jumping to postflight", cp_status)
    elif cp_status == "PLAN_COMPLETE":
        # Jump to implementation loop (step 1)
        resume_from_step = 0
        logger.info("[AUTO-RESUME] Status=%s -- jumping to implementation loop", cp_status)
    elif cp_status == "IN_PROGRESS":
        resume_from_step = checkpoint.get("current_step", 0)
        logger.info("[AUTO-RESUME] Status=%s -- resuming from step %d", cp_status, resume_from_step + 1)
```

4. Wire `auto_resume=args.auto_resume` in the CLI dispatch.

5. Make `--auto-resume`, `--resume`, and `--resume-postflight` mutually exclusive via `argparse.add_mutually_exclusive_group()`. If `--auto-resume` is provided alongside `--resume` or `--resume-postflight`, the parser should reject the invocation with a clear error.

Note: `skip_to_finalize` is a new boolean that must be threaded through the postflight section to skip code review when resuming from REVIEW_COMPLETE or CI_PENDING. Add it alongside the existing `skip_to_postflight` flag.

**Acceptance:** `python -m scripts.execute_recommendation --help | grep -q "auto-resume"`

### Step 9: Update tests for new checkpoint statuses
**File:** `tests/test_execution_state.py`
**Action:** Modify

Add test cases:
- `test_save_and_load_plan_complete`: Save with status="PLAN_COMPLETE", load, assert status matches.
- `test_save_and_load_review_complete`: Save with status="REVIEW_COMPLETE", load, assert status matches.
- `test_save_and_load_ci_pending`: Save with status="CI_PENDING", load, assert status matches.
- `test_valid_statuses_constant`: Assert VALID_STATUSES contains all expected values.

**Acceptance:** `python -m pytest tests/test_execution_state.py -x -q`

### Step 10: Update tests for resume skip and gotcha injection
**File:** `tests/test_executor_step_runner.py`
**Action:** Modify

Add test cases:
- `test_implement_step_xs_skips_resume`: Mock llm_call, call implement_step with effort="XS" and resume_session_id="fake-id". Assert llm_call was called with resume_session_id=None.
- `test_get_relevant_gotchas_terraform`: Call _get_relevant_gotchas("terraform/main.tf"), assert "try()" in result.
- `test_get_relevant_gotchas_no_match`: Call _get_relevant_gotchas("README.md"), assert result is empty string.
- `test_get_relevant_gotchas_tests_dir`: Call _get_relevant_gotchas("tests/test_foo.py"), assert "Test Isolation" in result.

**Acceptance:** `python -m pytest tests/test_executor_step_runner.py -x -q`

### Step 11: Update tests for effort-threaded review model
**File:** `tests/test_executor_postflight.py`
**Action:** Modify

Add test case:
- `test_code_review_gate_receives_effort`: Mock llm_call and model_registry.resolve_model. Call _code_review_gate with effort="XS". Assert resolve_model was called with ("review", "XS") not ("review", "M").

**Acceptance:** `python -m pytest tests/test_executor_postflight.py -x -q`

### Step 12: Update tests for warm_base skip, phase checkpoints, and auto-resume
**File:** `tests/test_execute_recommendation.py`
**Action:** Modify

Add test cases:
- `test_xs_effort_skips_seed_session`: Mock _seed_gemini_session. Execute with effort="XS". Assert _seed_gemini_session was NOT called.
- `test_auto_resume_from_impl_complete`: Set up an IMPL_COMPLETE checkpoint. Call execute_recommendation with auto_resume=True. Assert it skips to postflight.
- `test_auto_resume_from_ci_pending`: Set up a CI_PENDING checkpoint. Assert it skips to finalize.

Note: This file is very large (~300K). Add tests to existing test classes where appropriate. Keep test methods focused and minimal. Be aware of the postflight function mock exhaustion gotcha -- count subprocess.run mock side_effects carefully.

**Acceptance:** `python -m pytest tests/test_execute_recommendation.py -x -q --timeout=120`

### Step 13: Run full test suite
Run `python -m pytest tests/ -x -q` -- all tests must pass.

**Acceptance:** `python -m pytest tests/ -x -q`

### Step 14: Run full validation
Run `python -m scripts.validate --scope all` -- must exit 0.

**Acceptance:** `python -m scripts.validate --scope all`

### Step 15: Execute Verification Plan
Run each step from the Verification Plan table above. If a step fails, fix the code, re-run tests + validate, and re-attempt. Loop until all steps pass. Do NOT merge with failing verification.

### Step 16: Report
Report: what was implemented, verification results (actual outcomes), bugs found and fixed.
