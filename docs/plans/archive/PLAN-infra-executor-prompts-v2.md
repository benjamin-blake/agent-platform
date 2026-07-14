# Plan

## Intent
Improve the autonomous executor's reliability and output quality by strengthening scope enforcement across all prompt layers, detecting critique cycling, hardening checkpoint cleanup, and adding documentation guidance. These changes reduce wasted executor runs and improve the quality of merged code.

## Plan Type
IMPLEMENTATION

## Branch
agent/infra-executor-prompts-v2

## Phase
Phase 1: Core Infrastructure (maintenance)

## Scope
| File | Action | Purpose |
|------|--------|---------|
| .github/prompts/develop-executor.prompt.md | Modify | Add SESSION_LOG guidance, --auto gotcha, validate --quick preflight, diff-stat scope review (rec-066, 067, 070, 071) |
| config/prompts/executor/planning.prompt.md | Modify | Add ARCHITECTURE guidance, Known Gotchas ref, test naming, CHANGELOG guidance, scope constraint (rec-069, 072, 073, 076, 080) |
| config/prompts/executor/critique.prompt.md | Modify | Add test quality Hard-Fail, scope-enforcement Hard-Fail (rec-074, 079) |
| config/prompts/executor/refine.prompt.md | Modify | Mirror all 7 Hard-Fail Rules from critique (rec-075) |
| config/prompts/executor/implement-step.prompt.md | Modify | Add Rule 8: don't alter previously-implemented code (rec-081) |
| docs/INTENT-recommendation-executor.md | Modify | Document _execute_recommendation_inner vs execute_recommendation boundary (rec-068) |
| scripts/executor/postflight.py | Modify | Add clear_checkpoint() call in cleanup_after_merge() success path (rec-078) |
| tests/test_executor_postflight.py | Modify | Add test for clear_checkpoint in cleanup_after_merge (rec-078) |
| scripts/executor/plan.py | Modify | Add critique cycling detection (rec-082, supersedes rec-065) |
| tests/test_executor_plan.py | Modify | Add tests for cycling detection (rec-082) |
| logs/.recommendations-log.jsonl | Modify | Close rec-065 as superseded, close rec-066 through rec-082 |

## Acceptance Criteria
- [ ] `grep -q "SESSION_LOG" .github/prompts/develop-executor.prompt.md`
- [ ] `grep -q "\-\-auto" .github/prompts/develop-executor.prompt.md`
- [ ] `grep -q "validate.*quick" .github/prompts/develop-executor.prompt.md`
- [ ] `grep -q "diff.stat\|scope.creep" .github/prompts/develop-executor.prompt.md`
- [ ] `grep -q "ARCHITECTURE" config/prompts/executor/planning.prompt.md`
- [ ] `grep -q "copilot-instructions\|Known Gotcha" config/prompts/executor/planning.prompt.md`
- [ ] `grep -q "test_executor_" config/prompts/executor/planning.prompt.md`
- [ ] `grep -q "CHANGELOG" config/prompts/executor/planning.prompt.md`
- [ ] `grep -q "declared scope\|outside.*recommendation" config/prompts/executor/planning.prompt.md`
- [ ] `grep -q "behavioural\|structural.*test\|pytest.*acceptance" config/prompts/executor/critique.prompt.md`
- [ ] `grep -q "target.file\|out.of.scope\|declared.*file" config/prompts/executor/critique.prompt.md`
- [ ] `grep -q "line-number\|empty acceptance\|step count" config/prompts/executor/refine.prompt.md`
- [ ] `grep -q "previously.*implemented\|outside.*step.*scope\|leave them exactly" config/prompts/executor/implement-step.prompt.md`
- [ ] `grep -q "_execute_recommendation_inner" docs/INTENT-recommendation-executor.md`
- [ ] `grep -q "clear_checkpoint" scripts/executor/postflight.py`
- [ ] `python -m pytest tests/test_executor_postflight.py::TestCleanupAfterMerge -v`
- [ ] `grep -q "cycling\|_detect_critique_cycling" scripts/executor/plan.py`
- [ ] `python -m pytest tests/test_executor_plan.py -k cycling -v`
- [ ] All closed recs have status "closed" in logs/.recommendations-log.jsonl
- [ ] `python -m pytest tests/` passes
- [ ] `python scripts/validate.py` exits 0

## Constraints
- Python 3.12+, type hints required
- Windows host with Git Bash shell
- No emojis in code or documentation
- Test file naming: `tests/test_executor_<module>.py` for executor submodules
- Line length limit: 127 characters (ruff E501)

## Context
- **rec-065 and rec-082** both address critique cycling; rec-082 has cleaner spec. Close rec-065 as superseded.
- **rec-076 revised**: Original spec was deterministic CHANGELOG append in postflight.py. Revised to add guidance in planning.prompt.md instructing planner to include CHANGELOG step for user-facing changes. This is lower risk and leverages the CLI agent's existing context.
- **rec-077** already closed (per-rec friction capture loop implemented in prior session).
- **Known Gotcha (subprocess fork explosion)**: Any subprocess.run(timeout=N) without tree-kill can orphan processes on Windows.
- **Known Gotcha (replace_string_in_file context)**: Include 3-5 lines before/after target text.

## Pre-Implementation Checklist
> The implementing agent must verify all items before editing any file.
- [ ] Branch confirmed not on `main`
- [ ] copilot_instructions.md read (rules, gotchas, file router)
- [ ] DECISIONS.md read (no conflicts with prior decisions)
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps

### Step 1: Update develop-executor.prompt.md with SESSION_LOG, --auto gotcha, validate --quick, diff-stat review
**File**: .github/prompts/develop-executor.prompt.md
**Action**: modify
**Description**: Add four improvements: (1) In Phase 6 Write Review section, add instruction to append session summary to docs/SESSION_LOG.md. (2) In Terminal Gotchas section, add entry about `gh pr merge --squash --auto` requiring branch protection rules. (3) In Phase 1 Environment Check, add step 5 to run `python -m scripts.validate --quick`. (4) In Phase 3 step 3 monitoring instructions, add guidance to scan diff stats for files outside the step's declared File field to detect scope creep.
**Acceptance**: `grep -q "SESSION_LOG" .github/prompts/develop-executor.prompt.md && grep -q "\-\-auto" .github/prompts/develop-executor.prompt.md`

### Step 2: Update planning.prompt.md with ARCHITECTURE, Known Gotchas, test naming, CHANGELOG, scope constraint
**File**: config/prompts/executor/planning.prompt.md
**Action**: modify
**Description**: Add five improvements: (1) Add conditional guidance to include ARCHITECTURE.md update step when rec creates new modules or changes cross-module interfaces. (2) Add note directing planner to check Known Gotchas in .github/copilot-instructions.md. (3) Add test file naming convention: `tests/test_executor_<module>.py` for executor submodules. (4) Add guidance to include CHANGELOG.md step when rec involves user-facing changes. (5) Add Banned Patterns entry for modifying functions not mentioned in the recommendation (scope constraint).
**Acceptance**: `grep -q "ARCHITECTURE" config/prompts/executor/planning.prompt.md && grep -q "CHANGELOG" config/prompts/executor/planning.prompt.md`

### Step 3: Update critique.prompt.md with test quality Hard-Fail and scope-enforcement Hard-Fail
**File**: config/prompts/executor/critique.prompt.md
**Action**: modify
**Description**: Add two Hard-Fail Rules: (1) Rule 8: Test steps whose acceptance command is a structural check (grep for function name) rather than behavioural verification (pytest execution) should be flagged as NEEDS_REVISION when pytest is feasible. (2) Rule 9: Steps whose File field does not match the recommendation's target file or its corresponding test file must be flagged as out-of-scope.
**Acceptance**: `grep -q "behavioural\|structural" config/prompts/executor/critique.prompt.md && grep -q "target.*file\|out.of.scope" config/prompts/executor/critique.prompt.md`

### Step 4: Update refine.prompt.md to mirror all Hard-Fail Rules
**File**: config/prompts/executor/refine.prompt.md
**Action**: modify
**Description**: The refine prompt currently lists only 4 fix instructions. Add instructions for Rules 5 (no line numbers), 6 (no empty acceptance), 7 (minimal step count), 8 (test quality), and 9 (scope enforcement) so the refine model knows how to address all critique violations.
**Acceptance**: `grep -q "line-number\|line number" config/prompts/executor/refine.prompt.md && grep -q "empty acceptance" config/prompts/executor/refine.prompt.md`

### Step 5: Update implement-step.prompt.md with Rule 8 (don't alter previously-implemented code)
**File**: config/prompts/executor/implement-step.prompt.md
**Action**: modify
**Description**: Add Rule 8: "Do not alter code sections outside the scope of this step. If other functions or classes exist in the file, leave them exactly as they are. Do not refactor, improve, or modify previously-implemented code even if you see potential improvements."
**Acceptance**: `grep -q "outside.*scope\|leave them exactly\|previously" config/prompts/executor/implement-step.prompt.md`

### Step 6: Update INTENT-recommendation-executor.md to document inner/outer function boundary
**File**: docs/INTENT-recommendation-executor.md
**Action**: modify
**Description**: Add a section explaining that `execute_recommendation()` is a thin exception-catching wrapper while `_execute_recommendation_inner()` contains the real orchestration logic including checkpoint management and eligibility checks. Tests that mock `execute_recommendation` miss all checkpoint logic; they should mock at the inner function level or below.
**Acceptance**: `grep -q "_execute_recommendation_inner" docs/INTENT-recommendation-executor.md`

### Step 7: Add clear_checkpoint() call to cleanup_after_merge() in postflight.py
**File**: scripts/executor/postflight.py
**Action**: modify
**Description**: At the end of `cleanup_after_merge()` success path (before `return True`), add a call to `clear_checkpoint()`. This ensures the checkpoint is cleared even if the orchestrator's success path is not reached due to an error elsewhere. The import for `clear_checkpoint` already exists at the top of the file.
**Acceptance**: `grep -q "clear_checkpoint" scripts/executor/postflight.py`

### Step 8: Add test for clear_checkpoint in cleanup_after_merge
**File**: tests/test_executor_postflight.py
**Action**: modify
**Description**: Add a test in TestCleanupAfterMerge that verifies `clear_checkpoint()` is called when cleanup succeeds. Mock subprocess.run to simulate successful git checkout, pull, and branch delete. Assert that `clear_checkpoint` was called once.
**Acceptance**: `python -m pytest tests/test_executor_postflight.py::TestCleanupAfterMerge -v -k checkpoint`

### Step 9: Add critique cycling detection to plan.py
**File**: scripts/executor/plan.py
**Action**: modify
**Description**: Add `_detect_critique_cycling()` function that tracks (step_n, rule_number) pairs across revisions. If the same (step_n, rule_number) pair appears in 2+ consecutive revisions, log a CRITIQUE-CYCLING warning. In the critique loop, if cycling is detected on the 3rd revision, auto-approve the plan instead of failing. This prevents infinite loops when critique and refine cannot resolve a pattern disagreement.
**Acceptance**: `grep -q "_detect_critique_cycling\|CRITIQUE-CYCLING\|cycling" scripts/executor/plan.py`

### Step 10: Add tests for critique cycling detection
**File**: tests/test_executor_plan.py
**Action**: modify
**Description**: Add TestCritiqueCycling class with tests: (1) test_no_cycling_when_violations_differ - different violations across revisions should not trigger cycling. (2) test_cycling_detected_same_step_same_rule - same (step_n, rule_number) in 2+ consecutive revisions triggers cycling. (3) test_auto_approve_on_cycling - when cycling is detected at revision 3, plan should be auto-approved.
**Acceptance**: `python -m pytest tests/test_executor_plan.py -k cycling -v`

### Step 11: Update recommendation statuses in JSONL
**File**: logs/.recommendations-log.jsonl
**Action**: modify
**Description**: Close rec-065 with status "closed" and note "superseded by rec-082". Close rec-066, rec-067, rec-068, rec-069, rec-070, rec-071, rec-072, rec-073, rec-074, rec-075, rec-076, rec-078, rec-079, rec-080, rec-081, rec-082 with status "closed". (rec-077 already closed.)
**Acceptance**: `grep '"id": "rec-082"' logs/.recommendations-log.jsonl | grep -q '"status": "closed"'`

### Step 12: Run pytest
**File**: N/A
**Action**: verify
**Description**: Run full test suite to verify all changes work together.
**Acceptance**: `python -m pytest tests/ -v`

### Step 13: Run validate.py
**File**: N/A
**Action**: verify
**Description**: Run full validation to ensure CI will pass.
**Acceptance**: `python scripts/validate.py`

### Step 14: Report implementation summary
**File**: N/A
**Action**: report
**Description**: Summarize what was implemented, any design decisions made, and confirm all acceptance criteria are met.
**Acceptance**: N/A (human review)
