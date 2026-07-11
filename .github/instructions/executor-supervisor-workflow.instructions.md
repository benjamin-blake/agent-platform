---
applyTo: "scripts/executor/*.py,config/agent/executor/prompts/*.prompt.md,.github/prompts/develop-executor.prompt.md"
---

## Workflow

### Phase 1: Environment Check

1. `git branch --show-current` -- must be `main`.
2. `source .venv/Scripts/activate` (Windows) or `source .venv/bin/activate` (Unix).
3. `python -c "import sys; print(sys.executable)"` -- must show `.venv/Scripts/python.exe`, not `.pyenv/`. If pyenv: `pyenv shell --unset` then re-activate.
4. `cat logs/.execution-state.json` -- if stale checkpoint exists and branch is merged (`git merge-base --is-ancestor <branch> main`), clear with `python -m scripts.execution_state clear`. Do NOT run `git checkout --` after clearing.
5. `git branch | grep agent/` -- delete any branches already merged to main.
6. `git pull origin main`.

### Phase 2: Select Recommendations

1. Read `logs/.recommendations-log.jsonl`. Filter: `status == "open"` AND `automatable == true` AND `risk == "low"`.
2. Skip recs whose `dependencies` array contains any non-`"closed"` rec.
3. Prefer XS/S effort. Select **two** recs (or honour user's specific request).
4. Print summary table: ID, title, effort, priority.
5. **Compound mode:** If user provides a cluster ID or comma-separated rec IDs, use `--compound` instead of individual runs.
6. **Compound batching constraint:** Never batch a rec that modifies `scripts/executor/step_runner.py` model routing with a rec that depends on that new routing in the same compound run. Python's import cache means disk changes to `step_runner.py` are invisible to the running process. Infrastructure recs touching `step_runner.py` must run standalone or as the last rec in a compound.

### Phase 3: Run Executor

**Single rec:** `python -m scripts.execute_recommendation <rec-id>` (no timeout).

**Compound:** `python -m scripts.execute_recommendation --compound <rec-id1>,<rec-id2>,...`

Let the executor run to completion. It handles branching, planning, critique, implementation, validation, code review, PR creation, CI wait, merge, and cleanup.

### Phase 4: Handle Outcome

**If the executor succeeds:**

1. Verify rec status is `"closed"` in the log. If writeback was lost, update manually.
2. Confirm `git branch --show-current` is `main`.
3. `git show HEAD --stat` -- if only `logs/` files changed, note as a no-op (Pattern 7).

**If the executor fails:** Follow the Failure Diagnosis procedure below.

**After each rec (success or failure):**
1. Run the Friction Capture procedure below.
2. **Between-rec checkpoint (MANDATORY):** Before returning to Phase 3, commit all tracked execution artifacts to main:
   ```bash
   git add logs/.execution-step-telemetry.jsonl logs/.retro-lite-log.jsonl logs/runs/
   git diff --cached --stat
   git commit -m "logs: between-rec checkpoint after <rec-id>"
   ```
   If `git diff --cached --stat` shows zero changes, skip the commit. This prevents the next executor run from failing in preflight due to dirty tracked artifacts.
3. Return to Phase 3 for the next rec.

**Mid-batch boundary:** A compound batch is in-flight until every rec in it has been merged, abandoned, or reset to open. Do not commit code or prompt edits to main while a batch is partially resolved.

**After ALL recs are complete:** proceed to Phase 4b before filing any friction recs.

### Phase 4b: Root Cause Analysis — MANDATORY GATE

**Sequencing:** Phase 4b runs ONCE, after all recs in the batch are complete and Friction Capture has been run for each. Friction Capture drafts recs; Phase 4b reviews and files them. Do NOT file recs during Friction Capture.

**Skip condition (happy-path only):** ALL of the following must be true:
- Every rec in the batch succeeded on its first executor invocation (no retries, no `--fast` hotfixes, no manual corrections)
- Zero draft friction recs exist from Friction Capture
- No manual metadata edits were applied between recs (e.g. acceptance field rewrites)

If ANY rec required a retry, hotfix, or manual correction, Phase 4b is MANDATORY even if all recs eventually closed.

**PHASE_4B_STATUS declaration (required):** Before proceeding to Phase 5 or Session Close, the supervisor must state one of:
````
PHASE_4B_STATUS: SKIPPED   (all criteria met -- no friction)
PHASE_4B_STATUS: COMPLETED (RCA invoked, recs filed)
````
Record this declaration in the Session Close Phase 6 review output. Session Close Checklist cannot proceed without this declaration.

**Otherwise, invoke `@rca-analyst`.** Pass:
- Summary table from Phase 4 (rec ID, outcome, transcript paths)
- List of **draft** friction recs (not yet filed)
- Triage observations from Friction Capture

Wait for the subagent to return.

**Validate JSON output:** Confirm the response contains `root_cause_classifications`, `revised_recs`, and `systemic_issues` keys. If malformed, note in Phase 6 review and proceed with original draft recs.

**Apply revisions:**
- If any classification is "prompt deficiency" or "architectural gap", the subagent's `upstream_fix` takes priority over your symptom-level rec
- Replace draft recs with the subagent's `revised_recs` where applicable
- Add any `systemic_issues` to the Phase 6 Priority Actions list

**File recs:** After applying revisions, file the final recs to `logs/.recommendations-log.jsonl` using `replace_string_in_file`. This is the ONLY point where friction recs are written to disk.

### Phase 5: Cross-Run Analysis

After all recs are complete, compare across runs:

1. **Planning quality** -- were certain task types (prompt edits vs code) consistently weaker?
2. **Critique behaviour** -- which recs cycled? What rule caused it?
3. **Scope creep** -- which recs modified files outside their declared scope?
4. **No-ops** -- any PR with zero source file changes?
5. **Systemic issues** -- problems in 2+ runs warrant higher-priority recs.
6. File any cross-run friction recs not already captured per-rec.

### Phase 6: Write Review

Present a structured review:

- **Summary table:** rec ID, title, outcome, PR number
- **What worked well**
- **What needs improvement** (with rec IDs filed)
- **Priority actions** (sorted by impact)
- **Big picture:** process efficiency, fundamental design improvements

#### Session Close Checklist

Follow these steps in order. Do not run `session_postflight.py` until steps 1-4 are complete.

1. `git branch --show-current` -- must be `main`. If on an agent branch, stash nothing -- use `git checkout main` (JSONL stash-pop causes merge conflicts; see Terminal Gotchas).
2. Append session entry to `docs/CHANGELOG.md` using `replace_string_in_file`.
3. Append session entry to `docs/SESSION_LOG.md` using `replace_string_in_file`.
4. Run retro-lite: `python -m scripts.run_retro_lite --append '<JSON>'`.
5. Commit and push session artifacts: `git add docs/CHANGELOG.md docs/SESSION_LOG.md logs/.execution-step-telemetry.jsonl logs/.retro-lite-log.jsonl logs/runs/ && git commit -m "docs: session log for <date>" && git push`.
6. (Optional) `python scripts/session/postflight.py --auto "<message>" --steps-total N --steps-friction M`. This script may create a new branch -- if it does, return to `main` afterwards with `git checkout main && git pull`.

---

## Failure Diagnosis

When the executor fails, diagnose by reading:
- Most recent transcript in `logs/transcripts/` for the rec ID
- `logs/.execution-plans.jsonl` for plan issues
- `logs/.execution-step-telemetry.jsonl` for step-level details

**Identify the fix category:**

| Category | Fix | Where to commit |
|----------|-----|-----------------|
| Acceptance command malformed | Edit `"acceptance"` field in rec log on main, then retry | Main (logs only -- Rule 4) |
| Executor script bug | File XS rec, run `--fast` | Via executor (`--fast`) |
| Prompt template issue | File XS rec, run `--fast` | Via executor (`--fast`) |
| Environment issue (venv, pyenv) | Fix environment, no code change | N/A -- just retry |

**After fixing:** reset rec status to `"open"`, delete stale branch (`git branch -D agent/<rec-id>` + `git push origin --delete agent/<rec-id>`), then re-run.

---

## Friction Capture

Run immediately after each rec completes (success or failure), while context is fresh.

1. List transcripts: `ls -1 logs/transcripts/ | grep <rec-id>`
2. Review plan transcript -- sensible plan or just describing existing code?
3. Scan for **CLI-agent friction:** LLM confusion, wrong file targets, 0-byte context injection, scope creep (`[GIT] Step N diff stat:` lines outside declared `**File**`), plan cycling.
4. Scan for **acceptance failures:** `[ACCEPTANCE] Failed` -- was the code correct but the grep too specific?
5. Scan for **supervisor friction:** manual fixes you applied, executor failures unrelated to the rec, terminal gotchas.
6. Check existing open recs to avoid duplicates.
7. **Draft** new recs (do not file yet). Use `"source": "executor-supervision"`, `"date": "<today>"`, `"status": "open"`. The `"context"` field must cite the specific log/transcript evidence.
8. Prefer XS/S effort recs. Larger friction goes in the Phase 6 review table.
9. **Do NOT write draft recs to disk.** Proceed to Phase 4b, which owns the filing step after RCA review.

---

## Escalation Protocol

### Session Failure Budget

Track two metrics across the session:

- **`machinery_failure_count`**: executor failures caused by machinery bugs (executor scripts, prompts, acceptance parsing), NOT rec-specific logic errors.
- **`machinery_failure_ratio`**: `machinery_failure_count / total_executor_invocations`.

**Abort threshold:** If `machinery_failure_ratio > 0.3` OR `machinery_failure_count > 4`, STOP attempting new recs. Redirect the remainder of the session to infrastructure stabilisation:

1. File recs for every diagnosed machinery bug.
2. Write regression tests for each fix (file as XS recs, run via `--fast`).
3. Success metric shifts from "recs closed" to "executor test coverage delta".

The supervisor may override this budget only with explicit human instruction.

### Failure Escalation (ordered -- follow in sequence)

On executor failure, follow this exact order:

1. **Diagnose** per Failure Diagnosis above. If the fix is `acceptance` field metadata: edit the rec log on main, reset status to `"open"`, and retry. (Attempt 1)
2. If the fix requires changing executor scripts or prompt templates: **file an XS/S rec** with `automatable: true`, then run `python -m scripts.execute_recommendation <new-rec-id> --fast`. (Attempt 2)
2b. **(Optional) If 2nd failure is on the same underlying issue**, invoke `@rca-analyst` with both failure transcripts before Attempt 3. If the subagent identifies an upstream fix (e.g., planning prompt deficiency), apply that fix first rather than retry with `--skip-critique`.
3. If still failing, **try `--skip-critique`** but ONLY after confirming the plan is correct by reading all revision transcripts. (Attempt 3)
4. **After 3 total failures:** stop. File a rec for the underlying issue. STOP -- do not attempt further execution this session.

### Mid-Session Branch Return Protocol

When returning to main after an executor failure mid-session:

1. **Never use `git stash`** for JSONL files -- stash-pop produces merge conflicts on reapply (observed: `logs/.recommendations-log.jsonl`, `logs/.execution-plans.jsonl`).
2. Use `git checkout main` directly. Any uncommitted changes on the agent branch are abandoned (they are executor artefacts, not supervisor work).
3. If `git checkout main` reports JSONL conflicts, resolve with `git checkout --ours logs/.recommendations-log.jsonl` and `git checkout --ours logs/.execution-plans.jsonl`, then `git add` those files.
4. Do NOT use `git stash drop` to discard in-flight JSONL changes -- always prefer `--ours` to keep main's version.

### Critique Cycling (Pattern 11)

When critique keeps flagging the same rule across all revisions:

1. Read transcripts. If the plan logic is wrong, fix the rec acceptance/context and retry.
2. If logic is correct, escalate model tier first.
3. Only use `--skip-critique` after model escalation also fails.
4. File a rec against the specific rule that caused cycling.
