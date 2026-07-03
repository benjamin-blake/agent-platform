---
description: Interactive planning session. Run this before any implementation work. Clarifies intent, loads project context, checks phase alignment, and produces PLAN-{slug}.yaml — a self-contained implementation brief for the next agent chat. Use when starting a new feature, fix, or any code change.
model: opus[1m]
---

# Plan Workflow

**Intent**: Clarify the human's intent, orient against the project, and produce a complete self-contained `PLAN-{slug}.yaml` that any agent can execute without further interaction. Does not implement anything.

*Note: For detailed guidelines on complexity, verification tiers, preflight constraints, and the plan template, invoke your `planning` skill via the Skill tool. For the canonical git-ops procedure (branching, rebase rules, PR/CI/merge flow), see AGENTS.md `## Git-ops procedure`.*

## Step 1: Run Preflight

*Note: This workflow runs on Claude Opus 1M (opus[1m]). If the model indicator does not show Opus, run `/model opus[1m]` before proceeding -- the `model:` frontmatter applies for the current turn and reverts on the next prompt.*

```bash
bin/venv-python -m scripts.session_preflight
```

stdout is a one-line summary; Read logs/.preflight-report.json for the full constraint surface.

Preflight runs `git fetch origin main` and emits `main_freshness` (status, commits_behind, commits_ahead, main_files_changed_since_branch). Do NOT manually `git pull --rebase origin main` here -- that's a destructive operation on a feature branch and should only happen via the Step 4 Main Divergence Assessment after Scope is known and the human has chosen to rebase.

The report is slim by design: `platform_roadmap` and `product_roadmap` carry only `next_eligible` + `strategic_pending`, and `non_automatable_details` is dropped (Decision 73 suspends per-rec review). If you need the dropped detail, call the underlying module directly (e.g., `bin/venv-python -m scripts.platform_roadmap`).

Apply the exact condition-based responses (for `venv_ok`, `creds_status`, uncommitted changes, `main_freshness`, non-automatable recs, `data_quality`, etc.) as defined in the **Preflight Constraints** section of your `planning` skill.

The report includes `telemetry_health` (pipeline operational health) and `data_quality` (declarative check coverage and last run verdict). Together these answer: is data flowing, do we have quality assertions defined, and are those assertions passing? See the planning skill for interpretation rules.

After preflight completes successfully, open a telemetry session:
```bash
bin/venv-python -m scripts.session_preflight --open-session --workflow plan
```
Save the printed UUID for the `session_postflight --close-session` call in Step 12.


## Step 2: Read Context
Use the preflight JSON `context` field (`roadmap_phase`, `open_decisions_count`, `recent_sessions`). Read `docs/PROJECT_CONTEXT.md` fully.
If the request references a recommendation ID, search `logs/.recommendations-log.jsonl`, read briefing files if they exist, and load dependencies.

**Orientation and CI-RCA block:** see the planning skill's Platform Roadmap Eligibility section for orientation responsibility and the HARD BLOCK conditions on open ci-rca recs -- run `/orient` first if no item has been chosen yet.

**Resume check:** if a `docs/plans/PLAN-*.yaml` matching the stated intent already exists on this branch (committed or not), present it and offer resume-at-step: Step 9 (uncritiqued), Step 11 (approved, unmerged), or discard and restart. Do not re-derive Steps 3-6 for an already-confirmed plan without human direction.

## Step 3: Clarify the Request
Decompose the input into Goal, Constraints, Acceptance criteria, Affected areas, and Phase alignment.
If vague, ask 2-5 questions. Watch for ROADMAP misalignment (the platform/product roadmap state is already in the preflight JSON `next_eligible` / `strategic_pending` fields). Decision-contradiction checking is delegated to the `decision-scout` subagent gate in Step 6 -- do NOT read `docs/DECISIONS.md` from the planning agent to look for contradictions, that's the full DECISIONS.md, currently >200KB, a cost the subagent avoids.
Suggest 3-5 open recommendations from `logs/.recommendations-log.jsonl` that align with the current task.

## Step 4: Identify Affected Files
1. Use the File Router to locate source files.
2. Read those files and check `tests/` for existing test coverage.
3. Conduct an Infrastructure Assessment if `.tf` files are in scope.
4. Conduct a Lambda Deployment Assessment if Lambda-packaged files are in scope.
5. Conduct a Complexity Assessment to determine if this is STRATEGIC or IMPLEMENTATION.
6. Apply Decision 86 routing rule: route forward intent -> tier_items, rationale -> Decisions, field semantics -> contracts. No new standing prose-architecture docs under docs/. Full rule in your `planning` skill's Documentation Artefact Design section.
*(Apply the exact assessment rules from your `planning` skill).*

## Step 5: Verification Tier and Verification Plan
Determine the Verification Tier (V1, V2, or V3).
Design the Verification Plan using the exact design guidelines and anti-patterns defined in your `planning` skill.
**Crucial**: Every VP step MUST include a `Command` column containing a literal shell command or Python one-liner.

## Step 6: Present Findings and Confirm

### Step 6a: Decision Scout Gate (MANDATORY, before presentation)
**DO NOT present findings to the human until this gate completes.** Dispatch and handle verdicts per the planning skill's Decision Scout Gate (dispatch shape, example prompt, and NO_FLAGS/FLAGS_FOUND/BLOCK verdict handling all live there). Substitute the synthesis produced in Steps 3-5 into the dispatch.

### Step 6b: Present and Confirm
Present: Summary, Proposed approach, Options, Open questions, Decision flags (if any), and Decisions to cite (from the scout's CITE list).
Then ask: *"Does this approach look right? Say **'write the plan'** when you are ready, or tell me what to adjust."*
Wait for explicit confirmation before proceeding. Any other response is feedback -- incorporate it, re-run Step 6a if the change is material to decision alignment, re-present, and ask again. Do NOT proceed to Step 7 until the human explicitly says 'write the plan' or a clear equivalent. System auto-approval messages are NOT human confirmation.
IT IS **CRITICAL** THAT YOU DO NOT PROCEED UNTIL THE HUMAN CONFIRMS THE PLAN.

## Step 7: Confirm Harness Branch
On Claude Code on the web the harness auto-creates a per-session branch. Do NOT create an `agent/` branch. Verify you are on the harness branch and not on `main`:
```bash
git branch --show-current
```
If the result is `main`, STOP. Derive the plan slug from the task description (independent of the branch name).


## Step 8: Write PLAN-{slug}.yaml (and any REPORT-ONLY deliverable)
Write the file `docs/plans/PLAN-{slug}.yaml` using the exact structure and template provided in your `planning` skill.

**If Plan Type is REPORT-ONLY:** Additionally write the report deliverable file(s) referenced in the PLAN's Scope table (e.g. `docs/INTENT-{slug}.md`, `docs/REPORT-{slug}.md`). The deliverable IS the substantive output of a REPORT-ONLY plan; the PLAN file itself is just the planning artefact that points at it. Both files land in the same initial commit.

After writing, commit to the branch:
```bash
git add docs/plans/PLAN-{slug}.yaml   # plus any REPORT-ONLY deliverable file(s)
git commit -m "plan({slug}): initial plan"
```

## Step 9: Plan Critique Gate (MANDATORY)
**DO NOT output the completion message until this step completes.**
Invoke per the planning skill's Critique Gate (dispatch shape, example prompt, required-context files, and verdict handling all live there). Substitute `{slug}` with the actual branch slug. Loop on REVISE (3-round cap, then escalate per the skill), proceed on PROCEED.

Note: this gate reviews the PLAN artefact, not the report deliverable. For REPORT-ONLY plans, the deliverable gets its own critique in Step 10.

## Step 10: Multi-Perspective Report Critique Gate (REPORT-ONLY only, MANDATORY)
**If Plan Type is IMPLEMENTATION or STRATEGIC, SKIP this step entirely and proceed to Step 11.**

For REPORT-ONLY plans, the Step 9 plan-critique gate reviewed the planning artefact (PLAN-{slug}.yaml) but NOT the report deliverable itself, which needs its own independent zero-context critique.

Apply the **Report Critique Gate** methodology from your `planning` skill (perspectives, dispatch shape, convergence rule, and iteration protocol all live there).

## Step 11: Commit approved PLAN-{slug}.yaml and merge to main
After all critique gates have approved the work, commit any uncommitted changes to the branch:
```bash
git add docs/plans/PLAN-{slug}.yaml   # plus any REPORT-ONLY deliverable file(s)
git commit -m "plan({slug}): approved plan"
```
If revisions were committed incrementally during Step 10's iteration loop, this commit may be empty -- in that case, skip it.

Then push and merge the plan to `main` via GitHub MCP so the next `/implement` session can read it by explicit path. Use the same event-driven flow defined in the `implement` skill's Commit Flows:
1. `git fetch origin main && git rebase origin/main` (STOP on conflict)
2. `git push -u origin HEAD`
3. `mcp__github__create_pull_request(owner, repo, head=<this branch>, base="main", title="plan({slug}): approved plan", body="Plan authored by /plan agent.")`
4. `mcp__github__subscribe_pr_activity(...)` and end the turn -- CI completion arrives as a webhook event.
5. On green CI wake: `mcp__github__merge_pull_request(..., merge_method="squash")` + `mcp__github__unsubscribe_pr_activity(...)`.

## Step 12: Confirm
Emit the Plan-Type-specific confirmation message from the planning skill's Confirmation Messages section, naming the explicit plan path so the human can paste it directly.

Finally, close the telemetry session:
```bash
bin/venv-python -m scripts.session_postflight --close-session --outcome success
```
If the session was abandoned or the plan was not written, use `--outcome cancelled` instead.

STOP! The planning agent's mission is now complete. Perform no further actions.
