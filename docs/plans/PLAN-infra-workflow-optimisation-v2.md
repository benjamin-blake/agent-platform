# Plan

## Intent

Reduce token costs across the entire workflow (estimated 30-40% reduction) by consolidating redundant logic into shared utilities, pre-computing context in deterministic scripts, scoping expensive operations to session-relevant files, and enabling true parallel implementation via first-class worktree support. This directly advances the North Star by improving the cost-efficiency of the self-improving feedback loop.

## Plan Type

IMPLEMENTATION

## Branch

agent/infra-workflow-optimisation-v2

## Phase

Infra (workflow optimization iteration 2)

## Scope

| File | Action | Purpose |
|------|--------|---------|
| `scripts/find_plan.py` | Create | Single source of truth for plan file resolution (branch → slug → path) |
| `tests/test_find_plan.py` | Create | Tests for plan discovery logic |
| `scripts/session_postflight.py` | Modify | Import and use `find_plan.py`; add `--close` mode for deterministic session close steps |
| `scripts/plan_audit.py` | Modify | Import and use `find_plan.py` |
| `scripts/session_preflight.py` | Modify | Add context pre-read (ROADMAP, DECISIONS, SESSION_LOG, RECOMMENDATIONS summaries); add worktree venv detection with hardcoded path |
| `scripts/session_metrics.py` | Modify | Add `steps_total`, `steps_with_friction`, `friction_rate` fields to output |
| `tests/test_session_preflight.py` | Modify | Add tests for context pre-read and worktree venv detection |
| `tests/test_session_postflight.py` | Modify | Add tests for `--close` mode |
| `tests/test_session_metrics.py` | Modify | Add tests for step counter fields |
| `.github/agents/code-review.agent.md` | Modify | Call `find_plan.py` via terminal; scope review to changed + scoped files only |
| `.github/agents/scope-guard.agent.md` | Modify | Call `find_plan.py` via terminal |
| `.github/agents/step-validator.agent.md` | Modify | Remove inline plan discovery fallback; call `find_plan.py` via terminal for consistency |
| `tests/test_plan_audit.py` | Modify | Update tests after plan_audit.py refactor to use find_plan.py |
| `scripts/extract_imports.py` | Create | AST-based script to extract `src.*` imports from Python files (more robust than grep) |
| `tests/test_extract_imports.py` | Create | Tests for import extraction logic |
| `.github/prompts/plan.prompt.md` | Modify | Remove Step 3 (context loading); renumber steps; use preflight context summary; make worktrees first-class |
| `.github/prompts/implement.prompt.md` | Modify | Pass step metrics to postflight; move deterministic close steps to `--close`; add worktree detection and cleanup |
| `.github/copilot_instructions.md` | Modify | Remove duplicated rules; update worktree gotcha with hardcoded venv path |
| `docs/AGENT_WORKFLOW.md` | Modify | Update diagram with worktree-based parallel implementation flow |

## Acceptance Criteria

- [ ] `python scripts/find_plan.py` outputs correct plan path for `agent/{slug}` branches; falls back to `PLAN.md` for legacy branches; outputs `NOT_FOUND` when no plan exists
- [ ] `session_preflight.py` outputs `context.roadmap_phase`, `context.open_decisions_count`, `context.recent_sessions`, `context.strategic_review_due` in JSON
- [ ] `/plan` prompt no longer has Step 3 (context loading); steps renumbered 1-10; uses preflight context summary
- [ ] All 3 agents (code-review, scope-guard, step-validator) resolve plan path via `find_plan.py` script call
- [ ] `python scripts/extract_imports.py <file>` outputs `src.*` imports using AST parsing
- [ ] Code-review agent scopes review to `git diff` + Scope table files + direct imports via `extract_imports.py` (not entire repo)
- [ ] `copilot_instructions.md` reduced by removing duplicated rules (retro-lite, plan critique, workflow entry point, closed recommendations)
- [ ] `session_metrics.py` outputs `steps_total`, `steps_with_friction`, `friction_rate` in JSONL
- [ ] `session_postflight.py --close` writes SESSION_LOG entry deterministically and runs pre-commit sanity
- [ ] `/implement` passes `--steps-total N --steps-friction M` to metrics; calls `--close` for deterministic steps
- [ ] Worktree venv detection accepts `C:/Users/bblake/Git Repos/agent-platform/.venv` when running in worktree
- [ ] `/implement` detects worktree via `git rev-parse --show-toplevel` and cleans up after merge
- [ ] `pytest tests/` -- all tests pass
- [ ] `python scripts/validate.py` -- exit 0

## Constraints

- Python scripts only for automation (no shell scripts)
- Windows-compatible commands (bash syntax for terminal examples)
- Hardcoded venv path is company-VM-specific (`C:/Users/bblake/...`)
- Must maintain backwards compatibility with legacy `PLAN.md` format for in-flight work
- Code-review scoping must not break detection of issues in files imported by changed files

## Context

- Decision 25: Git worktrees approved for parallel development
- Decision 26: 2-chat model with local automation layers already implemented
- Known Gotcha: Virtual environment switching between repos causes import errors
- Known Gotcha: Pre-commit hooks may modify files on first 1-2 commit attempts
- Previous friction: Wrong venv activated at session start (recurring pattern in retro-lite log)

## Pre-Implementation Checklist

> The implementing agent must verify all items before editing any file.
- [ ] Branch confirmed not on `main`
- [ ] copilot_instructions.md read (rules, gotchas, file router)
- [ ] DECISIONS.md read (no conflicts with prior decisions)
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps

> **Execute these in sequence. Do not substitute the Scope table as a work list.**

### Phase 1: Create find_plan.py + Tests

1. Create `scripts/find_plan.py` with:
   - `find_plan_file()` function that returns `Path | None`
   - Logic: get current branch via `git branch --show-current`; if starts with `agent/`, extract slug, check `docs/plans/PLAN-{slug}.md`; fallback to `docs/plans/PLAN.md`; return `None` if neither exists
   - CLI entry point: prints plan path or `NOT_FOUND` to stdout
   - Use `subprocess.run` with `encoding='utf-8'` for git calls
   - Exit 0 always (output indicates result)

2. Create `tests/test_find_plan.py` with tests for:
   - Branch `agent/foo-bar` → finds `PLAN-foo-bar.md`
   - Branch `agent/foo-bar` with no branch-specific plan → falls back to `PLAN.md`
   - Branch `main` → falls back to `PLAN.md`
   - No plan file exists → returns `None` / outputs `NOT_FOUND`
   - Use `tmp_path` and mock `subprocess.run` for git calls

3. Run `pytest tests/test_find_plan.py -v` -- all tests must pass

### Phase 2: Refactor Python Scripts to Use find_plan.py

4. Modify `scripts/plan_audit.py`:
   - Import `find_plan_file` from `scripts.find_plan`
   - Replace inline `find_plan_file()` function with imported one
   - Remove duplicated logic

5. Modify `scripts/session_postflight.py`:
   - Import `find_plan_file` from `scripts.find_plan`
   - Replace `_find_plan_file()` with imported `find_plan_file()`
   - Remove duplicated logic

6. Update `tests/test_plan_audit.py`:
   - Verify existing tests still pass after refactor (find_plan_file is now imported, not inline)
   - Mock `find_plan_file` if tests previously mocked the inline function directly

6b. Run `pytest tests/test_plan_audit.py tests/test_session_postflight.py -v` -- all tests must pass

### Phase 3: Refactor Agents to Call find_plan.py

7. Modify `.github/agents/code-review.agent.md` Step 0:
   - Replace inline branch/plan resolution logic with:
     ```bash
     python scripts/find_plan.py
     ```
   - Read the output line; if `NOT_FOUND`, proceed without plan context (note in report)
   - Otherwise read the plan file at the output path

8. Modify `.github/agents/scope-guard.agent.md` Step 1:
   - Replace inline plan discovery logic with `python scripts/find_plan.py` call
   - Handle `NOT_FOUND` output

9. Modify `.github/agents/step-validator.agent.md` Step 2:
   - Replace any inline plan discovery fallback logic with `python scripts/find_plan.py` call
   - The caller passes the plan file path, but the agent should use `find_plan.py` for consistency with other agents
   - Handle `NOT_FOUND` output by reporting error to caller

### Phase 4: Extend session_preflight.py with Context Pre-Read

10. Modify `scripts/session_preflight.py` to add context pre-read:
    - Add `read_context_files()` function that returns a dict with:
      - `roadmap_phase`: parse `## Phase X.Y:` header from ROADMAP.md, extract phase name and completion status
      - `open_decisions_count`: count `## Decision` headers in DECISIONS.md that contain `(Open)` or similar
      - `recent_sessions`: extract last 5 `## [YYYY-MM-DD]` entries from SESSION_LOG.md (date + Done line only)
      - `strategic_review_due`: check if any SESSION_LOG entry in last 30 days mentions "strategic review"
      - `recommendations_count`: count open rows in RECOMMENDATIONS.md Open table
    - Add `context` key to the output JSON containing this dict
    - Handle missing files gracefully (return defaults)

11. Modify `tests/test_session_preflight.py`:
    - Add tests for `read_context_files()` with mock files in `tmp_path`
    - Test missing files return sensible defaults
    - Test strategic_review_due detection

12. Run `pytest tests/test_session_preflight.py -v` -- all tests must pass

### Phase 5: Slim /plan Prompt

13. Modify `.github/prompts/plan.prompt.md`:
    - Remove Step 3 entirely (context loading) -- preflight JSON now contains context summary
    - Add new Step 2: "Read Context from Preflight" that instructs Opus to use the `context` section of preflight JSON
    - Renumber remaining steps: current Step 4 becomes Step 3, etc. (final steps should be 1-10)
    - Update Step 0 to reference that preflight output includes context summary

14. Verify `/plan` prompt step numbering is now sequential 0-10 with no gaps

### Phase 6: Scope Code-Review Agent

15. Create `scripts/extract_imports.py`:
    - Use Python's `ast` module to reliably extract `src.*` imports from Python files
    - Handle both `import src.X` and `from src.X import Y` patterns
    - Handle multi-line imports and edge cases
    - CLI: accepts file paths as arguments, outputs one import module per line (e.g., `src.common`, `src.data`)
    - Gracefully handle syntax errors and missing files (skip them)

15b. Create `tests/test_extract_imports.py`:
    - Test `import src.common.config` extraction
    - Test `from src.data.pipeline import DataPipeline` extraction
    - Test files with no src imports return empty
    - Test syntax error files are skipped gracefully

15c. Modify `.github/agents/code-review.agent.md`:
    - Replace "## Review Process" section step 2 ("Read every source file") with scoped approach:
      - Run `git diff --name-only origin/main` to get changed files
      - Parse plan file Scope table to get planned files
      - For each Python file in changed + planned, extract imports via: `python scripts/extract_imports.py <file>`
      - Read: changed files + planned files + imported modules (resolve to paths via file router)
      - Skip entire directories like `src/data/handlers/` unless specific files are in scope
    - Update review instructions to note: "Review scope is limited to session-relevant files. Issues in other files are out of scope for this review."

16. Add guidance for what "direct imports" means:
    - If `src/data/pipeline.py` is changed and imports `from src.common.config import Config`, then `src/common/config.py` is in scope
    - Do not recursively follow imports (only 1 level deep)
    - Test files are in scope only if `tests/` files are in the diff or Scope table

### Phase 7: Trim copilot_instructions.md

17. Modify `.github/copilot_instructions.md`:
    - Remove the "Retro-lite" rule paragraph (already in implement.prompt.md Step 6)
    - Remove the "Plan critique" rule paragraph (already in plan.prompt.md Step 9)
    - Remove the "Workflow entry point" multi-sentence description (keep only the file router entry)
    - Remove the "Closed recommendations" rule (already in retrospective.agent.md Phase 6)
    - Keep all cross-cutting rules: branching, context budget, AWS, File Router, Known Gotchas
    - Verify remaining content is not duplicated elsewhere

18. Count lines before and after; target ~80-100 lines removed

### Phase 8: Implement Step Counter

19. Modify `scripts/session_metrics.py`:
    - Add CLI arguments `--steps-total` and `--steps-friction` (integers, default 0)
    - Add these fields to the JSONL output record
    - Compute `friction_rate = steps_friction / steps_total` if steps_total > 0, else 0.0
    - Add to console output: "Steps: {total} total, {friction} with friction ({rate}%)"

20. Modify `tests/test_session_metrics.py`:
    - Add tests for `--steps-total` and `--steps-friction` arguments
    - Test `friction_rate` computation (including divide-by-zero case)

21. Modify `.github/prompts/implement.prompt.md`:
    - In Step 6 (execute steps), add instruction: "Track the count of steps that had friction (tool failures, retries, unexpected states)"
    - In Step 13 (metrics), change command to:
      ```bash
      python scripts/session_postflight.py --metrics --steps-total <N> --steps-friction <M>
      ```
      where N is total Ordered Execution Steps and M is count of steps where retro-lite recorded friction

22. Run `pytest tests/test_session_metrics.py -v` -- all tests must pass

### Phase 9: Add --close Mode to session_postflight.py

23. Modify `scripts/session_postflight.py`:
    - Add `--close` argument to argparse
    - Add `run_close()` function that:
      - Runs intent verification: parse plan file Intent section, run `git diff --stat origin/main`, output comparison
      - Generates SESSION_LOG entry from template using metrics JSON (if available)
      - Runs pre-commit sanity check
      - Returns JSON with `intent_achieved`, `session_log_entry`, `sanity_status`

24. Modify `tests/test_session_postflight.py`:
    - Add tests for `--close` mode
    - Test intent verification with mock plan and git diff
    - Test SESSION_LOG template generation

25. Modify `.github/prompts/implement.prompt.md`:
    - Move Steps 12 (intent verification), 15 (session log write), 16 (pre-commit sanity) to use:
      ```bash
      python scripts/session_postflight.py --close
      ```
    - Keep Step 14 (retrospective invocation) as agent step -- needs context
    - Renumber steps accordingly

26. Run `pytest tests/test_session_postflight.py -v` -- all tests must pass

### Phase 10: Worktree First-Class Implementation

27. Modify `scripts/session_preflight.py`:
    - Add constant: `MAIN_REPO_VENV = Path("C:/Users/bblake/Git Repos/agent-platform/.venv/Scripts/python.exe")`
    - Modify `check_venv()`:
      - If `sys.executable` matches `MAIN_REPO_VENV`, return `True` (main repo venv is always valid)
      - Otherwise, check if repo name is in `sys.executable` path (current behavior)
    - Add `is_worktree()` function: compare `git rev-parse --show-toplevel` to current working directory; if different, we're in a worktree

28. Modify `tests/test_session_preflight.py`:
    - Add tests for `check_venv()` with worktree scenario (sys.executable = MAIN_REPO_VENV, cwd is different)
    - Add tests for `is_worktree()` detection

29. Modify `.github/prompts/plan.prompt.md` Step 7c:
    - Change from "(Optional)" to "Worktree Setup (for parallel development)"
    - Add explicit venv instruction:
      ```
      The worktree shares the main repository's venv. No separate venv setup is needed.
      When opening the worktree in VS Code, the main repo's venv will be used automatically
      because session_preflight.py accepts it via hardcoded path.
      ```
    - Add: "If you want to implement this feature in parallel, create the worktree now. Otherwise skip to Step 8."

30. Modify `.github/prompts/implement.prompt.md`:
    - Add Step 0b after branch verification: "Worktree Detection"
      ```bash
      TOPLEVEL=$(git rev-parse --show-toplevel)
      if [[ "$TOPLEVEL" != "$(pwd)" ]]; then
        echo "Running in worktree: $TOPLEVEL"
      fi
      ```
    - Add to Session Close Phase (after merge): "Worktree Cleanup"
      ```bash
      # If running in a worktree, remove it after successful merge
      if [[ -n "$WORKTREE_PATH" ]]; then
        cd ..
        git worktree remove "$WORKTREE_PATH"
      fi
      ```

31. Modify `.github/copilot_instructions.md` Known Gotchas:
    - Update "Git worktrees for parallel development" gotcha to include:
      ```
      Worktrees use the main repository's venv (hardcoded path: C:/Users/bblake/Git Repos/agent-platform/.venv).
      session_preflight.py accepts this venv when running in any worktree of this repo.
      ```

32. Run `pytest tests/test_session_preflight.py -v` -- all tests must pass

### Phase 11: Documentation Updates

33. Modify `docs/AGENT_WORKFLOW.md`:
    - Update the workflow diagram to show worktree-based parallel flow:
      ```
      /plan (main) ──► agent/{slug} branch ──► worktree (optional)
                                               │
                                               ▼
                                          /implement in worktree VS Code window
                                               │
                                               ▼
                                          merge + worktree cleanup
      ```
    - Add section "Parallel Implementation with Worktrees" explaining the flow

34. Run `pytest tests/` -- all tests must pass

35. Run `python scripts/validate.py` -- must exit 0

36. Report what was implemented and any design decisions made during implementation
