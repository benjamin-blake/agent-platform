# Plan

## Intent
Reduce executor retry waste by matching model capability to task complexity. Currently Haiku handles all planning, causing 7+ retries on S-effort recs due to poor instruction adherence. A deterministic model hierarchy (effort-based) with automatic escalation will reduce premium request burn from ~6x to ~1-2x per rec while maintaining automation.

## Plan Type
IMPLEMENTATION

## Branch
agent/infra-executor-model-hierarchy

## Phase
Phase 1.5: Infrastructure Hardening

## Scope
| File | Action | Purpose |
|------|--------|---------|
| scripts/executor/plan.py | Modify | Add `get_planning_model(effort)` function |
| scripts/executor/step_runner.py | Modify | Add `get_implementation_model(effort)` function |
| scripts/execute_recommendation.py | Modify | Hotfix branch logic + auto-file rec on fix |
| .github/prompts/develop-executor.prompt.md | Modify | Supervisor guidance for escalation/hotfix |
| .github/instructions/executor-planning.instructions.md | Modify | Consolidate into Acceptance Command Checklist |
| .github/instructions/executor-critique.instructions.md | Modify | Add deep analysis rules (call sites, mocks, line numbers) |
| config/prompts/executor/critique.prompt.md | Modify | Inject scope file list for deep analysis |
| tests/test_executor_plan.py | Modify | Tests for `get_planning_model()` |
| tests/test_execute_recommendation.py | Modify | Tests for hotfix branch creation |

## Acceptance Criteria
- [ ] `get_planning_model("XS")` returns `claude-haiku-4.5`
- [ ] `get_planning_model("S")` returns `claude-sonnet-4.5`
- [ ] `get_planning_model("M")` returns `claude-sonnet-4.5`
- [ ] `get_planning_model("L")` returns `claude-opus-4`
- [ ] `get_planning_model("XL")` returns `claude-opus-4`
- [ ] `get_implementation_model("XS")` returns `gpt-4.1`
- [ ] `get_implementation_model("S")` returns `claude-haiku-4.5`
- [ ] All model functions have Sonnet fallback on 3 consecutive failures
- [ ] Hotfix branches created as `agent/rec-{id}-hotfix-{slug}` when supervisor makes mid-flight fixes
- [ ] Rec auto-filed when hotfix branch created (status: open, source: executor-hotfix)
- [ ] `executor-critique.instructions.md` requires FILES READ section with line counts
- [ ] `executor-critique.instructions.md` requires call site verification with line numbers
- [ ] `executor-critique.instructions.md` requires mock pattern identification
- [ ] `executor-planning.instructions.md` contains consolidated Acceptance Command Checklist
- [ ] `develop-executor.prompt.md` contains escalation threshold guidance (3 failures = next model)
- [ ] `develop-executor.prompt.md` contains hotfix branch guidance (never commit to main mid-retry)
- [ ] All tests pass: `python -m pytest tests/test_executor_plan.py tests/test_execute_recommendation.py -q`

## Constraints
- Model names must match `config/copilot_model_multipliers.yaml` entries
- Environment variable `COPILOT_MODEL_PLANNING` overrides the hierarchy (existing behavior preserved)
- Environment variable `COPILOT_MODEL_CRITIQUE` sets critique model (default: gemini-2.5-pro)
- Hotfix rec filing uses existing `update_recommendation_status()` from jsonl_store.py
- No new dependencies allowed

## Context
- **Decision 39:** Step Functions for deterministic scheduling (relevant: escalation is deterministic, not AI-decided)
- **rec-170 failure analysis:** 7 planning failures at 0.33x each = 2.3x burned; single Sonnet = 1x
- **Cost multipliers:** Haiku=0.33x, Sonnet=1x, Opus=3x, GPT-4.1=0x, Gemini 2.5 Pro=1x
- **Known gotcha:** `COPILOT_MODEL_PLANNING` env var already exists and must remain as override

## Pre-Implementation Checklist
> The implementing agent must verify all items before editing any file.
- [ ] Branch confirmed not on `main`
- [ ] copilot-instructions.md read (rules, gotchas, file router)
- [ ] DECISIONS.md read (no conflicts with prior decisions)
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps

### Step 1: Add model selection functions to plan.py
**File:** scripts/executor/plan.py
**Action:** Add `get_planning_model(effort: str) -> str` function that returns:
- XS: `claude-haiku-4.5`
- S, M: `claude-sonnet-4.5`
- L, XL: `claude-opus-4`
- Default/unknown: `claude-sonnet-4.5`

Add `_PLANNING_FAILURE_COUNT` module-level dict to track consecutive failures per rec_id.
Add `escalate_planning_model(rec_id: str, current_model: str) -> str` that:
- Increments failure count
- If count >= 3, returns next tier (haiku->sonnet->opus->None for human)
- Resets count on success

Preserve existing `COPILOT_MODEL_PLANNING` env var override (check first, before hierarchy).

**Integration point:** Modify `generate_initial_plan()` to call `get_planning_model(effort)` and use its return value for the `model` parameter in `copilot_call`. The effort level is available from the rec's JSONL entry.

**Acceptance:** `grep -q 'def get_planning_model' scripts/executor/plan.py && grep -q 'def escalate_planning_model' scripts/executor/plan.py`

### Step 2: Add model selection to step_runner.py
**File:** scripts/executor/step_runner.py
**Action:** Add `get_implementation_model(effort: str) -> str` function that returns:
- XS: `gpt-4.1`
- S, M, L, XL: `claude-haiku-4.5`
- Default: `claude-haiku-4.5`

Add `SONNET_FALLBACK = "claude-sonnet-4.5"` constant.
Add `_IMPL_FAILURE_COUNT` tracking similar to plan.py.

**Integration point:** Modify `implement_step()` to call `get_implementation_model(effort)` and use its return value for the `model` parameter in `copilot_call`. The effort level is passed down from execute_recommendation.py.

**Acceptance:** `grep -q 'def get_implementation_model' scripts/executor/step_runner.py && grep -q 'SONNET_FALLBACK' scripts/executor/step_runner.py`

### Step 3: Add hotfix branch logic to execute_recommendation.py
**File:** scripts/execute_recommendation.py
**Action:** Add `create_hotfix_branch(rec_id: str, slug: str) -> str` function that:
- Creates branch `agent/rec-{rec_id}-hotfix-{slug}`
- Returns the branch name

Add `file_hotfix_rec(rec_id: str, hotfix_slug: str, description: str) -> str` function that:
- Generates next rec ID using `get_next_rec_id()` pattern (read existing max + 1)
- Creates rec entry with: status=open, source=executor-hotfix, effort=XS, automatable=true
- Context references the parent rec_id
- Returns new rec ID

These functions are called by the supervisor (develop-executor.prompt.md) when making mid-flight fixes.

**Acceptance:** `grep -q 'def create_hotfix_branch' scripts/execute_recommendation.py && grep -q 'def file_hotfix_rec' scripts/execute_recommendation.py`

### Step 4: Update develop-executor.prompt.md with supervisor guidance
**File:** .github/prompts/develop-executor.prompt.md
**Action:** Add new section after the existing workflow sections:

```markdown
## Escalation and Hotfix Protocol

### Model Escalation
- After 3 consecutive planning failures on the same rec, escalate to the next model tier
- XS (Haiku) -> S/M (Sonnet) -> L/XL (Opus) -> Human intervention required
- Do NOT manually retry with the same model more than 3 times

### Hotfix Branch Protocol
When you need to fix executor machinery (plan.py, step_runner.py, etc.) during a rec run:
1. **Never commit fixes directly to main** between retries
2. Create a hotfix branch: `agent/rec-{id}-hotfix-{slug}`
3. Commit fixes to the hotfix branch
4. Auto-file a rec to review whether the fix addresses root cause vs symptom
5. Only merge hotfix to main after the original rec succeeds OR after 3 total failures

### Failure Threshold
- After 3 total failures (across all models), pause and file a rec for the underlying issue
- Do not continue retrying indefinitely
```

**Acceptance:** `grep -q 'Hotfix Branch Protocol' .github/prompts/develop-executor.prompt.md && grep -q 'Model Escalation' .github/prompts/develop-executor.prompt.md`

### Step 5: Consolidate executor-planning.instructions.md
**File:** .github/instructions/executor-planning.instructions.md
**Action:** Replace scattered acceptance command rules with a consolidated checklist section:

```markdown
## Acceptance Command Checklist

Before generating any acceptance command, verify ALL of these:

### Banned Patterns (immediate NEEDS_REVISION)
- [ ] NO `python -c "..."` one-liners (breaks on Windows, nested quotes fail)
- [ ] NO `grep -q 'fn()'` with empty parentheses (implementation may add parameters)
- [ ] NO `grep -qE '^[N-M]$'` range counts (LLM may generate more/fewer items)
- [ ] NO references to test functions created in later steps
- [ ] NO `validate.py --ci` (use `validate.py --quick` for step acceptance)
- [ ] NO module-level imports from `scripts.*` in validate.py (must be inside function body)

### Required Patterns
- [ ] Use `grep -q 'def function_name'` for function existence (no parens, no args)
- [ ] Use `python -m pytest tests/test_file.py::TestClass -q` for test validation
- [ ] Use relative paths from repo root
- [ ] Acceptance must be a SINGLE inline backtick command, no trailing prose

### Examples
GOOD: `grep -q 'def validate_recommendations_schema' scripts/validate.py`
BAD: `grep -q 'validate_recommendations_schema()' scripts/validate.py`

GOOD: `python -m pytest tests/test_executor_plan.py::TestModelSelection -q`
BAD: `python -c "from scripts.executor.plan import get_planning_model; assert get_planning_model('XS') == 'claude-haiku-4.5'"`
```

Remove the individual scattered rules that are now consolidated here.

**Acceptance:** `grep -q 'Acceptance Command Checklist' .github/instructions/executor-planning.instructions.md && grep -q 'Banned Patterns' .github/instructions/executor-planning.instructions.md`

### Step 6: Add deep analysis to executor-critique.instructions.md
**File:** .github/instructions/executor-critique.instructions.md
**Action:** Expand Phase 0 and add new deep analysis requirements:

```markdown
## Phase 0: Read Target Files (MANDATORY)
Before evaluating ANY rules, use the view tool to read EVERY file listed in the plan's scope. For each file:
- Read the ENTIRE file (all lines, not just headers)
- Note line numbers for functions being modified
- Note line numbers for any mocks in test files that depend on modified code

## Deep Analysis Rules (NEW)

13. **Call site verification:** For any function/class being modified, search for ALL usages. Cite line numbers. Flag usages not addressed by plan.
14. **Mock pattern identification:** For each source file, identify test mocks that depend on it. Cite line numbers.
15. **Line number citations required:** FILES READ section must include line counts proving full file read.
16. **Scope file completeness:** If plan scope has N files, FILES READ must list N files.

## Quality Gate (before outputting verdict)
- [ ] Read EVERY file in the plan's scope (not just .md files)
- [ ] Cite line numbers for functions being modified
- [ ] Cite line numbers for mocks that depend on modified code
- [ ] Your "FILES READ" list matches the scope file count

## Response Format Enhancement
FILES READ section format:
```
FILES READ:
- scripts/executor/plan.py (423 lines) - get_planning_model at L145, generate_initial_plan at L200
- tests/test_executor_plan.py (312 lines) - mock at L45, L89, L156
```
```

**Acceptance:** `grep -q 'Call site verification' .github/instructions/executor-critique.instructions.md && grep -q 'Mock pattern identification' .github/instructions/executor-critique.instructions.md`

### Step 7: Update critique.prompt.md with scope file injection
**File:** config/prompts/executor/critique.prompt.md
**Action:** Ensure the `{scope_files}` placeholder is present and add instruction to read all listed files before verdict.

Add after the scope files section:
```markdown
## Deep Analysis Required
You MUST read every file listed above before outputting your verdict. Your FILES READ section must:
1. List every scope file with line count
2. Cite line numbers for modified functions
3. Cite line numbers for affected mocks
4. If you cannot cite line numbers, you have not read the files — go back and read them.
```

**Acceptance:** `grep -q 'Deep Analysis Required' config/prompts/executor/critique.prompt.md`

### Step 8: Add tests for model selection
**File:** tests/test_executor_plan.py
**Action:** Add `TestModelSelection` class with tests:
- `test_get_planning_model_xs_returns_haiku`
- `test_get_planning_model_s_returns_sonnet`
- `test_get_planning_model_m_returns_sonnet`
- `test_get_planning_model_l_returns_opus`
- `test_get_planning_model_xl_returns_opus`
- `test_get_planning_model_unknown_returns_sonnet`
- `test_env_override_takes_precedence` (mock COPILOT_MODEL_PLANNING)
- `test_escalate_returns_next_tier_after_3_failures`

**Acceptance:** `python -m pytest tests/test_executor_plan.py::TestModelSelection -q`

### Step 9: Add tests for hotfix branch logic
**File:** tests/test_execute_recommendation.py
**Action:** Add `TestHotfixBranch` class with tests:
- `test_create_hotfix_branch_returns_correct_name`
- `test_file_hotfix_rec_creates_entry`
- `test_file_hotfix_rec_generates_next_id`
- `test_file_hotfix_rec_references_parent`

Mock `subprocess.run` for git commands and `update_recommendation_status` for JSONL writes.

**Acceptance:** `python -m pytest tests/test_execute_recommendation.py::TestHotfixBranch -q`

### Step 10: Run full validation
**File:** N/A
**Action:** Run pytest and validate.py to ensure all changes work together.

**Acceptance:** `python -m pytest tests/test_executor_plan.py tests/test_execute_recommendation.py tests/test_executor_step_runner.py -q && python scripts/validate.py --quick`

### Step 11: Report implementation summary
**Action:** Summarize what was implemented and any design decisions made during implementation.
