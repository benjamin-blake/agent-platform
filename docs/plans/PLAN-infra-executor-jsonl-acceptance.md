# Plan

## Intent
Eliminate executor machinery bugs that waste premium requests on false-positive preflight failures and silently discard corrected recommendation metadata, directly improving the self-improving feedback loop's reliability and cost efficiency.

## Plan Type
IMPLEMENTATION

## Branch
agent/infra-executor-jsonl-acceptance

## Phase
Phase 1: Core Infrastructure (maintenance)

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `scripts/executor/jsonl_store.py` | Modify | rec-462: Change `load_recommendation()` to return last matching entry (last-wins JSONL semantics) |
| `tests/test_executor_jsonl_store.py` | Modify | rec-462: Add regression test for last-wins behaviour |
| `scripts/execute_recommendation.py` | Modify | rec-461 + rec-401: Make `validate_acceptance_feasibility()` action-aware; skip file-existence checks for create-action recs and non-existent `python -m` module targets |
| `tests/test_execute_recommendation.py` | Modify | rec-461 + rec-401: Add regression tests for action-aware feasibility |
| `config/prompts/executor/planning.prompt.md` | Modify | rec-463: Add CURRENT_IMPL vs TARGET_CANONICAL tagging rule |

## Bundled Recommendations
- **rec-461** (S/High): `validate_acceptance_feasibility` action-aware redesign
- **rec-462** (XS/High): `load_recommendation` last-wins JSONL semantics
- **rec-463** (XS/High): `planning.prompt.md` CURRENT_IMPL/TARGET_CANONICAL rule
- **rec-401** (XS/High): Test that `validate_acceptance_feasibility` returns FEASIBLE for non-existent `python -m` module targets

## Acceptance Criteria
- [ ] `load_recommendation("rec-X")` returns the last matching entry when multiple entries exist for the same ID
- [ ] `validate_acceptance_feasibility("grep -q 'pattern' nonexistent.md", action="create")` returns FEASIBLE (Pattern 1 grep bypass only; other patterns still validate)
- [ ] `validate_acceptance_feasibility("python -m scripts.new_module")` returns FEASIBLE even when module does not exist (already works; test locks existing behaviour per rec-401)
- [ ] `planning.prompt.md` contains CURRENT_IMPL vs TARGET_CANONICAL guidance
- [ ] All existing tests pass (`pytest tests/test_executor_jsonl_store.py tests/test_execute_recommendation.py -x -q`)

## Constraints
- All target files are executor boundary files (`automatable: false`) -- this plan goes through `/plan` -> `/implement`, not the executor
- `scripts/execute_recommendation.py` is the most complex file in the repo; changes must be minimal and surgical
- `validate_acceptance_feasibility()` signature change must be backward-compatible (new parameter must have a default)
- Windows Git Bash compatibility required for all shell commands
- No Docker available on company VM

## Context
- **Decision 44** (executor self-modification boundary): All five files are boundary files. The executor must not modify its own code, prompts, or tests.
- **Session 25 evidence**: rec-454 failed 3 times due to rec-461 (preflight false positive on create-action) and rec-462 (load_recommendation returning stale first entry). rec-463 arose from code review finding wrong canonical values in generated documentation.
- **Known Gotcha**: `load_recommendation()` at `jsonl_store.py:103` returns the first match; `load_all_recommendations()` at `jsonl_store.py:139` returns the last (overwrites `result[rec_id]`). This inconsistency is the root cause of rec-462.
- **Known Gotcha**: `validate_acceptance_feasibility()` Pattern 1 (grep file paths) has no concept of step action type. Patterns 2 (pytest) and 3 (python -m) already have "file may be created by this rec" comments but no formal action parameter.

## Pre-Implementation Checklist
> The implementing agent must verify all items before editing any file.
- [ ] Branch confirmed not on `main`
- [ ] copilot-instructions.md read (rules, gotchas, file router)
- [ ] DECISIONS.md read (no conflicts with prior decisions)
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps
> **Execute these in sequence. Do not substitute the Scope table as a work list.**

1. **Modify `scripts/executor/jsonl_store.py`: change `load_recommendation()` to last-wins semantics**
   - In the local file path: instead of returning on first match, iterate all lines and keep updating a `result` variable. Return the last match found.
   - In the S3 path: same change -- iterate all entries, keep last match.
   - Update the docstring from "Returns the first matching entry" to "Returns the last matching entry" to document last-wins JSONL append semantics.
   - Do NOT change `load_all_recommendations()` -- it already uses last-wins (dict overwrite).

2. **Modify `tests/test_executor_jsonl_store.py`: add last-wins regression test**
   - In `TestLoadRecommendation`, add a test method that writes two JSONL entries with the same `id` but different `acceptance` values. Assert that `load_recommendation()` returns the entry with the second (last) acceptance value.
   - Also add an S3-backend variant in `TestS3Backend` that mocks `read_jsonl` returning two entries with the same ID and asserts last-wins.

3. **Modify `scripts/execute_recommendation.py`: make `validate_acceptance_feasibility()` action-aware**
   - Add an optional `action: str = ""` parameter to the function signature (backward-compatible default).
   - Scope the action-aware bypass to **Pattern 1 (grep file-path checks) only**: inside the grep match block, before the `full_path.exists()` check, add: if `action == "create"`, skip the file-existence check and continue to the next pattern (do NOT return early for the whole function -- other patterns still run their own checks).
   - **Call-site (~line 1444):** The existing call site always passes `action=""` (no change needed). The recommendation JSONL schema has no `action` field, so the current preflight call site cannot infer action type reliably. The `action` parameter exists for future callers (e.g., per-step feasibility checks during plan execution) where the step action is known from the parsed plan. This is an API extension, not a call-site refactor.
   - **Pattern 3 (python -m) -- no code change needed (rec-401 is test-only):** The existing code at lines 225-231 already falls through to FEASIBLE for non-existent `python -m` modules (the `pass` inside `if not exists` results in no INFEASIBLE return). Step 4 adds a test to lock this existing behaviour. Do NOT modify the Pattern 3 code path.

4. **Modify `tests/test_execute_recommendation.py`: add action-aware feasibility tests**
   - Add a test class `TestValidateAcceptanceFeasibilityActionAware` (or add methods to the existing test class covering `validate_acceptance_feasibility`).
   - Test 1: `validate_acceptance_feasibility("grep -q 'pattern' nonexistent.md", action="create")` returns `FEASIBLE`.
   - Test 2: `validate_acceptance_feasibility("grep -q 'pattern' nonexistent.md")` (no action) returns `INFEASIBLE` (existing behaviour preserved).
   - Test 3 (rec-401): `validate_acceptance_feasibility("python -m scripts.new_nonexistent_module")` returns `FEASIBLE` (module-creation recs).
   - Test 4: `validate_acceptance_feasibility("test -f nonexistent.md", action="create")` returns `FEASIBLE`.

5. **Modify `config/prompts/executor/planning.prompt.md`: add CURRENT_IMPL vs TARGET_CANONICAL rule**
   - Add a new section after the "Recommendation to Implement" template section (before "Output Format").
   - Title: `## CURRENT_IMPL vs TARGET_CANONICAL Values -- CRITICAL`
   - Content: When the recommendation context specifies values that differ from the current codebase implementation (e.g., canonical status values, S3 key paths, API contracts), the plan MUST:
     - Tag each value as `CURRENT_IMPL` (what the code does today) or `TARGET_CANONICAL` (what the rec intends to establish)
     - The implementation step description must explicitly state which canonical values to use
     - Cross-reference S3 key paths, status values, and field names against existing prompt files and source code to detect conflicts
   - This prevents documentation recs from encoding broken current behaviour as canonical.

6. Run `pytest tests/test_executor_jsonl_store.py tests/test_execute_recommendation.py -x -q` -- all tests must pass
7. Run `python scripts/validate.py` -- must exit 0
8. Report what was implemented and any design decisions made during implementation
