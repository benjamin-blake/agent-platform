---
description: Implements IMPLEMENTATION plans directly or scopes STRATEGIC plans into atomic recommendations for the executor. Run after /plan.
argument-hint: [docs/plans/PLAN-slug.yaml]
---

# Implement Workflow

**Intent**: For IMPLEMENTATION plans: execute the Ordered Execution Steps directly. For STRATEGIC plans: research Work Areas and produce atomic, automatable recommendations for the executor.

*Note: For detailed guidelines on how to execute each step below, invoke your `implement` skill via the Skill tool. For the canonical git-ops procedure (branching, rebase rules, PR/CI/merge flow), see AGENTS.md `## Git-ops procedure`.*

## Step 1: Run Preflight
```bash
bin/venv-python -m scripts.session_preflight
```
stdout is a one-line summary; Read logs/.preflight-report.json for the full constraint surface.

Preflight runs `git fetch origin main` and emits `main_freshness` (status, commits_behind, commits_ahead, main_files_changed_since_branch). The report is slim: roadmap state carries only `next_eligible` + `strategic_pending`; `non_automatable_details` is dropped (Decision 73). Handle constraints (including the `main_freshness` cases) as defined in the **Preflight Constraints** section of your `implement` skill. After Step 2 loads the plan, apply the **Main Divergence Check** from the skill before proceeding to Step 3.

After preflight completes successfully, open a telemetry session:
```bash
bin/venv-python -m scripts.session_preflight --open-session --workflow implement
```
Save the printed UUID for the `session_postflight --close-session` call in Step 9.

After the session is open, run the pre-implementation gate (fast `--pre` tier):
```bash
bin/venv-python -m scripts.validate --pre
```
On non-zero exit: parse each failed check from the "Failed checks:" output, file each as a recommendation via `bin/venv-python -m scripts.ops_data_portal --file-rec ...` with `automatable: false`, surface a go/no-go to the human, and STOP if no-go. SSO-related failures: skip with actionable guidance per Decision 57; do not crash. Pattern reference: `ensure_fresh_dq_results()` in `scripts/validate.py`.

## Step 2: Load PLAN File
```bash
git branch --show-current
```
If the result is `main`, STOP.

The plan path is provided as `$ARGUMENTS` from the `/plan` handoff (e.g. `docs/plans/PLAN-web-workflow-migration.yaml`). If an argument was given, resolve it:
```bash
bin/venv-python scripts/find_plan.py <path-from-arguments>
```
If no argument was given, fall back to auto-discovery:
```bash
bin/venv-python scripts/find_plan.py
```
If either command prints `NOT_FOUND`, list `docs/plans/PLAN-*.yaml` and ask the human which plan to implement.

Read the entire plan file. Extract Intent, Plan Type, Verification Tier, Work Areas (STRATEGIC) or Execution Steps (IMPLEMENTATION), Verification Plan, and Constraints.
**If no plan file exists, STOP.**
Also read `docs/PROJECT_CONTEXT.md`. Read only the decisions cited in the plan context (locate each via `rg "^## Decision N:" docs/DECISIONS.md`); do not load the full file.

## Step 3: Dispatch by Plan Type

### For IMPLEMENTATION Plans
1. Count Scope files and estimated steps.
2. Present summary of scope to the human, and explicitly state you are executing autonomously without breaking into recs. Include a fun titbit to confirm understanding.
3. Execute each Ordered Execution Step sequentially.
4. Proceed to Step 4.

### For STRATEGIC Plans
1. Research each Work Area by reading files/modules.
2. Identify dependencies.
3. Break into atomic recs (effort `<= M`).
4. Write full context (executor should not need to read the plan).
5. Define acceptance command and verification steps.
6. Apply the **Quality Gate Validation**, **Dedup Gate**, and **JIT Context Injection** from your `implement` skill.
7. File approved recs using `bin/venv-python -m scripts.ops_data_portal --file-rec ...`. For recs `> M` effort, create `docs/plans/briefings/BRIEFING-rec-NNN.md`.
8. Skip Steps 4-5 and proceed directly to Step 6.

## Step 4: Verification Plan (IMPLEMENTATION only -- MANDATORY)
**You MUST execute this step. Do not skip it.**
Execute the Verification Plan from the PLAN-{slug}.yaml file. Apply the strict **Live Verification Protocol** from your `implement` skill.
Produce the VP Compliance Table. If ANY row is FAIL, fix and re-verify. If BLOCKED, wait for human.

## Step 5: Code Review (IMPLEMENTATION only -- MANDATORY)
**You MUST trigger the code-review immediately after verification passes. Do not wait for the human to ask.** Dispatch per the **Code Review Protocol** in your `implement` skill (fresh-context anti-bias gate; `subagent_type: "general-purpose"` invoking the `code-review` skill via the `Skill` tool).

Read the findings output. You MUST implement fixes for all **Critical** and **High** priority findings before proceeding.
Medium and Low findings should be filed as recommendations using `bin/venv-python -m scripts.ops_data_portal --file-rec ...`.

## Step 6: Final Validation
**You MUST run validation. Do not skip this step.**
```bash
bin/venv-python -m scripts.validate
```
Must exit 0 before continuing. If it fails, fix the issues and re-run.

## Step 7: Commit, PR, and Merge
**You MUST execute the commit flow autonomously once Step 6 passes. Do not stop to ask for permission.**
Apply the appropriate **Commit Flow** (STRATEGIC or IMPLEMENTATION) defined in your `implement` skill. All GitHub operations use the GitHub MCP tools (`mcp__github__*`) -- the `gh` CLI is not available on the web harness. Wait for CI event-driven via `subscribe_pr_activity`; never busy-wait with a sleep timer or a recurring scheduled re-check.

When creating the PR body, emit a `Resolves: rec-NNNN[, rec-MMMM]` trailer if the plan's `bundled_recommendations` list is non-empty. After the merge, execute the **post-merge closeout fallback** from the implement skill (verify `rec-autoclose` closed each rec; close directly if not).

## Step 8: Capture Friction
Record friction (parsing errors, ambiguous areas, bugs found) by filing a recommendation via `bin/venv-python -m scripts.ops_data_portal --file-rec ...` with `source=manual` (the Single Portal Invariant, Decision 84). (The legacy process-event emit to `telemetry_process_events` via the executor telemetry API is suspended until Decision 84 Phase 4 (T2.36) re-lands telemetry on DuckLake.) If no friction, this step is a no-op.

**RCA-First Protocol (Decision 55):**
If the friction was a recurring gap or unrecoverable failure, you MUST invoke the `executor-rca` skill via the `Skill` tool to diagnose the root cause and file a permanent fix. Do NOT silently workaround structural issues.

Friction logs will be committed to the current branch and pushed automatically via the `session_postflight.py` flow during Step 7, or you can flush them manually:
```bash
bin/venv-python -m scripts.session_postflight --log-housekeeping
```

## Step 9: Report and Close Session
Output the final report:
- **STRATEGIC**: Total recs filed, breakdowns, briefing files created, and next step instructions.
- **IMPLEMENTATION**: Files changed, verification results (actual outcomes per step), code review findings fixed, bugs fixed, design decisions.

Finally, close the telemetry session:
```bash
bin/venv-python -m scripts.session_postflight --close-session --outcome success
```
Use `--outcome failure` if the session ended with unresolved errors. Use `--outcome cancelled` if abandoned.
