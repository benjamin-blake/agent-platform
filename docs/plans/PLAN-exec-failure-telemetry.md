# Plan

## Intent
Enable post-execution analysis of autonomous runs by preserving partial work on failure (draft PR) and enriching telemetry with diff stats and prompt version hashes - supporting the self-improving feedback loop.

## Plan Type
IMPLEMENTATION

## Branch
agent/exec-failure-telemetry

## Phase
Phase E: Executor Completeness (workflow infrastructure)

## Scope
| File | Action | Purpose |
|------|--------|---------|
| scripts/execute_recommendation.py | Modify | Add failure cleanup (push + draft PR), diff capture in commit_step(), prompt hashing in load_prompt() |
| tests/test_execute_recommendation.py | Modify | Add tests for failure cleanup, diff capture, and prompt hashing |

## Acceptance Criteria
- [ ] On step failure, executor pushes partial branch to remote
- [ ] Draft PR created with `[FAILED]` prefix in title and failure details in body
- [ ] `commit_step()` captures `git diff HEAD~1 --stat` and returns it alongside success boolean
- [ ] `load_prompt()` returns `(template, hash)` tuple where hash = SHA-256[:12] of template content
- [ ] `ExecutionPlan` includes `prompt_hash` field for planning prompt
- [ ] Step telemetry includes `prompt_hash` for implement-step prompt
- [ ] Step telemetry includes `diff_stat` from commit
- [ ] All new code paths have test coverage with mocked subprocess/copilot_call
- [ ] `pytest tests/test_execute_recommendation.py` passes
- [ ] `python scripts/validate.py` exits 0

## Constraints
- Windows-compatible: all subprocess calls use `encoding='utf-8', errors='replace'`
- No new dependencies; uses stdlib hashlib
- Graceful fallback: diff/hash failures do not break execution flow

## Context
- rec-037: Branch cleanup on failure (briefing at docs/plans/briefings/BRIEFING-rec-037.md)
- rec-039: Diff capture in step telemetry (briefing at docs/plans/briefings/BRIEFING-rec-039.md)
- rec-040: Prompt template hashing (briefing at docs/plans/briefings/BRIEFING-rec-040.md)
- All three are low-risk, automatable, XS-S effort
- copilot_instructions.md: Windows subprocess encoding gotcha applies

## Pre-Implementation Checklist
> The implementing agent must verify all items before editing any file.
- [ ] Branch confirmed not on `main`
- [ ] copilot_instructions.md read (rules, gotchas, file router)
- [ ] DECISIONS.md read (no conflicts with prior decisions)
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps

### Step 1: Add hashlib import and modify load_prompt() to return (template, hash) tuple
**File**: scripts/execute_recommendation.py
**Action**: modify
**What**: Add `import hashlib` at top. Modify `load_prompt()` to compute SHA-256 hash of template content and return `(template, sha256(content)[:12])` tuple. Update docstring to document new return type.

### Step 2: Update all load_prompt() call sites to unpack tuple
**File**: scripts/execute_recommendation.py
**Action**: modify
**What**: In `generate_initial_plan()`, `critique_plan()`, `refine_plan()`, and `implement_step()` - unpack `(template, prompt_hash)` from `load_prompt()`. Store `prompt_hash` in relevant telemetry dicts.

### Step 3: Add prompt_hash field to ExecutionPlan dataclass
**File**: scripts/execute_recommendation.py
**Action**: modify
**What**: Add `prompt_hash: str = ""` field to `ExecutionPlan` dataclass. Update `generate_initial_plan()` to populate it.

### Step 4: Modify commit_step() to capture and return diff stat
**File**: scripts/execute_recommendation.py
**Action**: modify
**What**: After successful commit, run `git diff HEAD~1 --stat` and capture output. Change return type from `bool` to `tuple[bool, str]` where str is diff_stat (empty on failure). Use graceful fallback: if diff command fails, return empty string. Update caller (implementation loop) to unpack tuple and store diff_stat in step telemetry.

### Step 5: Add _handle_failure() function for branch cleanup
**File**: scripts/execute_recommendation.py
**Action**: modify
**What**: Create `_handle_failure(rec_id, rec, failure_step, failure_reason, total_cost, steps_completed, total_steps)` that:
1. Pushes partial branch: `git push --set-upstream origin agent/{rec_id}`
2. Creates draft PR: `gh pr create --draft --title "[FAILED] {rec_id}: {title}" --body "{details}"`
3. Logs warnings on push/PR errors but does not raise (best-effort cleanup)

### Step 6: Call _handle_failure() from failure paths in _execute_recommendation_inner()
**File**: scripts/execute_recommendation.py
**Action**: modify
**What**: At both failure points (step failure and finalize failure), call `_handle_failure()` before returning False. Pass failure context to populate PR body.

### Step 7: Add tests for prompt hashing
**File**: tests/test_execute_recommendation.py
**Action**: modify
**What**: Add `TestPromptHashing` class with tests:
- `test_load_prompt_returns_tuple`: verify load_prompt returns (str, str) tuple
- `test_prompt_hash_is_deterministic`: same content produces same hash
- `test_prompt_hash_is_12_chars`: hash is exactly 12 hex characters

### Step 8: Add tests for diff capture
**File**: tests/test_execute_recommendation.py
**Action**: modify
**What**: Update `TestCommitStep` class with tests:
- `test_commit_step_returns_diff_stat`: mock successful diff capture
- `test_commit_step_diff_fallback_on_error`: mock diff command failure, verify empty string returned

### Step 9: Add tests for failure cleanup
**File**: tests/test_execute_recommendation.py
**Action**: modify
**What**: Add `TestFailureCleanup` class with tests:
- `test_handle_failure_pushes_branch`: mock subprocess, verify git push called
- `test_handle_failure_creates_draft_pr`: mock subprocess, verify gh pr create --draft called with correct title/body
- `test_handle_failure_tolerates_push_error`: mock push failure, verify no exception raised

### Step 10: Update existing tests for new return types
**File**: tests/test_execute_recommendation.py
**Action**: modify
**What**: Update any tests that use `commit_step()` to handle the new `tuple[bool, str]` return type. Update any tests that use `load_prompt()` to unpack the tuple.

### Step 11: Run pytest
**Command**: `pytest tests/test_execute_recommendation.py -v`
**What**: All tests must pass before proceeding.

### Step 12: Run validate.py
**Command**: `python scripts/validate.py`
**What**: Must exit 0.

### Step 13: Report implementation summary
**What**: Summarize what was implemented and any design decisions made during implementation.
