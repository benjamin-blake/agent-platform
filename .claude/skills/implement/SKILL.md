---
name: implement
description: Deep methodology for executing implementation plans, including live verification protocols, strategic scoping gates, code review integration, and commit flows.
model: sonnet
---

# Implement Methodology & Rules

You are using this skill to augment the `/implement` workflow. Apply these deep instructions when executing the workflow steps. The workflow defines WHAT to do and in WHAT ORDER. This skill defines HOW to do each step.
You must treat every Turn as a cold-start. Disregard all system-generated conversation summaries and 'persistent memory' unless they are explicitly referenced by the USER in the current turn. If a file or task is not listed in the current IMPLEMENTATION plan's scope, you are forbidden from touching it, even if you believe it is a 'logical next step' or a cleanup from a previous session.

**Plan format (T1.11 / CD.22):** plans are `docs/plans/PLAN-{slug}.yaml`, schema-validated by `scripts/plan_document.py` (resolve via `scripts/find_plan.py`). If handed a legacy `PLAN-{slug}.md` path, emit a deprecation warning in the session output and proceed -- the .md path survives one release cycle, then is removed. Never author new .md plans.

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
- **`ops_outbox` non-empty** -- Entries in migrated-table or `*_pending` dirs are ANOMALIES (Decision 84 I-4: those outboxes are retired and never drained) -- re-file the content via the portal and delete the files. Legacy staging dirs (telemetry/session_log/execution_plans) drain via `bin/venv-python -m scripts.sync_ops sync`. If that fails, STOP.
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
- Decision 86 routing rule -- no new standing prose-architecture docs under docs/:
  route forward intent to tier_items, rationale to Decisions, field semantics to contracts.
  Creating a new docs/INTENT-*.md or any equivalent standing prose-architecture doc is
  forbidden. The validate.py intent-doc-freeze guard enforces this on-disk.
  Existing INTENT docs are grandfathered via docs/intent-migration/MANIFEST.yaml and
  retire as extraction waves complete.

## Main Divergence Check (Workflow Step 2 -- after plan load)
Once the PLAN-{slug}.yaml `scope` list is parsed, intersect the scope file paths with `main_freshness.main_files_changed_since_branch` from the preflight report. If any scope file overlaps:

> "Main has changed [list of overlapping files] since this branch diverged, and your plan modifies the same file(s). Implementing without rebasing will produce a merge conflict at PR time after the work is already done -- and may invalidate the verification plan if the file's shape has changed. Recommend rebasing now: `git fetch origin main && git rebase origin/main` (resolve conflicts then re-run `/implement`). Options: (1) rebase now and re-enter `/implement`, (2) proceed anyway, (3) abort."

STOP and wait. Do not auto-rebase. If the human chooses (2), proceed with a logged note in chat output: "Proceeding without rebase despite Scope/main overlap on: [files]."

If `main_freshness.status != "ok"`, this check cannot run -- surface the fetch failure to the human and continue.

## Live Verification Protocol (Workflow Step 4 -- MANDATORY)
After all code changes are complete and unit tests pass, the implementing agent MUST execute the Verification Plan from the PLAN-{slug}.yaml file before proceeding to code review.

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
- Identify the plan file (`docs/plans/PLAN-{slug}.yaml`) so the subagent knows the acceptance criteria and intent.
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

### Decomposition-hint exemption inheritance (T-1.12 subset g)

A STRATEGIC parent tier_item that was split into atomic IMPLEMENTATION plans under the freeze
override (AGENTS.md Temporary Operational Constraints / CD.17; the T2.19 pattern) carries a
`decomposition_hints` block naming its children:
```yaml
decomposition_hints:
  split_by: <subsystem|per_lambda|phase|...>
  atomic_plans:
    - "PLAN-<child-slug> -- <description> (subset <x>)"
  rationale: |
    ...
```
When the bookkeeping walk files a status outcome for the current plan, resolve the plan's
effective `bootstrap_completion_exempt` by INHERITANCE from its parent -- do NOT read it from
the child's own (often absent) flag:

1. **Find the parent.** Scan `docs/ROADMAP-PLATFORM.yaml` `tier_items[]` for an item whose
   `decomposition_hints.atomic_plans[]` names the current plan. Match on the `PLAN-{slug}` token
   at the head of each entry (`entry.strip().split()[0] == "PLAN-{slug}"`). Some parents enumerate
   their children as prose descriptions rather than `PLAN-{slug}` tokens (e.g. T1.12's
   "Ratify lambda-*.yaml" entries, T1.6's phase descriptions); when no head-token match exists,
   map the current plan to its parent via the plan's Phase field / the decomposition rationale.
2. **Inherit the flag.** The child's effective exemption is the PARENT's live
   `bootstrap_completion_exempt` value. The per-item flag is the single source of truth -- the
   document-level "Bootstrap clause (COMPLETION exemption)" prose enumeration is documentation
   only. A child of an exempt parent (`true`) MAY stage `status: complete` on its slice even while
   the parent's gating CD is still `state: pending`; a child of a non-exempt parent (`false`)
   follows the normal flow and stays gated on CD ratification. Canonical examples: T-1.12 is
   `bootstrap_completion_exempt: true`, so its subset children inherit `true` (they may complete
   ahead of CD.25); T1.12 is `false`, so its per-Lambda children inherit `false` and ratify
   post-CD.16 under the normal flow.
3. **Read-only resolution.** Inheritance never writes the parent's `decomposition_hints` or the
   child's flag during bookkeeping -- it is read-only resolution at filing time. Record the
   inheritance in the bookkeeping output (e.g. "PLAN-<child-slug> inherits
   bootstrap_completion_exempt=true from parent T-1.12"). This is not a license to author STRATEGIC
   children: the freeze stays in force and atomic children remain IMPLEMENTATION plans.

**Self-application invariant (T-1.12 subset g):** `PLAN-implement-skill-decomposition-hints` is
itself an atomic child named in T-1.12's `decomposition_hints.atomic_plans`. The first `/implement`
run using this rule SHOULD therefore resolve this plan's exemption as inherited `true` from parent
T-1.12 and, subset (g) being T-1.12's last open exit criterion, stage `T-1.12 -> status: complete`
in the same bookkeeping pass. If the rule works, T-1.12 self-flips; if it does not, T-1.12 stays
`in_progress` and the discrepancy is observable (mirrors the T-1.10 self-application invariant below).

### Replacement closure check (cutover / supersession items)
Runs during the same bookkeeping walk for any checked tier_item whose name or intent implies a
replacement: cutover, migration, backend swap, retirement, supersession, "replaces X". A
replacement is CLOSED only when the old path is dead -- "new path works" is not closure
(2026-06-09 roadmap audit, dimension D11). Before staging `complete` on such an item:

1. **Name the replaced surface.** From the item text and the plan, identify the old path
   explicitly (file, Lambda, view, write path, profile, config flag). If neither the item
   nor the plan names it, derive it from the diff (what does the new code stop calling /
   start replacing?); if no old surface is derivable, record "no replaced surface
   identified -- closure check N/A" in the bookkeeping output rather than guessing.
   This check is per-touched-item: it closes the replacement THIS plan performed, not a
   repo-wide retirement sweep.
2. **Verify the old path is dead or designed-rollback-only.** Run the greps/commands that prove
   the old surface is deleted, fails closed, or is reachable ONLY behind the documented rollback
   flag. An unconditional fallback to the old backend (e.g. an Athena fallback on a table cut
   over to the DuckLake closed boundary) is a FAIL: do not count the cutover criterion as
   passing; surface the fallback as a finding and add its closure to the plan or stage a
   criterion for it on the open item.
3. **Verify a named owner for any surviving old path.** Partial cutovers are legitimate ONLY
   while a tier_item (or an explicit exit criterion elsewhere) owns the survivor's retirement.
   If none exists, stage one in the same YAML edit (a new criterion on the open item, or
   surface to the human that a successor item is needed). Deferred work with no carrier is
   invisible to eligibility computation and rots (audit finding F-018).
4. **Close out superseded predecessors.** If the completed work absorbs an older tier_item's
   scope, reconcile that older item in the same staged edit: `status: reserved` with a
   supersession note (preserving the id, per the T1.8 precedent), or re-home its still-live
   criteria onto the owning item. Never leave two items claiming the same future work.

### Exit-criteria truth maintenance (realized-differently rule)
When the session satisfied an item's INTENT via a different mechanism than its written exit
criteria describe (different filename, different substrate, a criterion superseded by a
ratified decision), do NOT flip the item complete over criteria that no longer adjudicate
true -- and do NOT leave the criteria stale with the truth buried in a note. In the same
staged YAML edit, rewrite the affected criteria to the realized mechanism (preserve the
original wording inside the item's note when the history matters) so the item re-adjudicates
true against the repo today. A `complete` item whose criteria cannot be re-run is an audit
finding (2026-06-09 audit, F-006/F-014), not a convenience. This rule applies the same way
when the bookkeeping walk runs against items completed in EARLIER sessions: discovering a
criteria-vs-reality mismatch on an already-complete item stages a criteria rewrite, never a
silent pass.

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
**Once validation passes (Step 6), execute the appropriate commit flow autonomously. Do not stop to ask permission -- the plan was approved during /plan.**

This workflow runs on Claude Code on the web: the harness assigned this session its own branch (e.g. `claude/...`), the `gh` CLI is NOT available, and the container hibernates between turns. All GitHub operations use the GitHub MCP tools (`mcp__github__*`). Squash-merge after CI passes is preserved policy (Decision 89 "Branch Protection Not Available", clause 4); the transport is now the GitHub MCP `merge_pull_request` tool (Decision 76).

### Run the full gate locally first
The PR gate runs ONLY the fast `--pre` tier; the full tier runs post-merge on main and a failure there spawns a ci-rca rec. To avoid a post-merge red main, run `bin/venv-python -m scripts.validate` (full, no flags) locally and get exit 0 BEFORE opening the PR.

### Wait-for-CI: event-driven, never polled
The PR-tier CI is the fast `--pre` tier (ruff/mypy/pytest-picked/prompt checks + terraform validate, ~1-3 min; Decision 73). Wait for it via subscription, NOT polling:
1. `mcp__github__subscribe_pr_activity(owner, repo, pullNumber)`.
2. **End your turn.** Do NOT busy-wait: no background sleep timer, no recurring scheduled re-check, no manual status polling -- the harness forbids busy-waiting on external events and a timer keeps the container awake for nothing. CI completion arrives as a `<github-webhook-activity>` event that WAKES this session.
3. On wake, confirm status (`mcp__github__pull_request_read` with `method=get_status`/`get_check_runs`):
   - **All green** -> `mcp__github__merge_pull_request(owner, repo, pullNumber, merge_method="squash")`, then `mcp__github__unsubscribe_pr_activity(...)`. Report the merge. **Carve-out:** for a PR touching `terraform/personal/**`, do NOT unsubscribe here -- defer to the "Hold subscription through apply" section below (the real outcome is the post-merge apply, not the merge).
   - **Any red** -> diagnose, fix on this branch, commit, push (re-triggers PR CI). Stay subscribed and end the turn. Do NOT inline-patch around a structural failure (Decision 55); if it is a recurring gap, run RCA (Step 8).
   - **Still running** -> end the turn; a later event wakes you.

The slow full tier runs post-merge on `main` (Decision 73); on failure the ci-rca agent files a `priority=critical`, `source=ci_rca` rec that hard-blocks the next planning session. You do not babysit main CI.

Robustness note: a genuinely lost webhook leaves the PR open (safe). The bulletproof upgrade is GitHub-native auto-merge (server-side merge on green, container fully out of the loop); branch protection + required status checks are now LIVE (Decision 83 / T2.12, applied 2026-06-08), so auto-merge is unblocked -- adopt via a small follow-up plan if desired. See Decision 76.

### Hold subscription through apply (terraform/personal PRs -- CD.35 / T2.20)
For a PR that touches `terraform/personal/**`, the sandbox CD apply runs **post-merge** on `main`
(`terraform-apply-sandbox.yml`), and that apply -- not the merge -- is the real outcome (it writes the
convergence record green/red). After the squash-merge, **do not unsubscribe**: hold the PR subscription so
the apply job's best-effort post-merge SHA->PR wake (it resolves the PR from the merge commit SHA, since
`workflow_run.pull_requests[]` is empty for push) can re-engage this session. The wake is best-effort and
likely fights the `subscribe_pr_activity` contract (unsubscribe-at-merge, open-PR-scoped); **the
authoritative baseline is the next planning session's convergence-record re-check** -- poll-free, never a
`sleep`/`/loop` (Decision 76). If the apply reds the record, `ci-rca` files a `source=ci_rca` rec; clear red
only via the `workflow_dispatch` acknowledge-and-retry path (naming the red commit/rec) after the rec is
reviewed -- never an inline workaround (Decision 55). Unsubscribe once the record is green (apply converged)
or the next planning session has assumed the baseline.

**Fail-closed set (IAM/trust/destroy diffs -- CD.35 Wave 3 / T2.22):** if the change hits the guard's
fail-closed set (guard exits 2), the post-merge path routes to the `gated-apply` job rather than auto-applying.
The job declares `environment: tf-gated-apply` and **blocks until benjamin-blake approves in GitHub Actions**
(Actions tab -> select the run -> Review pending deployments -> Approve). This is NOT a PR required status
check -- the PR merges normally; the gated apply is a separate post-merge job. After approval, the gated-apply
job applies the same saved plan.bin and writes the convergence record. The authoritative baseline is still
the next planning session's convergence-record re-check (not the wake). The gated apply gates the JOB, never
from a laptop.

### Pre-Push Rebase (applies to both flows)
After the local commit, before pushing, refresh and rebase so the PR opens against current main:
```bash
git fetch origin main
git rebase origin/main   # STOP on conflict; do not auto-resolve -- surface to the human
```
If the branch was pushed earlier in the session, the post-rebase push uses `--force-with-lease` (never `--force`).

### IMPLEMENTATION Commit Flow
```bash
git add -A
git commit -m "feat({slug}): implement {brief-description}"
git fetch origin main
git rebase origin/main   # STOP on conflict
git push -u origin HEAD   # this session's harness branch
```
Then via GitHub MCP (owner/repo from `git remote get-url origin`):
1. Build the PR body. If the plan has a non-empty `bundled_recommendations` list, append a `Resolves:` trailer to the body:
   ```
   Implemented by /implement. Verification plan passed.

   Resolves: rec-NNNN, rec-MMMM
   ```
   This triggers the `rec-autoclose` workflow to close each named rec after the squash-merge lands on main. If `bundled_recommendations` is empty, omit the trailer.
2. `mcp__github__create_pull_request(owner, repo, head=<this branch>, base="main", title="feat({slug}): {brief-description}", body=<body from step 1>)`
3. `mcp__github__subscribe_pr_activity(...)`; end the turn (see "Wait-for-CI").
4. On green wake: `mcp__github__merge_pull_request(..., merge_method="squash")` + `mcp__github__unsubscribe_pr_activity(...)`.
5. **Post-merge closeout fallback**: after the merge, verify that the `rec-autoclose` workflow closed each bundled rec (check via `bin/venv-python -m scripts.ops_data_portal --sync` then `grep rec-NNNN logs/.recommendations-log.jsonl`). If a rec is still open after ~5 min, close it directly: `bin/venv-python -m scripts.ops_data_portal --update-rec rec-NNNN --status closed --resolution "Resolved by merge of {slug} -- autoclose fallback"`.

### STRATEGIC Commit Flow
STRATEGIC plans are suspended (Decision 67). When restored, use the same MCP PR/subscribe/merge pattern, committing `docs/plans/briefings/` with a `scope({slug}): ...` message.
