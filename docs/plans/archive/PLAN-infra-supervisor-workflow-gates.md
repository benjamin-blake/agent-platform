# Plan

## Intent
Close gaps in the supervisor workflow that allow execution artifacts to accumulate uncommitted between recs, Phase 4b to be skipped without explicit justification, and manual commits to capture unintended changes. These gaps repeatedly caused wasted executor runs and required human intervention to unblock sessions.

## Plan Type
IMPLEMENTATION

## Branch
agent/infra-supervisor-workflow-gates

## Phase
Infra (phase-independent governance)

## Scope
| File | Action | Purpose |
|------|--------|---------|
| .github/prompts/develop-executor.prompt.md | Modify | Add between-rec checkpoint (rec-420), tighten Phase 4b skip (rec-408), add staged-diff inspection (rec-317), document COPILOT_STEP_TIMEOUT_SECS (rec-328) |
| .github/instructions/executor-supervisor-workflow.instructions.md | Modify | Add tracked artifact list to between-rec checkpoint (rec-420), tighten Phase 4b skip (rec-408), clarify Rule 4 mid-batch boundary (rec-321) |
| .github/instructions/executor-supervisor-rules.instructions.md | Modify | Clarify Rule 4 in-flight boundary for mid-batch pauses (rec-321) |
| logs/.recommendations-log.jsonl | Modify | Write back rec-414 status to closed (PR #220 already merged, writeback lost) |

## Bundled Recommendations
- **rec-420** (XS, High): Between-rec checkpoint + expanded tracked artifact list
- **rec-408** (XS, High): Explicit PHASE_4B_STATUS gate before session close
- **rec-317** (XS, High): Pre-commit staged-diff inspection
- **rec-321** (XS, Medium): Clarify Rule 4 in-flight boundary for mid-batch pauses
- **rec-328** (XS, Medium): Document COPILOT_STEP_TIMEOUT_SECS env var
- **rec-414** (housekeeping): Status writeback only -- already implemented in PR #220

## Acceptance Criteria
- [ ] rec-420: `grep -q 'between-rec checkpoint' .github/prompts/develop-executor.prompt.md && grep -q 'logs/.execution-step-telemetry.jsonl' .github/prompts/develop-executor.prompt.md && grep -q 'logs/.recommendations-log.jsonl' .github/instructions/executor-supervisor-workflow.instructions.md`
- [ ] rec-408: `grep -q 'PHASE_4B_STATUS' .github/prompts/develop-executor.prompt.md && grep -q 'PHASE_4B_STATUS' .github/instructions/executor-supervisor-workflow.instructions.md && grep -q 'first executor invocation' .github/prompts/develop-executor.prompt.md`
- [ ] rec-317: `grep -q 'diff.*cached' .github/prompts/develop-executor.prompt.md`
- [ ] rec-321: `grep -qE 'batch.*merged.*abandoned|batch.*fully.*resolved' .github/prompts/develop-executor.prompt.md`
- [ ] rec-328: `grep -q 'COPILOT_STEP_TIMEOUT_SECS' .github/prompts/develop-executor.prompt.md`
- [ ] rec-414: `python -c "import json; r=[json.loads(l) for l in open('logs/.recommendations-log.jsonl',encoding='utf-8') if l.strip() and '\"rec-414\"' in l][0]; assert r['status']=='closed'"`
- [ ] All acceptance commands from the original recs pass

## Constraints
- Windows Git Bash (no PowerShell)
- All changes are prompt/instruction file edits -- no Python code changes
- Edits must not break existing acceptance commands from rec-414 (already implemented: `grep -qi 'fast' .github/prompts/develop-executor.prompt.md`)
- These are executor boundary files per Decision 44 -- they cannot be implemented by the executor itself

## Context
- Decision 42 (Three-Tier Workflow Architecture) governs the /plan -> /implement -> /develop-executor separation
- Decision 44 (Executor Self-Modification Boundary) requires these files to go through /plan -> /implement, not the executor
- rec-414 was implemented in PR #220 (commit 90c6297, merged to main) but status writeback was lost in JSONL. rec-397 was already superseded as part of that same plan.
- The between-rec checkpoint gap (rec-420) directly caused rec-411 to fail in preflight because logs/.recommendations-log.jsonl was dirty after rec-419 success
- The Phase 4b skip gap (rec-408) caused rec-365 step-1 cross-file scope creep to go undetected until retroactive RCA

## Pre-Implementation Checklist
> The implementing agent must verify all items before editing any file.
- [ ] Branch confirmed not on `main`
- [ ] copilot-instructions.md read (rules, gotchas, file router)
- [ ] DECISIONS.md read (no conflicts with prior decisions)
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps

### Step 1: Add between-rec checkpoint to develop-executor.prompt.md (rec-420)
**File:** .github/prompts/develop-executor.prompt.md
**Action:** Replace the current "After each rec" line in Phase 4 with a between-rec checkpoint block. The current text at approximately line 68 reads:

```
**After each rec (success or failure):** run the Friction Capture procedure below, then return to Phase 3 for the next rec.
```

Replace with:

```
**After each rec (success or failure):**
1. Run the Friction Capture procedure below.
2. **Between-rec checkpoint (MANDATORY):** Before returning to Phase 3, commit all tracked execution artifacts to main:
   ```bash
   git add logs/.recommendations-log.jsonl logs/.execution-plans.jsonl logs/.execution-step-telemetry.jsonl logs/.retro-lite-log.jsonl logs/.session-telemetry.jsonl logs/runs/
   git diff --cached --stat
   git commit -m "logs: between-rec checkpoint after <rec-id>"
   ```
   If `git diff --cached --stat` shows zero changes, skip the commit. This prevents the next executor run from failing in preflight due to dirty tracked artifacts.
3. Return to Phase 3 for the next rec.
```

Also add the same tracked artifact list to the Session Close Checklist step 5 by expanding the `git add` command to include all tracked artifact files (currently only lists `docs/CHANGELOG.md docs/SESSION_LOG.md logs/.retro-lite-log.jsonl logs/.session-telemetry.jsonl` but misses `logs/.recommendations-log.jsonl logs/.execution-plans.jsonl logs/.execution-step-telemetry.jsonl logs/runs/`).

**Acceptance:** `grep -q 'between-rec checkpoint' .github/prompts/develop-executor.prompt.md && grep -q 'logs/.execution-step-telemetry.jsonl' .github/prompts/develop-executor.prompt.md`

### Step 2: Mirror between-rec checkpoint in workflow instructions (rec-420)
**File:** .github/instructions/executor-supervisor-workflow.instructions.md
**Action:** Apply the same between-rec checkpoint block to the matching "After each rec" line in Phase 4. The current text at approximately line 44 reads:

```
**After each rec (success or failure):** run the Friction Capture procedure below, then return to Phase 3 for the next rec.
```

Replace with the same expanded block from Step 1. Also expand the Session Close Checklist git add command to include all tracked artifacts (same additions as Step 1).

Also add `logs/.recommendations-log.jsonl` to the artifact list referenced in the Session Close Checklist.

**Acceptance:** `grep -q 'between-rec checkpoint' .github/instructions/executor-supervisor-workflow.instructions.md && grep -q 'logs/.recommendations-log.jsonl' .github/instructions/executor-supervisor-workflow.instructions.md`

### Step 3: Tighten Phase 4b skip condition (rec-408)
**File:** .github/prompts/develop-executor.prompt.md
**Action:** Replace the current Phase 4b skip condition. The current text reads:

```
**Skip condition:** All recs succeeded AND zero draft friction recs exist. In this case, proceed directly to Phase 5.
```

Replace with:

```
**Skip condition (happy-path only):** ALL of the following must be true:
- Every rec in the batch succeeded on its first executor invocation (no retries, no `--fast` hotfixes, no manual corrections)
- Zero draft friction recs exist from Friction Capture
- No manual metadata edits were applied between recs (e.g. acceptance field rewrites)

If ANY rec required a retry, hotfix, or manual correction, Phase 4b is MANDATORY even if all recs eventually closed.

**PHASE_4B_STATUS declaration (required):** Before proceeding to Phase 5 or Session Close, the supervisor must state one of:
```
PHASE_4B_STATUS: SKIPPED   (all criteria met -- no friction)
PHASE_4B_STATUS: COMPLETED (RCA invoked, recs filed)
```
Record this declaration in the Session Close Phase 6 review output. Session Close Checklist cannot proceed without this declaration.

**Implementer note:** The replacement text contains triple-backtick fences. Use 4-backtick (````) or tilde (~~~) outer fences in the target Markdown file to avoid nesting ambiguity.
```

Apply the same replacement in `.github/instructions/executor-supervisor-workflow.instructions.md`.

**Acceptance:** `grep -q 'PHASE_4B_STATUS' .github/prompts/develop-executor.prompt.md && grep -q 'PHASE_4B_STATUS' .github/instructions/executor-supervisor-workflow.instructions.md && grep -q 'first executor invocation' .github/prompts/develop-executor.prompt.md`

### Step 4: Add staged-diff inspection to commit protocol (rec-317)
**File:** .github/prompts/develop-executor.prompt.md
**Action:** Add a pre-commit staged-diff inspection rule. In the Session Close Checklist (after step 4, before step 5), add:

```
4b. **Pre-commit staged-diff inspection:** Before any `git commit` on main, run `git diff --cached --name-only` and verify every staged file is intentional. If any file outside `logs/` and `docs/` appears, STOP -- unstage it with `git reset HEAD <file>`. This prevents executor-generated residue from leaking into supervisor commits.
```

Also add this rule to Rule 4 (Commit Policy) in executor-supervisor-rules.instructions.md as a procedural enforcement note:

```
**Pre-commit check:** Always run `git diff --cached --name-only` before committing. If any file outside `logs/` and `docs/` is staged, unstage it (`git reset HEAD <file>`) -- it is likely executor residue from a failed run.
```

**Acceptance:** `grep -q 'diff.*cached' .github/prompts/develop-executor.prompt.md`

### Step 5: Clarify Rule 4 mid-batch boundary (rec-321)
**File:** .github/instructions/executor-supervisor-rules.instructions.md
**Action:** Expand Rule 4 (Commit Policy) to clarify the mid-batch pause boundary. The current text distinguishes "During a rec run" from "Between rec runs" but does not address mid-batch pauses (when a compound batch has been interrupted but not all recs have merged or been abandoned). Add after the existing Rule 4 text:

```
**Mid-batch pause boundary:** If a compound batch is interrupted (some recs merged, others pending), the batch is NOT complete until all remaining recs are either merged, abandoned (`git branch -D`), or their status reset to `"open"`. Until the batch is fully resolved, the "During a rec run" restrictions apply -- no code or prompt edits on main. Only metadata and log fixes are permitted.
```

Also add a matching note in develop-executor.prompt.md Phase 4 section:

```
**Mid-batch boundary:** A compound batch is in-flight until every rec in it has been merged, abandoned, or reset to open. Do not commit code or prompt edits to main while a batch is partially resolved.
```

**Acceptance:** `grep -qE 'batch.*merged.*abandoned|all.*recs.*merged|batch.*fully.*resolved' .github/prompts/develop-executor.prompt.md`

### Step 6: Document COPILOT_STEP_TIMEOUT_SECS (rec-328)
**File:** .github/prompts/develop-executor.prompt.md
**Action:** Add `COPILOT_STEP_TIMEOUT_SECS` to an Environment Variables section. If no such section exists, add one after the Escalation Protocol section heading (or before the Terminal Gotchas if one exists). The entry should read:

```
### Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `COPILOT_STEP_TIMEOUT_SECS` | 300 | Maximum seconds for a single implementation step CLI call in `scripts/executor/step_runner.py`. Increase for large-file recs (e.g., `COPILOT_STEP_TIMEOUT_SECS=600`). If a step hits this timeout, the executor logs `CLI_ERROR` and the supervisor should retry with a higher value before escalating. |
| `SKIP_CI_WAIT` | (unset) | When set to `true`, the executor skips waiting for CI checks after PR creation. Use when GitHub Actions billing is paused or CI is known-broken. |
```

If SKIP_CI_WAIT is already documented elsewhere, only add the COPILOT_STEP_TIMEOUT_SECS row.

**Acceptance:** `grep -q 'COPILOT_STEP_TIMEOUT_SECS' .github/prompts/develop-executor.prompt.md`

### Step 7: Write back rec-414 status (housekeeping)
**File:** logs/.recommendations-log.jsonl
**Action:** Find the rec-414 line and update its status from `"open"` to `"closed"`. Add `"execution_result": "manual"`, `"execution_date": "2026-04-18T11:00:00+01:00"`, `"execution_branch": "agent/infra-hotfix-routing"`, `"execution_pr_url": "https://github.com/benjamin-blake/agent-platform/pull/220"`. Use `replace_string_in_file` with the rec-414 JSON line as anchor.

**Acceptance:** `python -c "import json; r=[json.loads(l) for l in open('logs/.recommendations-log.jsonl',encoding='utf-8') if l.strip() and '\"rec-414\"' in l][0]; assert r['status']=='closed', r['status']"`

### Step 8: Run validation
**Action:** Run `python -m scripts.validate --scope prompts` to verify prompt/instruction file formatting. Then run all acceptance commands from the bundled recs.

**Acceptance:** `python -m scripts.validate --scope prompts`

### Step 9: Report
Report what was implemented and any design decisions made during implementation.
