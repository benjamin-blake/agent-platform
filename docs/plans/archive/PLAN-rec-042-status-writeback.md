# Plan

## Intent
Enable the autonomous recommendation executor to close the feedback loop by writing execution results back to the source of truth, preventing re-execution of completed/failed recommendations and providing an audit trail for batch processing.

## Plan Type
IMPLEMENTATION

## Branch
agent/rec-042-status-writeback

## Phase
Phase E: Executor Completeness (from PLAN-infra-cli-migration-plan.md)

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `scripts/execute_recommendation.py` | Modify | Add `update_recommendation_status()` function; modify `is_eligible()` to skip closed/failed recs; call writeback on success/failure paths |
| `tests/test_execute_recommendation.py` | Modify | Add tests for status writeback (success, failure, rec-not-found, JSONL integrity) |
| `docs/INTENT-recommendation-executor.md` | Modify | Mark rec-042 (status writeback) as implemented in the Known Critical Gaps section |

## Acceptance Criteria
- [ ] After successful merge, rec entry updated with `status: "closed"`, `execution_result: "success"`, `execution_date`, `execution_branch`, `execution_pr_url`, `execution_cost_usd`, `execution_steps`
- [ ] After failure, rec entry updated with `status: "failed"`, `execution_result: "failure"`, `failure_step`, `failure_reason`, `execution_cost_usd`
- [ ] Original JSONL fields preserved (id, title, etc.); new fields merged
- [ ] `is_eligible()` returns False for recs with `status: "closed"` or `status: "failed"`
- [ ] Test covers: success writeback, failure writeback, rec-not-found (graceful), JSONL integrity after update

## Constraints
- Python 3.12+, type hints required
- JSONL is the source of truth for recommendations — no external database
- Single-writer scenario (no file locking required for MVP)
- Windows compatibility: use `encoding='utf-8'` for all file operations

## Context
- **INTENT document**: `docs/INTENT-recommendation-executor.md` defines the executor architecture and the "nervous system" separation (deterministic script vs non-deterministic LLM)
- **Briefing**: `docs/plans/briefings/BRIEFING-rec-042.md` specifies the exact JSON fields to write
- **Dependency**: rec-009 (executor exists) is already implemented
- **Known gotcha**: JSONL schema line starts with `#` — skip it when parsing

## Pre-Implementation Checklist
> The implementing agent must verify all items before editing any file.
- [ ] Branch confirmed not on `main`
- [ ] copilot_instructions.md read (rules, gotchas, file router)
- [ ] DECISIONS.md read (no conflicts with prior decisions)
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps

### Step 1: Add `update_recommendation_status()` function
**File**: `scripts/execute_recommendation.py`
**Action**: Add new function after `load_recommendation()`

Add function with signature:
```python
def update_recommendation_status(rec_id: str, updates: dict) -> bool:
```

Implementation:
1. Read all lines from `RECS_JSONL`
2. Skip schema line (starts with `#` or `{"_schema`)
3. Find line with matching `id`
4. If not found, log warning and return `False`
5. Parse JSON, merge `updates` dict (updates take precedence)
6. Write all lines back to file atomically (write to temp file, then replace)
7. Return `True` on success

### Step 2: Modify `is_eligible()` to skip closed/failed recs
**File**: `scripts/execute_recommendation.py`
**Action**: Modify existing function

Change from:
```python
def is_eligible(rec: dict) -> bool:
    return rec.get("risk") == "low" and rec.get("automatable") is True
```

To also check:
```python
def is_eligible(rec: dict) -> bool:
    status = rec.get("status", "open")
    if status in ("closed", "failed"):
        return False
    return rec.get("risk") == "low" and rec.get("automatable") is True
```

### Step 3: Add cost accumulation tracking
**File**: `scripts/execute_recommendation.py`
**Action**: Modify `_execute_recommendation_inner()`

Add variables at the start of `_execute_recommendation_inner()`:
```python
total_cost_usd: float = 0.0
steps_completed: int = 0
failure_step: Optional[int] = None
failure_reason: Optional[str] = None
```

Track cost after each CLI call (plan generation, critique, refine, implement steps).

### Step 4: Capture PR URL from `finalize()`
**File**: `scripts/execute_recommendation.py`
**Action**: Modify `finalize()` to return PR URL

Change signature and implementation:
```python
def finalize(rec_id: str) -> Optional[str]:
    """Push and create PR. Returns PR URL on success, None on failure."""
```

After `gh pr create --fill`, run `gh pr view --json url -q .url` to get the PR URL and return it.

### Step 5: Add success writeback call
**File**: `scripts/execute_recommendation.py`
**Action**: Modify end of `_execute_recommendation_inner()` success path

After `finalize()` succeeds, before returning `True`:
```python
update_recommendation_status(rec_id, {
    "status": "closed",
    "execution_result": "success",
    "execution_date": datetime.now(timezone.utc).isoformat(),
    "execution_branch": f"agent/{rec_id}",
    "execution_pr_url": pr_url,
    "execution_cost_usd": round(total_cost_usd, 4),
    "execution_steps": steps_completed,
})
```

### Step 6: Add failure writeback calls
**File**: `scripts/execute_recommendation.py`
**Action**: Modify failure return points in `_execute_recommendation_inner()`

At each `return False` point that represents execution failure (after step failure, after finalize failure), call:
```python
update_recommendation_status(rec_id, {
    "status": "failed",
    "execution_result": "failure",
    "execution_date": datetime.now(timezone.utc).isoformat(),
    "execution_branch": f"agent/{rec_id}",
    "failure_step": failure_step,
    "failure_reason": failure_reason[:500] if failure_reason else None,
    "execution_cost_usd": round(total_cost_usd, 4),
    "execution_steps_attempted": steps_completed,
    "execution_steps_total": len(plan.steps) if 'plan' in dir() else None,
})
```

Note: Early failures (rec not found, not eligible, branch setup failure) should NOT write back — the rec is unchanged.

### Step 7: Add test for success writeback
**File**: `tests/test_execute_recommendation.py`
**Action**: Add new test class `TestUpdateRecommendationStatus`

Add test:
```python
def test_update_status_success(self, tmp_path, monkeypatch):
    """Test updating rec status to closed on success."""
```

Setup: Create JSONL with one rec, call `update_recommendation_status()` with success fields, verify rec now has `status: "closed"` and all new fields merged.

### Step 8: Add test for failure writeback
**File**: `tests/test_execute_recommendation.py`
**Action**: Add test to `TestUpdateRecommendationStatus`

Add test:
```python
def test_update_status_failure(self, tmp_path, monkeypatch):
    """Test updating rec status to failed on failure."""
```

Setup: Create JSONL with one rec, call `update_recommendation_status()` with failure fields, verify rec now has `status: "failed"` and failure details.

### Step 9: Add test for rec-not-found graceful handling
**File**: `tests/test_execute_recommendation.py`
**Action**: Add test to `TestUpdateRecommendationStatus`

Add test:
```python
def test_update_status_rec_not_found(self, tmp_path, monkeypatch):
    """Test graceful handling when rec ID not in JSONL."""
```

Should return `False` without raising, JSONL unchanged.

### Step 10: Add test for is_eligible with closed/failed status
**File**: `tests/test_execute_recommendation.py`
**Action**: Add tests to `TestIsEligible`

Add:
```python
def test_is_eligible_false_status_closed(self):
    rec = {"risk": "low", "automatable": True, "status": "closed"}
    assert is_eligible(rec) is False

def test_is_eligible_false_status_failed(self):
    rec = {"risk": "low", "automatable": True, "status": "failed"}
    assert is_eligible(rec) is False
```

### Step 11: Add test for JSONL integrity after update
**File**: `tests/test_execute_recommendation.py`
**Action**: Add test to `TestUpdateRecommendationStatus`

Add test:
```python
def test_update_preserves_other_recs(self, tmp_path, monkeypatch):
    """Test that updating one rec doesn't corrupt others."""
```

Setup: Create JSONL with 3 recs, update middle one, verify all 3 still readable and only target one changed.

### Step 12: Update INTENT document
**File**: `docs/INTENT-recommendation-executor.md`
**Action**: Modify Known Critical Gaps section

Mark rec-042 (status writeback) as implemented. Change the gap entry from a gap to a completed item or remove it from the gaps list and add a note that it's now implemented.

### Step 13: Run pytest
Run `pytest tests/test_execute_recommendation.py -v` — all tests must pass.

### Step 14: Run validate.py
Run `python scripts/validate.py` — must exit 0.

### Step 15: Report implementation summary
Report what was implemented and any design decisions made during implementation.
