---
description: Interactive planning session. Run this before any implementation work. Clarifies intent, loads project context, checks phase alignment, and produces PLAN-{slug}.md — a self-contained implementation brief for the next agent chat. Use when starting a new feature, fix, or any code change.
model: opus[1m]
---

# Plan Workflow

**Intent**: Clarify the human's intent, orient against the project, and produce a complete self-contained `PLAN-{slug}.md` that any agent can execute without further interaction. Does not implement anything.

*Note: For detailed guidelines on complexity, verification tiers, preflight constraints, and the plan template, invoke your `planning` skill via the Skill tool.*

## Step 1: Run Preflight

*Note: This workflow runs on Claude Opus 1M (opus[1m]). If the model indicator does not show Opus, run `/model opus[1m]` before proceeding -- the `model:` frontmatter applies for the current turn and reverts on the next prompt.*

```bash
bin/venv-python -m scripts.session_preflight
```

The script emits only a one-line summary to stdout (the full report would cost ~12-15k tokens per session for a payload that's already on disk). The full report is at `logs/.preflight-report.json`. Read that file with the `Read` tool to get the constraint-evaluation surface.

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

Also surface `preflight.platform_roadmap.next_eligible` and `preflight.platform_roadmap.strategic_pending` to the human so the eligibility surface is visible without manually grepping the YAML. Apply the **Platform Roadmap Eligibility** rules from your `planning` skill to print the summary line and handle soft-warn exception categories.

## Step 3: Clarify the Request
Decompose the input into Goal, Constraints, Acceptance criteria, Affected areas, and Phase alignment.
If vague, ask 2-5 questions. Watch for ROADMAP misalignment (the platform/product roadmap state is already in the preflight JSON `next_eligible` / `strategic_pending` fields). Decision-contradiction checking is delegated to the `decision-scout` subagent gate in Step 6 -- do NOT read `docs/DECISIONS.md` from the planning agent to look for contradictions, that's a 25k-token cost the subagent avoids.
Suggest 3-5 open recommendations from `logs/.recommendations-log.jsonl` that align with the current task.

## Step 4: Identify Affected Files
1. Use the File Router to locate source files.
2. Read those files and check `tests/` for existing test coverage.
3. Conduct an Infrastructure Assessment if `.tf` files are in scope.
4. Conduct a Lambda Deployment Assessment if Lambda-packaged files are in scope.
5. Conduct a Complexity Assessment to determine if this is STRATEGIC or IMPLEMENTATION.
*(Apply the exact assessment rules from your `planning` skill).*

## Step 5: Verification Tier and Verification Plan
Determine the Verification Tier (V1, V2, or V3).
Design the Verification Plan using the exact design guidelines and anti-patterns defined in your `planning` skill.
**Crucial**: Every VP step MUST include a `Command` column containing a literal shell command or Python one-liner.

## Step 6: Present Findings and Confirm

### Step 6a: Decision Scout Gate (MANDATORY, before presentation)
**DO NOT present findings to the human until this gate completes.** Launch a zero-context Claude subagent via the `Agent` tool to run the `decision-scout` skill. The fresh context is the point: it lets the subagent read the full 25k-token `docs/DECISIONS.md` without that cost ever entering the planning agent's context.

Substitute the synthesis you produced in Steps 3-5 into the prompt. Invoke with:
- `subagent_type: "general-purpose"`
- `description: "Decision scout gate"`
- `prompt:` a self-contained brief that supplies (a) Intent (1-2 sentences from Step 3), (b) Proposed approach (paragraph from Steps 3-5 synthesis), (c) Scope file list (from Step 4), (d) Verification Tier (from Step 5), (e) any decision IDs already cited by the human, and (f) instruction to invoke the `decision-scout` skill via the `Skill` tool and return its structured output verbatim.

Example prompt body:
> "You are running the decision-scout gate in a fresh context window. Invoke the `decision-scout` skill via the Skill tool. The skill needs the following inputs (use them in your scout analysis):
> - Intent: [1-2 sentences from clarification]
> - Proposed approach: [paragraph synthesis]
> - Scope files: [list from Step 4]
> - Verification Tier: [V1 | V2 | V3]
> - Explicitly cited decisions: [list of IDs the human mentioned, or 'none']
>
> Return the skill's `## Decision Scout Report` output verbatim, including the final `Verdict:` line. Do not edit any files."

Read the report returned by the subagent. Handle per Verdict:
- **NO_FLAGS** -- proceed to Step 6b. Include the CITE list in the presentation as "Decisions this plan must reference: ...".
- **FLAGS_FOUND** -- surface each WARN/NOTE flag to the human in the Step 6b presentation under a new "Decision Flags" section. The human decides per-flag: pivot, defer with note, or accept.
- **BLOCK** -- STOP. Surface the BLOCK contradiction to the human and propose pivots. Do NOT present the original approach for confirmation; that would invite the human to confirm a proposal you already know contradicts an active decision. After pivoting, re-dispatch this gate against the revised approach.

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


## Step 8: Write PLAN-{slug}.md (and any REPORT-ONLY deliverable)
Write the file `docs/plans/PLAN-{slug}.md` using the exact structure and template provided in your `planning` skill.

**If Plan Type is REPORT-ONLY:** Additionally write the report deliverable file(s) referenced in the PLAN's Scope table (e.g. `docs/INTENT-{slug}.md`, `docs/REPORT-{slug}.md`). The deliverable IS the substantive output of a REPORT-ONLY plan; the PLAN file itself is just the planning artefact that points at it. Both files land in the same initial commit.

After writing, commit to the branch:
```bash
git add docs/plans/PLAN-{slug}.md   # plus any REPORT-ONLY deliverable file(s)
git commit -m "plan({slug}): initial plan"
```

## Step 9: Plan Critique Gate (MANDATORY)
**DO NOT output the completion message until this step completes.**
Launch a zero-context Claude subagent via the `Agent` tool to run the `plan-critique` skill in a fresh context window. The fresh context IS the point of this gate -- it eliminates cognitive bias from the planning agent. Do NOT invoke the `plan-critique` skill in the current session via the `Skill` tool, and do NOT shell out to `run_skill.py` (the legacy gemini-CLI dispatcher is removed).

Substitute `{slug}` with the actual branch slug (e.g. `bootstrap-speedup`). Invoke with:
- `subagent_type: "general-purpose"`
- `description: "Plan critique gate"`
- `prompt:` a self-contained brief that (a) names the target plan absolute path, (b) instructs the subagent to invoke the `plan-critique` skill via the `Skill` tool against that path, (c) lists the required-context files (`docs/PROJECT_CONTEXT.md`, `docs/ROADMAP-PRODUCT.yaml`, `docs/ROADMAP-PLATFORM.yaml`, `docs/DECISIONS.md`), (d) requires the subagent to read every file in the plan's Scope table for IMPLEMENTATION plans, (e) requires the subagent to return the skill's structured output verbatim including the final `Recommendation: PROCEED / REVISE` line, and (f) forbids the subagent from editing any files.

Example prompt body (adapt the path):
> "You are running the plan-critique gate. **First, run `git fetch origin main --quiet`** so the local `origin/main` ref is current -- the branch may have been open long enough for main to have moved. Then invoke the `plan-critique` skill via the Skill tool to critique `/home/user/agent-platform/docs/plans/PLAN-{slug}.md`. Read the skill's required-context files (`docs/PROJECT_CONTEXT.md`, `docs/ROADMAP-PRODUCT.yaml`, `docs/ROADMAP-PLATFORM.yaml`, `docs/DECISIONS.md`). For IMPLEMENTATION plans, also read every file in the plan's Scope table. If `git diff origin/main -- docs/DECISIONS.md docs/ROADMAP-PLATFORM.yaml` shows differences, note in your critique that the working-tree versions used for evaluation may lag main. Return the skill's structured critique output verbatim, including the final `Recommendation:` verdict. Do not edit any files."

Read the critique output returned by the subagent.
If it suggests revisions, update the plan with these fixes and re-launch the same subagent invocation against the revised plan.
Loop if REVISE. Proceed if PROCEED.

Note: this gate reviews the PLAN artefact, not the report deliverable. For REPORT-ONLY plans, the deliverable gets its own critique in Step 10.

## Step 10: Multi-Perspective Report Critique Gate (REPORT-ONLY only, MANDATORY)
**If Plan Type is IMPLEMENTATION or STRATEGIC, SKIP this step entirely and proceed to Step 11.**

For REPORT-ONLY plans, the Step 9 plan-critique gate reviewed the planning artefact (PLAN-{slug}.md) but NOT the report deliverable itself. The deliverable carries its own correctness burden -- design soundness, internal consistency, alignment with live repo state, blast radius of any proposed changes -- and needs independent zero-context critique.

Apply the **Report Critique Gate** methodology from your `planning` skill. Summary: launch AT LEAST 2 zero-context subagents IN PARALLEL via the `Agent` tool, each with a distinct perspective on the deliverable (architect/risk/etc.), synthesize their findings, present to the human, iterate based on human direction, re-launch critiques after each revision until convergence.

Convergence rule: both agents return PROCEED on a fresh round, OR the human explicitly accepts the current state with a defined deferral (e.g. "fix the HIGH-severity items and defer the rest to phase plans"). Each material revision lands as its own commit on the branch during the loop.

## Step 11: Commit approved PLAN-{slug}.md and merge to main
After all critique gates have approved the work, commit any uncommitted changes to the branch:
```bash
git add docs/plans/PLAN-{slug}.md   # plus any REPORT-ONLY deliverable file(s)
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
Output the final confirmation message based on Plan Type (IMPLEMENTATION / STRATEGIC / REPORT-ONLY) exactly as specified in your `planning` skill. The handoff message must name the explicit plan path so the human can paste it directly:

```
Planning complete. The plan is merged to main at docs/plans/PLAN-{slug}.md.
To implement, open a NEW Claude Code session and paste:

    /implement docs/plans/PLAN-{slug}.md

Summary: {one line on what the plan does}.
```

Finally, close the telemetry session:
```bash
bin/venv-python -m scripts.session_postflight --close-session --outcome success
```
If the session was abandoned or the plan was not written, use `--outcome cancelled` instead.

STOP! The planning agent's mission is now complete. Perform no further actions.
