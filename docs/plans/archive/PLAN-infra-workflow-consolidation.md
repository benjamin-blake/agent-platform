# Plan

## Intent

Reduce workflow complexity and context consumption by consolidating duplicate instruction files, triaging gotchas (removing those fixable via tooling), simplifying the implement.prompt.md from 21 steps to 10, and adding automation to make session close resilient to context compaction. This directly supports the North Star by improving the feedback loop efficiency — less overhead means more productive implementation time.

## Plan Type

IMPLEMENTATION

## Branch

agent/infra-workflow-consolidation

## Phase

Infrastructure (post-Phase 1)

## Scope

| File | Action | Purpose |
|------|--------|---------|
| `.github/copilot_instructions.md` | Delete | Remove duplicate instruction file |
| `.github/copilot-instructions.md` | Modify | Consolidate content from underscore file, condense gotchas from ~33 to ~12 |
| `.github/prompts/implement.prompt.md` | Modify | Simplify from 21 steps to 10, remove redundant steps |
| `.github/prompts/plan.prompt.md` | Modify | Add Lambda post-deploy testing requirement to Step 5b |
| `scripts/session_postflight.py` | Modify | Add `--auto` flag for single-command session close |
| `scripts/execution_state.py` | Modify | Track todo list state in checkpoint, not just step number |
| `scripts/validate.py` | Modify | Add lints: subprocess encoding, sys.executable, Terraform try() |
| `tests/test_session_postflight.py` | Modify | Add tests for `--auto` flag |
| `tests/test_execution_state.py` | Modify | Add tests for todo state persistence |
| `tests/test_validate.py` | Modify | Add tests for new lint checks |
| `docs/DECISIONS.md` | Modify | Add Decision 38: Workflow consolidation rationale |
| `docs/CHANGELOG.md` | Modify | Document changes |

## Acceptance Criteria

- [ ] `copilot_instructions.md` (underscore) deleted
- [ ] `copilot-instructions.md` (hyphen) has ~12 gotchas (down from ~33)
- [ ] `implement.prompt.md` has 10 steps (down from 21)
- [ ] `session_postflight.py --auto` runs full close sequence in one command
- [ ] `execution_state.py` checkpoint includes todo list state
- [ ] `validate.py` catches: subprocess without encoding, bare `['python']`, `filemd5()` without `try()`
- [ ] All tests pass (`pytest tests/`)
- [ ] Validation passes (`python scripts/validate.py`)

## Constraints

- Do not break existing `session_postflight.py` flags (`--validate`, `--close`, `--commit`, `--push`)
- Maintain backward compatibility with existing checkpoints (migration path for old format)
- Keep `implement.prompt.md` self-contained — no external includes for the 10 steps

## Context

- **Root cause:** Lambda testing gaps in `agent/infra-lambda-scheduled-agents` revealed that instruction files were duplicated, gotchas were bloated, and implement.prompt.md was too long for context compaction scenarios
- **Duplicate files:** VS Code loads `.github/copilot-instructions.md` (hyphen), but `.github/copilot_instructions.md` (underscore) exists with different content
- **Gotcha triage:** Many gotchas are now enforced via tooling or handled by preflight — keeping them in instructions is redundant
- **Context loss:** When conversations compact mid-implementation, the 21-step implement.prompt.md causes model confusion and "prodding" requirement

## Pre-Implementation Checklist

> The implementing agent must verify all items before editing any file.
- [ ] Branch confirmed not on `main`
- [ ] copilot_instructions.md read (rules, gotchas, file router)
- [ ] DECISIONS.md read (no conflicts with prior decisions)
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps

### Phase 1: Delete Underscore File and Consolidate Instructions

1. **Audit underscore file for unique content**
   - Read both instruction files
   - Identify any content in underscore file NOT in hyphen file
   - List items to migrate before deletion

2. **Migrate unique content to hyphen file**
   - Add missing entries from underscore file to hyphen file (if any)
   - Remove "Invocation Model" section (CLI-specific, executor prompts handle this)
   - Remove "Before Modifying Code" checklist (move enforcement to plan.prompt.md Step 0)

3. **Delete `copilot_instructions.md` (underscore)**
   - Remove the file
   - Grep for references and update them to point to hyphen file

### Phase 2: Gotcha Triage and Condensation

4. **Remove gotchas that are now tooling-enforced**
   Remove these entries (already handled by preflight/validation):
   - Pre-commit hook retries (expected behavior)
   - Git push on new branches (setup.py applies autoSetupRemote)
   - Validation sync (already enforced)
   - `gh` CLI required (checked in preflight)
   - Duplicate copilot instruction files (we're deleting one)

5. **Condense related gotchas into grouped entries**
   Create these consolidated entries:
   - "Venv and Version Manager" — merge virtual environment switching + pyenv shadowing
   - "Import Safety Patterns" — merge CI-safe error handling + optional dependencies + config file availability
   - "Athena/Iceberg Limitations" — merge ALTER TABLE + VACUUM + TBLPROPERTIES entries
   - "Windows Subprocess" — merge encoding + sys.executable + pip invocation + fork explosion
   - "Test Isolation Patterns" — merge recursion prevention + pathlib mocking + missing_ok + import scope

6. **Remove gotchas that should move elsewhere**
   - Move "Terraform workflow integration" to implement.prompt.md Step 5 (where it's enforced)
   - Move "Acceptance command format" to executor prompt (where it's relevant)
   - Reduce "Company SCP blocks OIDC" to "See Decision 37"

### Phase 3: Simplify implement.prompt.md

7. **Remove redundant steps**
   - Remove Step 2 (Read Rules) — already in VS Code context
   - Remove Step 8 (End-of-Session Friction) — duplicate of Step 20
   - Remove Step 14 (Invoke Retrospective) — friction capture is sufficient
   - Merge Step 7 into Step 11 — both run validation

8. **Consolidate session close steps**
   Merge Steps 11-16 into single "Session Close" step that calls `session_postflight.py --auto`:
   - Old: Step 11 (validate) + Step 12 (close) + Step 13 (metrics) + Step 15 (commit) + Step 16 (push)
   - New: Single step calling `session_postflight.py --auto "<commit-message>"`

9. **Renumber to 10 steps**
   Final structure:
   1. Load checkpoint or find plan
   2. Branch verification
   3. Build todo from Ordered Execution Steps
   4. Execute steps with checkpoint + step-validator
   5. Terraform gate (if applicable)
   6. Code review and findings gate
   7. Session close (`--auto`)
   8. CI triage (if needed)
   9. Friction capture + cleanup
   10. Return to main

### Phase 4: Add session_postflight.py --auto

10. **Implement `--auto` flag**
    Add new flag that executes: `--validate` → `--close` → `--metrics` → `--commit` → `--push`
    - Accept commit message as argument: `--auto "feat: ..."`
    - Return combined status (merged, ci_failed, conflict)
    - Handle each sub-step failure gracefully with clear error

11. **Add tests for `--auto`**
    - Test happy path (all steps succeed)
    - Test validation failure (stops before close)
    - Test CI failure (returns ci_failed status)
    - Test conflict (returns conflict status)

### Phase 5: Enhance execution_state.py

12. **Add todo list to checkpoint schema**
    Extend checkpoint JSON:
    ```json
    {
      "branch": "...",
      "plan_file": "...",
      "current_step": N,
      "total_steps": M,
      "todo_state": [
        {"id": 1, "title": "...", "status": "completed"},
        {"id": 2, "title": "...", "status": "in-progress"},
        ...
      ],
      "last_updated": "..."
    }
    ```

13. **Add migration for old checkpoint format**
    If checkpoint exists without `todo_state`, initialize it from plan file on load

14. **Add tests for todo state persistence**
    - Test save/load with todo state
    - Test migration from old format
    - Test partial completion recovery

### Phase 6: Add Validation Lints

15. **Add subprocess encoding lint**
    In `validate.py`, add check:
    - Pattern: `subprocess.run(` with `text=True` but without `encoding=`
    - Files: `scripts/**/*.py`
    - Error: "subprocess.run with text=True must specify encoding='utf-8'"

16. **Add sys.executable lint**
    - Pattern: `subprocess.run(['python'` or `subprocess.Popen(['python'`
    - Files: `scripts/**/*.py`
    - Error: "Use sys.executable instead of 'python' in subprocess calls"

17. **Add Terraform try() lint**
    - Pattern: `filemd5(` or `file(` without wrapping `try(`
    - Files: `terraform/**/*.tf`
    - Error: "Wrap filemd5() and file() with try() for CI compatibility"

18. **Add tests for new lints**
    - Test each lint catches bad pattern
    - Test each lint passes good pattern
    - Test lint integration in validate.py

### Phase 7: Update plan.prompt.md for Lambda Testing

19. **Add Lambda post-deploy requirement to Step 5b**
    In "Infrastructure Dependencies" section, add:
    - For Lambda resources: require `force_{param}` event field in handler design
    - Add "Post-deploy verification" column to Infrastructure Dependencies table
    - Acceptance Criteria must include invocation test

### Phase 8: Documentation

20. **Add Decision 38**
    Document rationale for workflow consolidation:
    - Problem: Context loss mid-implementation, duplicate files, bloated gotchas
    - Decision: Consolidate to single instruction file, triage gotchas, simplify implement.prompt.md
    - Trade-offs: Some historical context lost from gotcha removal

21. **Update CHANGELOG**
    Document: instruction file consolidation, gotcha triage, implement.prompt.md simplification

### Phase 9: Validation

22. Run `pytest tests/` — all tests must pass

23. Run `python scripts/validate.py` — must exit 0

24. Report what was implemented
