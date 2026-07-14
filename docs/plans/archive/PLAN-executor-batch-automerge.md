# Plan

## Intent
Close the autonomous execution loop by enabling the recommendation executor to complete the full workflow (CI wait, merge, cleanup), process multiple eligible recommendations in dependency order, and resume from interruptions - advancing the self-improving trading system toward fully unattended operation.

## Plan Type
IMPLEMENTATION

## Branch
agent/executor-batch-automerge

## Phase
Phase E: Executor Completeness

## Recommendations Implemented
- rec-033: Batch orchestrator for sequential loop over eligible recommendations
- rec-036: Execution checkpointing integration for resumability
- rec-041: Auto-merge with CI wait in the executor

## Scope
| File | Action | Purpose |
|------|--------|---------|
| scripts/execute_recommendation.py | Modify | Add CI wait, auto-merge, batch orchestrator, checkpointing, and supporting functions |
| scripts/execution_state.py | Use | Import save_checkpoint, load_checkpoint, clear_checkpoint for resumability |
| tests/test_execute_recommendation.py | Modify | Add comprehensive tests for new functionality |

## Acceptance Criteria
### rec-041: Auto-merge
- [ ] finalize() polls CI status after PR creation (max 10 min, 30s interval)
- [ ] On CI pass, PR is squash-merged and branch deleted (remote + local)
- [ ] On CI timeout or failure, rec marked as failed, PR left open
- [ ] Executor returns to main branch with latest changes after successful merge
- [ ] --no-merge flag stops at PR creation (for testing/safety)

### rec-033: Batch orchestrator
- [ ] --batch flag processes all eligible recs in dependency order
- [ ] After each success in batch mode, eligibility is re-evaluated (newly unblocked recs become eligible)
- [ ] Failed recs are skipped in batch mode; batch continues to next eligible
- [ ] --max-recs N limits batch to N recommendations (default 10)
- [ ] Batch summary printed: attempted / succeeded / failed / skipped

### rec-036: Checkpointing (step-level)
- [ ] Checkpoint saved after each successful step with rec_id, step_n, total_steps, branch
- [ ] On startup with existing checkpoint matching current rec, resumes from step N+1
- [ ] On startup with checkpoint for different rec, warns and requires --restart
- [ ] --restart flag clears checkpoint before execution
- [ ] Successful completion clears checkpoint
- [ ] Failure leaves checkpoint in place for resume

### Batch resumption (uses existing JSONL status from rec-042)
- [ ] If batch is interrupted mid-execution, re-running with --batch skips completed recs (status=closed in JSONL) and resumes from next eligible
- [ ] If a rec fails mid-step and batch continues, the failed rec's checkpoint remains for manual retry later

### General
- [ ] All existing tests continue to pass
- [ ] New tests cover all new functionality

## Constraints
- Python 3.12+, type hints required
- Use subprocess for git/gh commands with encoding=utf-8 on Windows
- Use graphlib.TopologicalSorter (stdlib) for dependency ordering
- No Docker - script runs locally
- Max 10 minute CI wait before timeout (configurable via env var)
- Batch resumption relies on JSONL status (rec-042) - no separate batch checkpoint needed
- Use existing execution_state.py for checkpointing (Decision #28)

## Context
- rec-034 (dependency resolution) already implemented: is_eligible() checks dependencies array
- rec-042 (status writeback) already implemented: update_recommendation_status() exists
- scripts/execution_state.py already exists with save_checkpoint(), load_checkpoint(), clear_checkpoint()
- finalize() currently creates PR but stops there - manual merge required
- gh pr checks returns JSON with state field (pending/success/failure)
- gh pr merge --squash --delete-branch handles remote branch deletion
- **Two-tier resumption model:**
  - Step-level: execution_state.py checkpoint enables resuming mid-rec (step N+1)
  - Batch-level: JSONL status (rec-042) enables skipping completed recs (status=closed filtered out by is_eligible)

## Pre-Implementation Checklist
- [ ] Branch confirmed not on main
- [ ] copilot_instructions.md read (rules, gotchas, file router)
- [ ] DECISIONS.md read (no conflicts with prior decisions)
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps

### Step 1: Add CI wait function
Add wait_for_ci(branch, timeout=600, interval=30) to scripts/execute_recommendation.py.
Poll gh pr checks {branch} --json state. Return (True, success) on CI pass, (False, timeout) after timeout, (False, failure) on CI failure. Log each poll with time remaining.

### Step 2: Add merge function
Add merge_pr(branch) to scripts/execute_recommendation.py.
Run gh pr merge {branch} --squash --delete-branch. Return (True, None) on success, (False, error_msg) on failure. Handle CalledProcessError gracefully.

### Step 3: Add robust cleanup function
Add cleanup_after_merge(branch) to scripts/execute_recommendation.py.
- Run git checkout main (if fails, attempt git checkout main && git reset --hard origin/main)
- Run git pull origin main
- Run git branch -d {branch} (handle already-deleted gracefully)
- Return True on success, False on unrecoverable error
- Log detailed errors for debugging

### Step 4: Refactor finalize() for auto-merge
Add no_merge parameter to finalize(). If no_merge=False, wait for CI, merge, cleanup. Return PR URL or None.

### Step 5: Add --no-merge CLI flag
Update main() argparse to add --no-merge flag.

### Step 6: Update execute_recommendation() signature
Add no_merge parameter to execute_recommendation() and _execute_recommendation_inner().

### Step 7: Add checkpointing to implementation loop
Import from scripts.execution_state: save_checkpoint, load_checkpoint, clear_checkpoint.
In _execute_recommendation_inner():
- After each successful step + commit, call save_checkpoint() with rec_id, step_n, total_steps, branch
- On successful completion (all steps + finalize), call clear_checkpoint()
- On failure, leave checkpoint in place

### Step 8: Add checkpoint resume logic
In execute_recommendation() preflight:
- Call load_checkpoint() to check for existing checkpoint
- If checkpoint exists and matches rec_id: skip to step N+1, log resume info
- If checkpoint exists for different rec_id: warn and return False (require --restart)
- If no checkpoint: proceed normally

### Step 9: Add --restart CLI flag
Update main() argparse to add --restart flag.
If --restart is set, call clear_checkpoint() before execution.

### Step 10: Add get_eligible_recs function
Add get_eligible_recs() that returns list of eligible rec dicts using load_all_recommendations() and is_eligible().

### Step 11: Add topological sort function
Add topological_sort_recs() using graphlib.TopologicalSorter for dependency ordering. Handle cycles gracefully (log error, return empty list).

### Step 12: Add execute_batch function
Add execute_batch() to process eligible recs in dependency order:
- Get eligible recs, topologically sort, limit to max_recs
- For each rec: execute, track counters (attempted/succeeded/failed)
- On success: re-call get_eligible_recs() to pick up newly unblocked recs
- On failure: continue to next (do not abort batch)
- Return summary dict and print batch summary

### Step 13: Add --batch and --max-recs CLI flags
Update main() argparse for batch mode. Make rec_id optional when --batch is used.

### Step 14: Add tests for wait_for_ci
TestWaitForCI: success, failure, timeout, pending-then-success cases.

### Step 15: Add tests for merge_pr
TestMergePR: success, conflict, subprocess error cases.

### Step 16: Add tests for cleanup_after_merge
TestCleanupAfterMerge: success, branch-already-deleted (graceful), checkout failure cases.

### Step 17: Add tests for finalize auto-merge
TestFinalizeAutoMerge: no_merge flag, full cycle, CI timeout, merge conflict cases.

### Step 18: Add tests for checkpointing
TestCheckpointing: save after step, resume from checkpoint, different rec warning, --restart clears, completion clears.

### Step 19: Add tests for batch orchestration
TestExecuteBatch: empty queue, single rec, dependency chain, failure continues, max_recs limit, re-evaluation after success, batch resumption (skips closed recs in JSONL).

### Step 20: Add tests for topological sort
TestTopologicalSort: no deps, chain ordering, cycle detection.

### Step 21: Run pytest
Run pytest tests/test_execute_recommendation.py -v - all tests must pass.

### Step 22: Run validate.py
Run python scripts/validate.py - must exit 0.

### Step 23: Report implementation summary
Report what was implemented: functions added, tests added, any design decisions made during implementation.
