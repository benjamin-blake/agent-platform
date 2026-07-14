# Plan

## Intent
Prevent the executor from modifying its own machinery. This closes a structural safety gap where autonomous code-generation agents edit the very prompts, scripts, and tests that control their behaviour -- a self-modification loop that risks silent behavioural regression and makes failure diagnosis unreliable.

## Plan Type
IMPLEMENTATION

## Branch
agent/infra-executor-boundary

## Phase
Infra (phase-independent governance)

## Scope
| File | Action | Purpose |
|------|--------|---------|
| docs/DECISIONS.md | Modify | Add Decision 44: Executor Self-Modification Boundary |
| logs/.recommendations-log.jsonl | Modify | Flip 53 open recs from automatable:true to automatable:false |
| scripts/validate.py | Modify | Add validate_executor_boundary() gate |
| tests/test_validate.py | Modify | Add TestValidateExecutorBoundary test class |
| .github/copilot-instructions.md | Modify | Add executor boundary rule to Known Gotchas |

## Bundled Recommendations
- **rec-420**: develop-executor: require a between-rec checkpoint before returning to Phase 3 and expand the tracked artifact list. Included because rec-420 touches develop-executor.prompt.md (inside the boundary) and is currently automatable:true -- it will be flipped to automatable:false as part of the batch update in Step 2. rec-420 itself is NOT implemented by this plan; it is only correctly classified.

## Acceptance Criteria
- [ ] Decision 44 exists in docs/DECISIONS.md with the boundary table and rationale
- [ ] All 53 identified open recs that touch executor boundary files have automatable:false
- [ ] validate_executor_boundary() exists in scripts/validate.py and is called from run_python_checks()
- [ ] validate_executor_boundary() fails if any open rec with a boundary-matching file field has automatable:true
- [ ] TestValidateExecutorBoundary passes in tests/test_validate.py
- [ ] Known Gotchas in copilot-instructions.md documents the boundary rule
- [ ] python scripts/validate.py --scope all exits 0

## Constraints
- Windows Git Bash (no PowerShell)
- Python 3.12+ style, type hints required
- validate.py is the single source of truth for validation (no separate CI checks)
- JSONL batch update must preserve line ordering and all existing fields
- The boundary patterns list must be a named constant in validate.py for reuse

## Context
- Decision 42 (Three-Tier Workflow Architecture) established /plan -> /implement -> /develop-executor separation
- Decision 44 (this plan) adds the structural enforcement: executor cannot modify its own tier
- rec-413 (--fast mode) and rec-414 (hotfix routing) are Phase B delegation mechanisms -- Decision 44 is the safety boundary that makes delegation safe
- 53 open recs currently have automatable:true but target executor boundary files
- 17 open recs already correctly have automatable:false for boundary files
- select_next_batch() in execute_recommendation.py already filters by automatable:true, so flipping these recs immediately removes them from autonomous batch selection

## Pre-Implementation Checklist
> The implementing agent must verify all items before editing any file.
- [ ] Branch confirmed not on `main`
- [ ] copilot-instructions.md read (rules, gotchas, file router)
- [ ] DECISIONS.md read (no conflicts with prior decisions)
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps

### Step 1: Add Decision 44 to docs/DECISIONS.md
**File:** docs/DECISIONS.md
**Action:** Add a new `## Decision 44: Executor Self-Modification Boundary (Decided)` section at the top of the file, below the `# Open Decisions` heading and above Decision 42.

The decision must contain:
- **Decision statement:** The executor (scripts/execute_recommendation.py and its submodules) must not modify files within its own machinery boundary. Recommendations targeting boundary files must have automatable:false and be implemented via /plan -> /implement.
- **Problem:** The executor generates code via LLM calls to implement recommendations. When the target files ARE the executor itself (or its prompts, instructions, or tests), the system is modifying the code that controls its own behaviour. This creates: (a) silent behavioural regression risk -- a bad edit to step_runner.py affects all future recs, (b) unreliable failure diagnosis -- the diagnostic tooling may itself be broken, (c) untestable changes -- executor tests run inside the executor, creating circular validation.
- **Boundary table:** The exact file pattern table:

| File pattern | Route | Reason |
|---|---|---|
| scripts/execute_recommendation.py | /plan -> /implement | The orchestrator itself |
| scripts/executor/*.py | /plan -> /implement | Executor submodules |
| config/prompts/executor/*.prompt.md | /plan -> /implement | Executor prompts |
| .github/instructions/executor-*.instructions.md | /plan -> /implement | Supervisor/executor instructions |
| .github/prompts/develop-executor.prompt.md | /plan -> /implement | Supervisor prompt |
| scripts/copilot_wrapper.py | /plan -> /implement | LLM interface layer |
| tests/test_execute_recommendation.py | /plan -> /implement | Executor test infrastructure |
| tests/test_executor_*.py | /plan -> /implement | Executor submodule tests |
| tests/test_copilot_wrapper.py | /plan -> /implement | LLM interface tests |
| Everything else | Executor (automatable: true) | Normal product code |

- **Enforcement:** (1) validate.py gate rejects open recs with boundary file + automatable:true, (2) copilot-instructions.md Known Gotchas documents the rule for all agents, (3) select_next_batch() already excludes automatable:false recs from batch selection
- **Exceptions:** None. If an executor boundary file needs changing, it goes through /plan -> /implement. The human reviews the plan and the implementation directly. --fast mode is not available for boundary files.

**Acceptance:** `grep -q "Decision 44" docs/DECISIONS.md && grep -q "Self-Modification Boundary" docs/DECISIONS.md`

### Step 2: Batch-update 53 open recs to automatable:false
**File:** logs/.recommendations-log.jsonl
**Action:** Write a temporary Python script (do not commit it -- delete after use) that reads the JSONL file, identifies all open recs where the `file` field or `acceptance` field matches any boundary pattern, and sets `automatable` to `false` for those entries. The script must:
- Preserve all existing fields and line ordering
- Only modify lines where status=="open" AND automatable==true AND file/acceptance matches a boundary pattern
- Print each modified rec ID and title for verification
- Write the entire file back atomically (read all, modify in memory, write all)
- Be deleted after successful execution (temporary script, not committed)

The 53 recs to flip were identified by scanning with these boundary patterns:
`execute_recommendation.py`, `scripts/executor/`, `config/prompts/executor/`, `executor-supervisor`, `executor-implement`, `executor-critique`, `executor-planning`, `executor-review`, `develop-executor.prompt.md`, `copilot_wrapper.py`, `tests/test_execute`, `tests/test_executor_`, `tests/test_copilot_wrapper`

After running the script, verify with an inline assertion that zero boundary violations remain.

Do NOT commit logs/.recommendations-log.jsonl with -a; use explicit git add for only the files changed in this step.

**Acceptance:** `python -c "import json; recs=[json.loads(l) for l in open('logs/.recommendations-log.jsonl',encoding='utf-8') if l.strip()]; pats=['execute_recommendation.py','scripts/executor/','config/prompts/executor/','executor-supervisor','executor-implement','executor-critique','executor-planning','executor-review','develop-executor.prompt.md','copilot_wrapper.py','tests/test_execute','tests/test_executor_','tests/test_copilot_wrapper']; bad=[r['id'] for r in recs if r.get('status')=='open' and r.get('automatable')==True and any(p in r.get('file','') or p in r.get('acceptance','') for p in pats)]; print(f'violations: {len(bad)}'); assert not bad"`

### Step 3: Add validate_executor_boundary() to scripts/validate.py
**File:** scripts/validate.py
**Action:** Add a new function `validate_executor_boundary(failed: list[str]) -> None` that:

1. Defines a module-level constant `_EXECUTOR_BOUNDARY_PATTERNS` as a tuple of strings:
   ```python
   _EXECUTOR_BOUNDARY_PATTERNS = (
       "execute_recommendation.py",
       "scripts/executor/",
       "config/prompts/executor/",
       "executor-supervisor",
       "executor-implement",
       "executor-critique",
       "executor-planning",
       "executor-review",
       "develop-executor.prompt.md",
       "copilot_wrapper.py",
       "tests/test_execute",
       "tests/test_executor_",
       "tests/test_copilot_wrapper",
   )
   ```

2. Reads `logs/.recommendations-log.jsonl` line by line (same pattern as validate_recommendations_schema)
3. For each entry where status=="open" and automatable==True: checks if the `file` field or `acceptance` field contains any pattern from `_EXECUTOR_BOUNDARY_PATTERNS`
4. Collects violations as a list of `(rec_id, file_field, matched_pattern)` tuples
5. If violations exist: prints each violation and appends "Executor boundary validation" to the `failed` list
6. If no violations: prints "Executor boundary validation passed."

Then add the call `validate_executor_boundary(failed)` inside `run_python_checks()`, after `validate_recommendations_schema(failed)`.

**Acceptance:** `grep -q '_EXECUTOR_BOUNDARY_PATTERNS' scripts/validate.py && grep -q 'validate_executor_boundary(failed)' scripts/validate.py && python -m pytest tests/test_validate.py::TestValidateExecutorBoundary -x -q`

### Step 4: Add TestValidateExecutorBoundary to tests/test_validate.py
**File:** tests/test_validate.py
**Action:** Add a new test class `TestValidateExecutorBoundary` with the following test cases:

1. `test_boundary_violation_detected`: Create a tmp JSONL file with one open rec where file="scripts/executor/plan.py" and automatable=true. Patch `ROOT / "logs" / ".recommendations-log.jsonl"` to point to the tmp file. Call `validate_executor_boundary(failed=[])`. Assert "Executor boundary validation" is in the failed list.

2. `test_boundary_compliant_passes`: Create a tmp JSONL file with one open rec where file="scripts/executor/plan.py" and automatable=false. Call validate_executor_boundary. Assert failed list is empty.

3. `test_non_boundary_file_ignored`: Create a tmp JSONL file with one open rec where file="scripts/session_postflight.py" and automatable=true. Call validate_executor_boundary. Assert failed list is empty (non-boundary files can be automatable).

4. `test_closed_rec_ignored`: Create a tmp JSONL file with one rec where file="scripts/executor/plan.py", automatable=true, status="closed". Call validate_executor_boundary. Assert failed list is empty (only open recs are checked).

Each test must create a minimal valid JSONL line with required fields (id, date, title, source, effort, priority, status, automatable, risk, file, context, acceptance). Use `tmp_path` and `monkeypatch` to isolate from the real JSONL file.

**Acceptance:** `python -m pytest tests/test_validate.py::TestValidateExecutorBoundary -x -q`

### Step 5: Add executor boundary rule to copilot-instructions.md Known Gotchas
**File:** .github/copilot-instructions.md
**Action:** Add a new entry to the Known Gotchas section:

```
- **Executor self-modification boundary (Critical):** Recs targeting executor machinery files must have `automatable: false`. The executor must not modify its own code, prompts, instructions, or tests. Boundary files: `scripts/execute_recommendation.py`, `scripts/executor/*.py`, `config/prompts/executor/*.prompt.md`, `.github/instructions/executor-*.instructions.md`, `.github/prompts/develop-executor.prompt.md`, `scripts/copilot_wrapper.py`, `tests/test_execute*`, `tests/test_executor_*`, `tests/test_copilot_wrapper.py`. These recs go through `/plan` -> `/implement` instead. See Decision 44. Enforced by `validate_executor_boundary()` in `validate.py`.
```

Place it after the first gotcha (Git branching workflow) and before the Venv gotcha, since it is Critical priority.

**Acceptance:** `grep -q "self-modification boundary" .github/copilot-instructions.md && grep -q "Decision 44" .github/copilot-instructions.md`

### Step 6: Run full validation
**Action:** Run `python -m scripts.validate --scope all` and verify exit code 0. All checks must pass including the new executor boundary validation.

**Acceptance:** `python -m scripts.validate --scope all`

### Step 7: Report
Report what was implemented and any design decisions made during implementation.
