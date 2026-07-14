# Plan

## Intent
Constrain the supervisor agent to use the executor pipeline as the sole mechanism for applying fixes, eliminating all direct-edit and hotfix-branch escape hatches. This closes the behavioral latitude gap that allows supervisors to bypass validation, telemetry, and code review -- a prerequisite for autonomous operation.

## Plan Type
IMPLEMENTATION

## Branch
agent/infra-hotfix-routing

## Phase
Infrastructure rescue (executor reliability hardening)

## Scope
| File | Action | Purpose |
|------|--------|---------|
| .github/instructions/executor-supervisor-workflow.instructions.md | Modify | Replace Hotfix Branch Protocol with --fast-only delegation. Remove direct-edit path entirely. Update Failure Escalation to terminate at "file rec + stop" instead of manual fix. Add mid-session stash-pop conflict protocol (rec-397 bundled). |
| .github/instructions/executor-supervisor-rules.instructions.md | Modify | Update Rule 4 (Commit Policy) to remove hotfix branch references. Update Rule 2 (Allowed Files) to clarify that edits are limited to rec metadata and logs -- not executor machinery during a run. |
| .github/prompts/develop-executor.prompt.md | Modify | Remove any remaining references to direct edits or hotfix branches in the Failure Diagnosis cross-reference. Add the stash-pop conflict protocol for mid-session branch returns (rec-397). |

## Bundled Recommendations
- rec-414: Route hotfixes through executor pipeline (primary)
- rec-397: Document mid-session stash-pop conflict protocol for JSONL files (bundled, same target file)

## Acceptance Criteria
- [ ] No occurrence of "hotfix branch", "direct edit", or "emergency fallback" in any of the three modified files
- [ ] The string "--fast" appears in executor-supervisor-workflow.instructions.md as the sole fix mechanism
- [ ] grep for "Hotfix Branch Protocol" returns zero matches across all .instructions.md and .prompt.md files
- [ ] The stash-pop conflict protocol appears in develop-executor.prompt.md (rec-397 acceptance: `grep -qE "checkout.*--ours|--ours|stash.*drop" .github/prompts/develop-executor.prompt.md`)
- [ ] `grep -qi 'fast\|delegate.*hotfix\|hotfix.*executor\|prefer.*fast' .github/prompts/develop-executor.prompt.md` passes (rec-414 acceptance)

## Constraints
- No Python code changes -- this is a prompt/instructions-only change
- The supervisor must not have any documented path to edit executor machinery directly
- rec-413 (--fast mode) is closed -- the executor already supports the `--fast` and `--plan-json` flags
- The Failure Diagnosis table (what category of fix) is still useful for diagnosis -- but the "Where to commit" column must route everything through --fast, not hotfix branches
- copilot-instructions.md Known Gotchas rule: "replace_string_in_file context boundary: Include 3-5 lines of unchanged code before and after target text"

## Context
- Decision 42: Three-Tier Workflow Architecture -- supervisor is an autonomous execution tier, not a code-editing tier
- rec-413 (closed): Implemented `--fast` mode with `--plan-json` support, phase skipping, and finalize flow
- rec-397 (open, automatable: false): Mid-session stash-pop conflict protocol -- bundled here since it targets the same prompt file
- Transcript evidence: GPT-5.4 supervisor used direct-edit latitude to pre-filter duplicate recs, skip session close, and apply manual hotfixes without telemetry. Removing the path eliminates the temptation.
- The supervisor model has been switched to Claude Sonnet 4.6 as of this session

## Pre-Implementation Checklist
> The implementing agent must verify all items before editing any file.
- [ ] Branch confirmed not on `main`
- [ ] copilot-instructions.md read (rules, gotchas, file router)
- [ ] DECISIONS.md read (no conflicts with prior decisions)
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps
> **Execute these in sequence. Do not substitute the Scope table as a work list.**

1. **Read** `.github/instructions/executor-supervisor-workflow.instructions.md` in full. Identify the exact text of: (a) Failure Diagnosis table "Where to commit" column, (b) Escalation and Hotfix Protocol section header, (c) Hotfix Branch Protocol subsection, (d) Failure Escalation subsection steps 1-4. Note the surrounding context lines for each.

2. **Modify** `.github/instructions/executor-supervisor-workflow.instructions.md`:
   - In the Failure Diagnosis table, replace the "Where to commit" column. Every row currently says "Hotfix branch (Rule 4)". Replace with the new delegation path:
     - Acceptance command malformed: `Edit "acceptance" field in rec log on main, then retry`
     - Executor script bug: `File XS rec, run --fast`
     - Prompt template issue: `File XS rec, run --fast`
     - Environment issue: unchanged (N/A -- just retry)
   - Replace the entire "Escalation and Hotfix Protocol" section (from `## Escalation and Hotfix Protocol` through end of `### Critique Cycling (Pattern 11)`) with a new section that:
     - Keeps Session Failure Budget (unchanged -- the abort threshold logic is correct)
     - Replaces Failure Escalation with: diagnose -> file XS/S rec with `automatable: true` -> run `python -m scripts.execute_recommendation <new-rec-id> --fast` -> if --fast fails, file a rec for the underlying issue and STOP
     - Removes Hotfix Branch Protocol entirely (no replacement)
     - Keeps Critique Cycling (Pattern 11) unchanged
   - Add a new subsection "Mid-Session Branch Return Protocol" documenting: when returning to main after executor failure, use `git checkout main` (never stash), and for JSONL conflicts use `git checkout --ours <file>` to keep main's version

3. **Modify** `.github/instructions/executor-supervisor-rules.instructions.md`:
   - Rule 2 (Allowed Files): keep the table but add a note below it: "During an executor run, the supervisor may only edit `logs/` files and rec metadata in `.recommendations-log.jsonl`. All other fixes (executor scripts, prompts, acceptance commands) must be filed as recs and executed via `--fast`."
   - Rule 4 (Commit Policy): replace the hotfix branch reference with: "During a rec run, only `logs/` file changes may be committed directly to main. All non-log fixes must be filed as a new rec and executed via `--fast`. Between rec runs, only `logs/` files and session artifacts (`docs/CHANGELOG.md`, `docs/SESSION_LOG.md`) may be committed directly to main. All code and prompt fixes must be filed as a new rec and executed via `--fast`."

4. **Modify** `.github/prompts/develop-executor.prompt.md`:
   - Add a "Mid-Session JSONL Conflict Resolution" subsection (placed after the Session Close Checklist) that documents: `git checkout --ours logs/.recommendations-log.jsonl` and `git checkout --ours logs/.execution-plans.jsonl` as the canonical resolution, followed by `git add` and continue. Warn: never use `git stash pop` for JSONL files mid-session.

5. **Verify acceptance criteria:**
   - `grep -rn "hotfix branch\|Hotfix Branch\|direct edit\|emergency fallback" .github/instructions/executor-supervisor-workflow.instructions.md .github/instructions/executor-supervisor-rules.instructions.md .github/prompts/develop-executor.prompt.md` must return zero matches
   - `grep -q "\-\-fast" .github/instructions/executor-supervisor-workflow.instructions.md` must pass
   - `grep -qE "checkout.*--ours|--ours|stash.*drop" .github/prompts/develop-executor.prompt.md` must pass
   - `grep -qi 'fast\|delegate.*hotfix\|hotfix.*executor\|prefer.*fast' .github/prompts/develop-executor.prompt.md` must pass

6. Run `python scripts/validate.py` -- must exit 0

7. Report what was changed and confirm both rec-414 and rec-397 acceptance criteria pass
