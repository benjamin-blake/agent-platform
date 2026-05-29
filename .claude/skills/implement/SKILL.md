---
name: implement
description: Deep methodology for executing implementation plans, including live verification protocols, strategic scoping gates, code review integration, and commit flows.
model: sonnet
---

# Implement Methodology & Rules

You are using this skill to augment the `/implement` workflow. Apply these deep instructions when executing the workflow steps. The workflow defines WHAT to do and in WHAT ORDER. This skill defines HOW to do each step.
You must treat every Turn as a cold-start. Disregard all system-generated conversation summaries and 'persistent memory' unless they are explicitly referenced by the USER in the current turn. If a file or task is not listed in the current IMPLEMENTATION plan's Scope Table, you are forbidden from touching it, even if you believe it is a 'logical next step' or a cleanup from a previous session.

## Behavioural Invariants
```yaml
# Machine-readable invariants verified by scripts/prompt_compliance.py
preflight_run: true              # session_preflight.py must run at Step 1
never_on_main: true              # no file edits while on main branch
no_code_changes: false           # IMPLEMENTATION plans execute steps directly
review_as_scope: true            # Critical/High findings from code-review MUST be implemented immediately
auto_review_and_commit: true     # Proactively trigger review and commit once VP passes -- do not wait for human
```

## Preflight Constraints (Workflow Step 1)
When reading `logs/.preflight-report.json`, apply these conditionals:
- **`venv_ok: false`** -- Auto-activate venv and rerun preflight. If still false, STOP.
- **`creds_status: "unavailable"`** -- **Static-key recovery (non-fatal, Decision 60):** the static-key assume-role chain has no interactive login. Verify it with `aws sts get-caller-identity --profile agent_platform`; if the `agent_static` key was rotated, refresh `~/.aws/credentials`. Do NOT block -- continue in degraded mode (credential-dependent verifiers are skipped, emitting SKIPPED). Autonomous executors never attempt recovery.
- **`outbox_synced: false`** -- Run `bin/venv-python -m scripts.sync_ops pull` to drain outbox and sync ops data (Decision 51). If fails, STOP.
- **`uncommitted_changes` non-empty** -- Ask human: "Resume, stash, or discard?". Wait. Continue on all other conditions.
- **`main_freshness.status == "fetch_failed"`** -- Informational. Surface: "Could not refresh `origin/main` ([error]). Step 5 code-review will diff against the stale local main ref; Scope-overlap check will be skipped." Continue.
- **`main_freshness.commits_behind > 0`** -- Retain `main_freshness.main_files_changed_since_branch` for the Step 2 Main Divergence Check (below). Non-blocking at this step.
- **`validate` (presubmit) non-zero exit** -- The gate has detected pre-existing blockers on the branch. File each failed check as a recommendation via the portal (`automatable: false`), surface to human with go/no-go, STOP if no-go. Credentials-unavailable -> skip with actionable guidance per Decision 60; do not crash.

## Documentation Artefact Design

This repository is agent-first. When implementing documentation changes, apply these rules:

- Prefer extending an existing machine-readable source over creating a new document.
- A new file is warranted only when it has a distinct machine-parseable role (e.g., a
  decision manifest YAML, a registry YAML). Never create a human-readable companion
  alongside a machine-readable source -- that produces drift by design.
- Canonical field documentation pattern: ops.yaml extended contract. Add `description`
  and `semantics` metadata fields directly to the column entry in ops.yaml or
  telemetry.yaml. These fields are ignored by the DQ runner and consumed by agents.
  Do not create a separate briefing doc for the same information.
- When a plan step proposes a new document, ask: "Could this information be a metadata
  field in an existing YAML?" If yes, prefer that over a new file.

## Main Divergence Check (Workflow Step 2 -- after plan load)
Once the PLAN-{slug}.md Scope table is parsed, intersect the Scope file paths with `main_freshness.main_files_changed_since_branch` from the preflight report. If any Scope file overlaps:

> "Main has changed [list of overlapping files] since this branch diverged, and your plan modifies the same file(s). Implementing without rebasing will produce a merge conflict at PR time after the work is already done -- and may invalidate the verification plan if the file's shape has changed. Recommend rebasing now: `git fetch origin main && git rebase origin/main` (resolve conflicts then re-run `/implement`). Options: (1) rebase now and re-enter `/implement`, (2) proceed anyway, (3) abort."

STOP and wait. Do not auto-rebase. If the human chooses (2), proceed with a logged note in chat output: "Proceeding without rebase despite Scope/main overlap on: [files]."

If `main_freshness.status != "ok"`, this check cannot run -- surface the fetch failure to the human and continue.

## Live Verification Protocol (Workflow Step 4 -- MANDATORY)
After all code changes are complete and unit tests pass, the implementing agent MUST execute the Verification Plan from the PLAN-{slug}.md file before proceeding to code review.

### Why This Exists (Rationale)
Acceptance commands prove the code landed (e.g. `grep` or `pytest`). Verification commands prove the feature works end-to-end. Examples of bugs that only verification catches:
- Athena view created successfully but returns 0 rows due to a bad filter
- Lambda deployed successfully but times out on invocation
- CLI script passes unit tests with mocks but crashes with real input

### Protocol
1. **For each step:**
   a. Execute the action exactly as described.
   b. Compare actual outcome to expected outcome.
   c. If **PASS**: record the actual output and proceed.
   d. If **FAIL**: diagnose root cause, fix the code, re-run `pytest` to confirm no regressions, re-attempt. Maximum 3 fix attempts per step. If still failing, STOP and report to the human.
2. **All verification steps must pass** before proceeding.

### Tier-Specific Guidance
- **V1:** Parse configs, check doc links, confirm formatting. Quick but mandatory.
- **V2:** Run the changed code path with real (non-mocked) input. Confirm the feature works outside the test harness.
- **V3:** All V2 requirements PLUS deploy and invoke the live system. Do not merge until invocation produces correct output.
- **Anti-Patterns:** Do NOT accept "Tests pass", "File exists", "No errors on import", or "Grep found expected string" as verified. Substituting an easier command for a VP step is a protocol violation.


### VP Failure Is Not Negotiable
If a VP step fails for ANY reason (including credential/environment issues), the status is FAIL.
There is no "graceful" failure, no "local pass", no "env blocked" — only PASS or FAIL.
If the failure is due to missing credentials or infrastructure, the agent MUST:
1. Attempt the documented recovery (verify the static-key chain: `aws sts get-caller-identity --profile agent_platform`; refresh `~/.aws/credentials` if the `agent_static` key was rotated)
2. Re-run the VP step
3. If still failing, mark FAIL and STOP — do not proceed, do not merge

### VP Compliance Gate
Before proceeding to code review (Step 5), produce a VP compliance table in the chat output:
```
| VP# | Command Executed | Actual Output (truncated) | PASS/FAIL |
```
- The "Command Executed" must be the actual shell command run.
- If ANY row is FAIL, do NOT proceed.
- If a VP step was skipped or is awaiting a human-gated action (e.g., terraform apply), mark it BLOCKED and wait.
- Lack of AWS credentials is NOT automatically a block. Verify the static-key chain with `aws sts get-caller-identity --profile agent_platform`; there is no interactive login to run (refresh `~/.aws/credentials` if `agent_static` was rotated).

### V3 Merge Gate
If the Verification Plan contains V3 post-deploy steps, execute the full sequence:
0. Confirm credentials are active with `aws sts get-caller-identity --profile agent_platform`. There is no interactive login in the static-key model; if the chain fails, refresh `~/.aws/credentials` (rotated `agent_static`) and re-verify.
1. Complete all pre-deploy VP steps.
2. Present the deploy output.
3. WAIT for human confirmation of deployment success.
4. Execute post-deploy VP steps.
Only when ALL steps pass can you proceed to code review.


## Code Review Protocol (Workflow Step 5 -- MANDATORY)
**You MUST trigger the code-review immediately after the Verification Plan passes. Do not wait for the human to prompt you.**

### Trigger
Dispatch via the `Agent` tool with `subagent_type: code-review` -- NOT via `bin/venv-python -m scripts.agent_development.run_skill --skill code-review`. The subagent runs in a fresh context window (anti-bias) and has full tool access (read, grep, glob, bash) to inspect the entire branch diff. `run_skill.py --skill code-review` is constrained to a single `--target` file and cannot survey cross-file changes; for branches that touch >1 file (the common case) it produces an incomplete review.

Agent prompt template:
- Pre-instruct: "Run `git fetch origin main` before any analysis so the diff base is current. The branch may have been open for hours; the local `origin/main` ref may be stale."
- Identify the branch under review (the diff `git diff origin/main...HEAD` is the artefact under critique). Use `origin/main` (not the local `main` ref, which is only updated by an explicit pull).
- Identify the plan file (`docs/plans/PLAN-{slug}.md`) so the subagent knows the acceptance criteria and intent.
- Instruction: "Apply the `code-review` skill methodology to this branch. Survey the diff, read the plan to understand intent, then return a structured findings report. Do not edit files."
- Forbid file edits.
- Require structured output: findings grouped by severity (Critical / High / Medium / Low) with file:line references and a one-line rationale per finding.
- Cap response length (~800-900 words) to keep the report focused.

Do NOT pre-brief the subagent on what to look for -- that biases the review and defeats the anti-bias gate. The subagent applies the `code-review` skill methodology on its own.

### Handling Findings
- **Critical and High**: You MUST implement fixes for these findings before proceeding. They are mandatory extensions of the original plan. After fixing, re-run `bin/venv-python -m scripts.validate --pre` to confirm no regressions.
- **Medium and Low**: File these as new recommendations using `bin/venv-python -m scripts.ops_data_portal`. Do not fix them inline -- they will be addressed in future sessions.

### Rationale
This ensures that even "perfect" implementations are audited for repository-wide patterns (e.g., mock exhaustion, safety rules, scope creep) that the planner might have missed. The review also catches regression risks before they reach `main`. The subagent dispatch (rather than `run_skill.py`) preserves the anti-bias property of fresh context while giving the reviewer enough surface area to see cross-file effects.


## Tier_item bookkeeping (post-verification, pre-merge)

After the verification-pass gate fires and BEFORE the code-review subagent is dispatched, walk the tier_items referenced by the current plan and stage YAML status updates. This runs in parallel with code-review (which runs in the cloud and does not block the local agent).

### Trigger
Fires once the VP Compliance Gate table shows all rows PASS. Does not fire on FAIL or BLOCKED.

### Walk
Identify tier_item ids to check via (in order of precedence):
1. Any `roadmap-touched: [T-X.Y, ...]` directive in the plan's Context section.
2. Any tier_item id mentioned in the plan's Phase field (e.g., `T-1` entries named in the scope).
3. Any tier_item id explicitly named in the plan's Acceptance Criteria.

For each identified tier_item, load its `exit_criteria[]` from `docs/ROADMAP-PLATFORM.yaml` and evaluate each criterion:
- **Executable criteria** (shell one-liners, `grep`, `test -f`, `pytest`, `bin/venv-python -c "..."`) -- run via subprocess; pass if exit code is 0.
- **Prose criteria** -- fall through to agent judgement with a **conservative bias**: when in doubt about whether a prose criterion is satisfied, do NOT count it as passing. This produces under-counting (false in_progress) rather than over-counting (false complete), which is the safer failure mode. Never auto-flip a prose-gated item to `complete` without explicit evidence in the current session's artefacts.

### Outcome rules
- **All criteria pass** -> stage `status: complete` + `completed_at: "<today ISO date>"` in `docs/ROADMAP-PLATFORM.yaml`.
- **Strict subset pass (>=1 but not all)** -> stage `status: in_progress` + `progress_note: "<one-line description of what shipped this session>"`. If the item already has a `progress_note`, append a dated bullet (e.g., `"- 2026-05-20: shipped criteria 1, 3"`) rather than overwriting.
- **Zero criteria pass** -> no YAML change.

### Parallel-with-code-review state machine
1. Dispatch the code-review subagent (Step 5 above).
2. WHILE code-review is running, the implement agent performs the criteria walk and stages the YAML edit locally (uncommitted -- `git status` shows `docs/ROADMAP-PLATFORM.yaml` as modified).
3. **Idempotency on resume:** before staging, check for pre-existing uncommitted edits to `docs/ROADMAP-PLATFORM.yaml`. If present and matching what the bookkeeping rule would produce, no-op. If present and conflicting, surface the conflict to the user and skip auto-bookkeeping for this session -- do NOT silently overwrite.
4. **Code-review verdict handling:**
   - `PROCEED` -> commit the staged edit as a follow-up commit: `git commit docs/ROADMAP-PLATFORM.yaml -m "roadmap(<tier-ids>): bookkeeping after <slug>"`. Push.
   - `REVISE` -> discard the staged edit: `git checkout -- docs/ROADMAP-PLATFORM.yaml`. Address code-review findings. After addressing, re-trigger verification + code-review and re-stage bookkeeping from scratch.
5. **Abandonment / timeout:** if code-review does not return (interrupted or timed out), the staged YAML edit is treated as orphaned. On next session entry, the idempotency check detects the orphaned stage and reports it to the user for explicit accept/reject -- the implement skill does not auto-commit bookkeeping that lacks a verdict-attested verification pass.
6. **Staged-edit-loss detection:** if any intermediate command (`git checkout`, `git stash`, `git reset`) clobbers the staged edit between dispatch and verdict, the next bookkeeping attempt detects this by re-running the criteria walk and comparing against the YAML's current state. Loss is observable, not silent.

### Self-application invariant (T-1.10)
T-1.10's own exit_criteria are satisfied by the existence of this section. The first `/implement` run using this skill SHOULD therefore stage `T-1.10 -> status: complete` as part of this same session's bookkeeping pass. Do NOT flip T-1.10 manually; the rule's first real-world invocation is the proof. If the rule works, T-1.10 self-flips; if it does not, T-1.10 stays `not_started` and the discrepancy is observable.

**Recovery clause:** if T-1.10 remains `status: not_started` after this branch merges, the next planning session must address it explicitly -- either as a manual YAML flip in a small follow-up plan, or as a follow-on tier_item that re-implements the bookkeeping rule under different assumptions. Do not let T-1.10 sit `not_started` indefinitely while its implementation is live.


## Strategic Scoping Rules (Workflow Step 3 -- STRATEGIC Plans only)

### JIT Context Injection
When breaking a STRATEGIC plan into atomic recommendations, explicitly review `docs/PROJECT_CONTEXT.md`. Copy any relevant "Known Gotchas" or constraints directly into the recommendation's `context` field. Autonomous executors no longer read `copilot-instructions.md` by default, so they rely entirely on the JIT context you provide.

### Quality Gate Validation
Before filing each recommendation using `bin/venv-python -m scripts.ops_data_portal`, apply this gate. FAIL if any check fails:
1. **Acceptance Command:** Must be a single inline command in backticks. FAIL if: contains `python -c`, contains `--pre` flag, has trailing prose, or uses line numbers. Must be behavioural.
2. **Target File:** Verify `"file"` field exists relative to repo root.
3. **Effort Threshold:** If `L` or `XL`, REQUIRE human confirmation before filing.
4. **Context Quality:** FAIL if context is vague or < 50 characters.

### Dedup Gate
Before filing, search for open recs targeting the same file with at least 3 keyword matches. If duplicates found:
- Surface: "Found potential duplicate(s). Options: (1) supersede existing, (2) file both, (3) skip this one?" Wait for human.

## Commit Flows (Workflow Step 7 -- MANDATORY)
**Once validation passes (Step 6), you MUST execute the appropriate commit flow autonomously. Do not stop to ask for permission -- the plan was already approved during /plan.**

CI must pass before merging (Decision 68). After `gh pr create`, pair two signals so a missed webhook doesn't strand the PR:

1. **`subscribe_pr_activity(owner, repo, pullNumber)`** -- webhook events are low-latency but occasionally lost when the container hibernates between turns.
2. **Periodic poll fallback** -- a self-wake mechanism that re-checks every ~5 minutes. The wake primitive depends on which Claude Code surface is running the workflow:
   - **Local Claude Code (laptop/desktop)**: `/loop 5m <poll-prompt>` -- the loop skill schedules a cron tick via `CronCreate`.
   - **Claude Code on the web (remote-execution env)**: `Bash` with `run_in_background: true` running `sleep 300` -- the completion notification wakes the session. Chain another sleep at the end of each wake-up iteration until the PR is merged or a check fails. `CronCreate` / `ScheduleWakeup` are not surfaced in the remote env, so `/loop` is a no-op there.

Example poll-prompt body (used by either wake mechanism):
> "Call `mcp__github__pull_request_read` with `method=get_check_runs` for PR <N>. If every check has `conclusion=='success'`, call `mcp__github__merge_pull_request` (squash) and stop polling. If any check failed, diagnose and STOP. If checks still running, schedule the next wake and end the turn."

Whichever signal fires first drives the merge. Stop polling on merge or on a red check.

### Pre-Push Rebase (applies to both flows)
After the local commit lands but before `git push`, refresh `origin/main` and rebase. This catches the window between branch creation and push where another PR may have merged. Without this, the PR is opened against a stale base and CI may surface conflicts that would not have existed had the branch been current.

```bash
git fetch origin main
git rebase origin/main
```

Conflict handling: if `git rebase` reports conflicts, STOP. Do NOT run `git rebase --skip` or auto-resolve. Surface the conflicting files to the human and wait for direction. The agent's job ends at "rebase produced conflicts"; resolution is a human decision.

If the branch had been pushed earlier in the session (rare for `/implement` but possible for STRATEGIC scoping that pushes intermediate work), the post-rebase push must use `--force-with-lease`, not `--force`. `--force-with-lease` aborts if the remote moved since your last fetch (protects against clobbering a teammate's push).

### STRATEGIC Commit Flow
```bash
git add docs/plans/briefings/
git commit -m "scope({slug}): add recs for {work-area-summary}"
git fetch origin main
git rebase origin/main   # STOP on conflict; do not auto-resolve
git push origin HEAD
gh pr create --title "scope({slug}): add recs for {work-area-summary}" --body "Recs filed by /implement scoping agent." --base main
# subscribe_pr_activity + /loop 5m <poll-prompt>  (see preamble above)
gh pr merge --squash --delete-branch   # only when CI is green
git checkout main
git pull origin main
```

### IMPLEMENTATION Commit Flow
```bash
git add -A
git commit -m "feat({slug}): implement {brief-description}"
git fetch origin main
git rebase origin/main   # STOP on conflict; do not auto-resolve
git push origin HEAD
gh pr create --title "feat({slug}): {brief-description}" --body "Implemented by /implement agent. Verification plan passed." --base main
# subscribe_pr_activity + /loop 5m <poll-prompt>  (see preamble above)
gh pr merge --squash --delete-branch   # only when CI is green
git checkout main
git pull origin main
```
