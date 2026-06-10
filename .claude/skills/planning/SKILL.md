---
name: planning
description: Deep methodology and rules for software planning, complexity assessment, and verification tier design. Use this when running the /plan workflow or when architecting new features.
model: opus[1m]
---

# Planning Methodology & Rules

You are using this skill to augment the `/plan` workflow. Apply these deep instructions when executing the workflow steps. You must NEVER initiate modifications to source code or global instructions (docs/PROJECT_CONTEXT.md, skills) during a planning session. The planning phase ends with the commitment of the PLAN artifact. Implementation only begins after an explicit /implement trigger with ANOTHER agent.

## Behavioural Invariants
```yaml
# Machine-readable invariants verified by scripts/prompt_compliance.py
preflight_run: true                # session_preflight.py must run at Step 1
harness_branch: true               # work on the harness-assigned session branch; do NOT create agent/ branches
decision_scout_gate: true          # @decision-scout must be invoked at Step 6a before presentation
critique_gate: true                # @plan-critique must be invoked before completion
report_critique_gate: report-only  # REPORT-ONLY plans must run Step 10 multi-perspective deliverable critique
never_on_main: true                # no file edits while on main branch
```

## Preflight Constraints (Workflow Step 1)
When reading `logs/.preflight-report.json`, apply these conditionals:
- **`venv_ok: false`** -- Verify `bin/venv-python -c "import sys; print(sys.executable)"` resolves to the venv interpreter and rerun preflight. If still false, STOP.
- **`creds_status: "unavailable"`** -- **Static-key recovery (non-fatal, Decision 60):** the static-key assume-role chain has no interactive login. Verify it with `aws sts get-caller-identity --profile agent_platform`; if the `agent_static` key was rotated, refresh `~/.aws/credentials`. Do NOT block -- continue in degraded mode (credential-dependent verifiers are skipped, emitting SKIPPED). Autonomous executors never attempt recovery.
- **`log_sync_result.status == "committed"`** -- Print: "Session logs synced to main ([N] file(s) committed)." Continue.
- **`log_sync_result.status == "conflict"`** -- STOP. Print error and require human resolution.
- **`uncommitted_changes` non-empty** -- Ask human: "Resume, stash, or discard?". Wait.
- **`main_freshness.status == "fetch_failed"`** -- Informational. Surface: "Could not refresh `origin/main` ([error]). Critique and Scope-overlap checks will use the stale local main ref." Continue.
- **`main_freshness.commits_behind > 20`** -- Surface as planning context warning: "Branch is N commits behind `origin/main`. Plan-critique (Step 9) reads `docs/PROJECT_CONTEXT.md`, `DECISIONS.md`, and `ROADMAP-PLATFORM.yaml` from the working tree; if these have moved on main, the critique evaluates against stale context. Recommend rebasing before continuing." Non-blocking but prompt the human to decide.
- **`main_freshness.commits_behind > 0`** -- Retain `main_freshness.main_files_changed_since_branch` for the Step 4 Main Divergence Assessment. Non-blocking at this step.
- **`cron_review_fresh: false`** -- Note to human (non-blocking).
- **`outbox_synced: false`** -- Run `bin/venv-python -m scripts.sync_ops pull` to drain outbox and sync data (Decision 51). If fails, STOP.
- **`open_recommendations > 0`** -- Surface counts and ask whether to address. Wait.
- **`non_automatable_recommendations > 0`** -- Informational. Surface counts; do not require per-rec discussion. Individual review is suspended per Decision 73 until CD.17 / T4.2 reverses (Decision 67's Lambda-deploy clause was lifted by Decision 79; the STRATEGIC clause survives).
  - If `non_automatable_softcap_breached` is true (count > 250), surface as a planning context note.
- **`friction_patterns` non-empty** -- Surface repeated patterns as planning context.
- **`metrics_anomalies` non-empty** -- Surface anomalies as planning context.
- **`token_anomalies` non-empty** -- Surface as planning context: "Context file token warning: [file list] exceed the 50K token threshold."
- **`data_quality.last_run.verdict == "FAIL"`** -- Surface as planning context: "Data quality checks failing ([N] failures across [tables]). Run `bin/venv-python -m scripts.data_quality_runner` for details." Non-blocking but relevant if the plan touches data pipelines or table schemas.
- **`data_quality.last_run` is null** -- Note: "Data quality checks have never been run. After fixing the pipeline, run `bin/venv-python -m scripts.data_quality_runner` to establish a baseline." Non-blocking.
- **`ci_rca_recs` non-empty** -- **HARD BLOCK**. `/plan` cannot scope unrelated work while any open ci-rca rec exists. Surface the list at the top of the planning context. Proceed only to scope work that satisfies one of the three Related-Work conditions (see Step 8) OR has a logged deferral rationale in the new plan's Context section.
- **`ci_rca_liveness_alert` non-null** -- **HARD ALERT**. Main CI has been red with no corresponding ci-rca rec for >30 minutes. Triage before continuing.
- **`forward_fix_recursion_alert` non-null** -- **HARD ALERT**. Three or more ci-rca recs targeting the same file were filed in the last 24 hours. Triage before continuing.
- **`budget_bypass_alert` non-null** -- **Informational**. Surface the count and recent bypass reasons as planning context: "Fast-tier budget bypassed N times in 7 days." Repeated `--ignore-budget` use indicates fast-tier drift and likely warrants a planning session to revisit the budget or identify which check is slow.

### What Telemetry Health Represents

The preflight `telemetry_health` section reports operational health of the telemetry and ops data pipelines:

1. **Session metrics** (from Athena): session count over 7 days, success rate, and staleness of the latest session. These answer: "Is the system producing telemetry records and are they reaching Athena?"

2. **Data quality coverage** (from `config/agent/data_quality/*.yaml`): how many declarative checks (not_null, unique, accepted_values, relationships, row_count, recency) are defined across how many tables. This answers: "Do we have visibility into data correctness?"

3. **Last DQ run result** (from `logs/debug/dq-latest.json`): the verdict (PASS/FAIL), pass/fail/warn counts, and timestamp of the most recent `bin/venv-python -m scripts.data_quality_runner` execution. This answers: "When we last checked, was the data actually correct?"

Together these form a three-layer health picture:
- **Pipeline health**: Is data flowing? (session count > 0, staleness < 72h)
- **Quality coverage**: Do we have checks defined? (checks_defined > 0)
- **Quality state**: Are the checks passing? (last_run.verdict == PASS)

If pipeline health is critical (no sessions in 7 days), the plan should prioritise pipeline fixes before adding new features. If quality coverage is zero, any plan touching data write paths should include adding YAML checks. If the last DQ run failed, the plan should note which tables are affected.

## Platform Roadmap Eligibility (Workflow Step 2)

Read `preflight.platform_roadmap` from the already-loaded preflight JSON (Step 1 produced it). Surface the following to the planning agent context before any clarification or scoping work begins:

- `next_eligible[]` -- tier_items whose depends_on are all complete and that are eligible to start now. These are the canonical candidates for this planning session.
- `strategic_pending[]` -- tier_items flagged `strategic: true` that are blocked only by the executor freeze (AGENTS.md Temporary Operational Constraints). Surface as context only; do not scope STRATEGIC plans during the freeze.

Print a summary line to the human (non-blocking):
> "Platform roadmap: N eligible items (T-X.Y, ...). N strategic items pending freeze lift."

If `next_eligible` is empty and `strategic_pending` is also empty, note that no roadmap work is currently eligible and proceed with the human's stated intent.

**Soft-warn exception categories:** when the human's stated intent names work that does not resolve to any `tier_items[].id`, do NOT reject the session -- issue a soft warning and proceed. Documented exception categories that bypass tier_item alignment:
- `ci_rca` -- CI failure investigation driven by a ci-rca rec (see preflight `ci_rca_recs`)
- `hotfix` -- production incident or critical bug fix with immediate blast-radius concern
- `security_advisory` -- security vulnerability requiring immediate remediation
- `ad_hoc_rec` -- standalone recommendation from `logs/.recommendations-log.jsonl` not yet promoted to a tier_item
- `user_explicit_out_of_scope` -- human explicitly states the work is outside current tier scope

Reject only when the intent *claims* tier_item alignment (e.g., "implementing T-1.6") but the referenced id does not exist or the item's depends_on are not satisfied.

## Clarification (Workflow Step 3)
Decompose the human's input into structured components:
| Component | Question to answer |
|-----------|-------------------|
| **Goal** | What outcome does the human actually want? (not just what they said) |
| **Constraints** | What explicit limits were stated? (time, scope, technology, cost) |
| **Acceptance criteria** | How will the human know when this is done? |
| **Affected areas** | Which files, modules, or infrastructure will be touched? |
| **Phase alignment** | Does this fall within the current roadmap phase? Does it depend on something not yet built? |

If the request is vague or missing key information, ask between 2 and 5 questions -- ranked by impact, no padding questions. Wait for answers before continuing.

## Tier Item Freshness Gate (Workflow Step 3, fires once intent resolves to tier_items)

The roadmap can lag the repo: items go stale when decisions ratify, surfaces move, or
sibling work absorbs their scope (2026-06-09 roadmap audit, findings F-008/F-013/F-016/F-017).
Before scoping ANY tier_item -- whether picked from `next_eligible` or named by the human --
re-verify it against the repo. Eligibility computation alone is NOT sufficient grounds to
plan an item. Run four checks, cheapest first:

1. **Silent-completion check.** Re-adjudicate the item's `exit_criteria[]` against the repo
   (executable criteria via subprocess; prose criteria with the implement skill's conservative
   bias). If ALL criteria already hold, do NOT plan the item -- propose a status closeout
   instead: stage `status: complete` + `completed_at` + a note citing the evidence, present it
   to the human, and on confirmation land it as a small roadmap-bookkeeping commit. Precedent:
   T-1.9 sat `not_started` after its deliverable (docs/INTENT-session-log-architecture.md) had
   already landed, and a downstream item (T2.15) was citing the deliverable as existing.
2. **Stale-reference check.** Verify every `files_in_scope` path exists or is marked `# new`;
   scan the item's intent/exit_criteria for surfaces or substrates that ratified decisions have
   retired (e.g. the EC2 runner per CD.21/Decision 73, Bedrock per CD.28, SSO per CD.26, direct
   Iceberg/Athena access for tables cut over to the DuckLake closed boundary per CD.31/CD.33/
   Decision 81). A stale reference does not block planning -- but the plan MUST include
   re-grounding the item's text as an explicit Scope row, and the implementation follows the
   CURRENT architecture, never the stale instruction.
3. **Supersession / redundancy check.** Search the roadmap for sibling tier_items or ratified-CD
   amendment notes that have absorbed or superseded the item's scope (`rg` the item's key
   artefacts across `tier_items[]` and `candidate_decisions[]`). Fully absorbed -> propose
   closing the item out (`status: reserved` with a supersession note, preserving the id)
   instead of planning duplicate work. Partial overlap -> the plan names the boundary
   explicitly and cross-references the sibling.
4. **Gating-decision and gate-rule check.** Read the item's `related_candidate_decisions` and
   any `decision_required_before`; check each referenced CD's `state` in the roadmap. If a
   gating CD is pending, surface it: starting is allowed (bootstrap allowance) but COMPLETION
   is gated, and ratification currently transits the ops portal (see the roadmap
   agent_instructions "ratification vehicle" note). Also grep `cross_tier_gates[]` for rules
   naming the item or its tier and adjudicate them by hand (e.g. a grace_period_elapsed window
   that has not elapsed makes an eligible-by-deps item not actually startable -- T5.2/G.10 is
   the canonical case). This manual check stands in for the blocked-on-CD and gate-evaluation
   preflight surfacing until T-1.20 lands.

Output discipline: every closeout or re-grounding this gate proposes is staged as a roadmap
edit in the plan's Scope table (or its own micro-commit on human confirmation) -- never
applied silently, never dropped silently. If the gate finds nothing, say so in one line and
continue. Closeouts replace dead work; they do not become an excuse to skip the human
confirmation gate (Step 6b).

## Suggest Aligned Recommendations
Search `logs/.recommendations-log.jsonl` for open recommendations that align with the current task (ensure cache is fresh via `bin/venv-python -m scripts.sync_ops pull` during preflight):
1. Extract keywords from the task description (file paths, module names, concepts)
2. Match against `title`, `file`, and `context` fields of open recommendations
3. Present top 3-5 matches (if any):
> "These open recommendations may align with your task:
> - **rec-XXX**: [title] (effort: [effort], priority: [priority])
>
> Want to bundle any into this session? Say 'include rec-XXX' or 'skip'."

## Documentation Artefact Design

This repository is agent-first. When a plan creates or modifies documentation artefacts,
apply these rules:

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

## Infrastructure & Lambda Assessment (Workflow Step 4)
**Infrastructure:** If `.tf` files are in scope, add an "Infrastructure Dependencies table" to the plan. Lambda handlers must accept a `force_{param}` event field. Pre-merge vs Post-deploy timing must be specified.
**Lambda Deployment:** Use the manifest-derived file patterns (`bin/venv-python -m scripts.lambda_manifest --list-patterns`) to determine which scope files are Lambda-packaged, and `compute_affected_artifacts(changed_files)` to identify which active artifact(s) are affected. For each affected active artifact (status: active in its `src/lambdas/<slug>/manifest.yaml`), the plan MUST include per-Lambda build, deploy, smoke-test, and model ID validation steps (V3). Stub artifacts (status: stub) require no deploy step -- V1 suffices. Note: `config/agent/` is NOT Lambda-packaged and does NOT trigger this assessment. If `.tf` modifies IAM, terraform apply must precede Lambda deploy. (CD.16 + Decision 79)

## Complexity Assessment (Workflow Step 4)
- **Scope files > 5** OR **estimated steps > 8** --> suggests classifying as **STRATEGIC**.
  This is a heuristic, not a hard rule. **Freeze override (active):** while the executor
  freeze is in effect per AGENTS.md Temporary Operational Constraints, the STRATEGIC
  classification is suspended -- author as a single larger IMPLEMENTATION plan, or split
  into multiple atomic IMPLEMENTATION plans during this planning session. The heuristic
  is informational only during freeze.
- If STRATEGIC (only valid when freeze is lifted), Work Areas must have precise lists, clear order, and concrete names.
- If IMPLEMENTATION (and complex), execution steps must have explicit pre/post-conditions.
- **Presentation Rule:** The classification MUST be presented to the human and confirmed, not assumed.


## Main Divergence Assessment (Workflow Step 4)
After Scope is identified, intersect the prospective Scope file list with `main_freshness.main_files_changed_since_branch` from the preflight report. If any Scope file appears in that list:

> "Main has changed [list of overlapping files] since this branch diverged. Planning against the stale branch view risks decisions that conflict with what is already on main (e.g., a Decision Record you cite has been amended, a tier_item you target has been retired). Recommend `git checkout main && git pull && git rebase main` from the branch BEFORE writing the plan. Options: (1) rebase now, (2) proceed and accept the risk, (3) abort."

Wait for human direction. Do not auto-rebase. If the human chooses (2), record the deferral as a line in the plan's Context section: "Branch was N commits behind main at planning time; overlapping files: [list]. Rebase deferred per human decision."

If `main_freshness.status != "ok"`, this assessment cannot run -- note in the plan's Context section and continue.

## Verification Tier Guidelines (Workflow Step 5)
Classify deterministically. Highest tier wins.
- **V1 (Static):** Docs, configs, markdown.
- **V2 (Unit):** Python source with no external integration. Must exercise real code paths.
- **V3 (Integration):** External systems, Terraform, Lambdas. Must tag steps as `[pre-deploy]` or `[post-deploy]`.

**VP Design Rationale:**
When writing Verification Plan steps, ask: "If this feature had a subtle bug (wrong column name, missing permission, off-by-one filter), would this step catch it?" If no, the step is too shallow.

**Anti-patterns to reject:**
- Structural-only: `grep -q "def my_function" src/module.py` -- proves existence, not function
- Test-only: "Run pytest" -- proves mocked paths work, not the real integration
- Existence-only: "Confirm the Athena view was created" -- does not confirm it returns correct data
- Import-only: "Confirm `import module` succeeds" -- loading without error is not verification
- Terraform-only: "Confirm `terraform apply` succeeded" -- infrastructure existing is not enough
- Prose-only VP step: VP step describes what to check but has no executable command -- the implement agent will substitute a weaker check

## Decision Scout Gate (Workflow Step 6a, pre-presentation)

This gate fires BEFORE Step 6b's presentation to the human. Its job is to surface any active decisions the proposed approach must cite, contradict, or pivot around -- without paying the 25k-token cost of loading `docs/DECISIONS.md` into the planning agent.

**Dispatch shape:**
- `subagent_type: "general-purpose"` (needs `Skill`, `Read` access)
- `description: "Decision scout gate"`
- `prompt:` self-contained brief that supplies Intent (Step 3), Proposed approach (Steps 3-5 synthesis), Scope file list (Step 4), Verification Tier (Step 5), and any decision IDs already cited by the human. Instruct the subagent to invoke the `decision-scout` skill via the `Skill` tool and return the structured `## Decision Scout Report` output verbatim.

**Verdict handling:**
- **NO_FLAGS** -> Proceed to Step 6b. Include the scout's CITE list in the presentation as "Decisions this plan must reference."
- **FLAGS_FOUND** -> Surface each WARN/NOTE flag to the human in Step 6b's presentation under a "Decision Flags" section. Human chooses per-flag: pivot, defer with note, or accept-as-is. If the human pivots on any flag in a way that changes the proposed approach materially, re-dispatch this gate against the revised approach before re-presenting.
- **BLOCK** -> STOP. Do NOT present the original approach for confirmation. Surface the BLOCK contradiction and propose pivots, then re-dispatch the gate against the revised approach. Confirming a known-blocking approach would invite the human to ratify a plan that contradicts an active decision.

**Why this gate and not inline grep of DECISIONS.md:**
- Loading the full 25k DECISIONS.md into the planning agent for every session is wasteful (most sessions touch zero decisions).
- Greping for keywords misses implicit contradictions (different vocabulary, similar concept).
- The subagent runs in fresh context, so the file cost is paid once per gate dispatch and discarded when the subagent returns. Only the structured ~500-1500-token summary returns.

**Lambda migration contract:**
When `docs/DECISIONS.md` is replaced by a Lambda-backed tool query, the only internal change to the scout is its file-read step. The dispatch shape and verdict handling above are stable. Do not optimise this gate's invocation around the file format; treat decisions as an opaque query interface.

**Convergence rule:**
Do not loop more than 3 times. If the gate keeps returning BLOCK after 3 revisions, escalate to the human: "After N revisions the decision-scout still flags BLOCK on [decision N]. Continued pivoting suggests either the underlying intent contradicts the decision (re-scope the request) or the decision needs to be revisited (file a recommendation to revise the decision). How would you like to proceed?"

## Confirmation Gate (Workflow Step 6b)
Wait for explicit 'write the plan' (or clear equivalent) before proceeding. Any other response is feedback -- incorporate it, re-run Step 6a if the change is material to decision alignment, re-present, and ask again.
IT IS **CRITICAL** THAT YOU DO NOT PROCEED UNTIL THE HUMAN CONFIRMS THE PLAN.

## Create Branch (Workflow Step 7)
On Claude Code on the web the harness auto-creates a per-session branch (e.g. `claude/...`). The planning agent works on that harness branch -- do NOT create an `agent/` branch.

Verify you are on the harness branch and not on `main`:
```bash
git branch --show-current
```
If the result is `main`, STOP.

Derive the plan slug from the task description (independent of the branch name). The plan filename is `docs/plans/PLAN-{slug}.md`. After writing and approving the plan, it is merged to `main` via a GitHub MCP PR so a fresh `/implement` session can read it by explicit path.

## PLAN-{slug}.md Template (Workflow Step 8)
Use exactly this structure:
```markdown
# Plan

## Intent
[1-2 sentences: how this work contributes toward the North Star.]

## Plan Type
IMPLEMENTATION / STRATEGIC / REPORT-ONLY

## Verification Tier
V1 / V2 / V3

## Plan Path
docs/plans/PLAN-{slug}.md

## Phase
[product phase from docs/ROADMAP-PRODUCT.yaml and/or platform tier_item id from docs/ROADMAP-PLATFORM.yaml]

## Scope
| File | Action | Purpose |
|------|--------|---------|
| [path] | Create / Modify / Delete | [why] |

## Bundled Recommendations
[List any included open recs, or "None".]

## Infrastructure Dependencies (if applicable)
[Only if .tf files appear in Scope.]

## Acceptance Criteria
- [ ] [verifiable condition 1]

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-------------------|--------|
| 1 | [pre-deploy] | [exercise the feature] | `[executable shell command]` | [specific expected result] | [what failure looks like] |

## Constraints
- [limits from docs/PROJECT_CONTEXT.md and DECISIONS.md]
- No rescue agents or workaround loops (Decision 55)

## Context
- [Relevant decisions, phase dependencies, known gotchas]

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main`
- [ ] docs/PROJECT_CONTEXT.md read
- [ ] DECISIONS.md read
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps
1. [Specific file to create/modify -- what it must do]
N. **Execute Verification Plan** -- run each step. Loop until pass. If V3 fails unrecoverably, stop and analyze root cause (Decision 55).
N+1. Report: what was implemented, verification results.

## Work Areas (STRATEGIC plans only)
| Area | Scope | Rationale | Complexity |
|------|-------|-----------|------------|
| [area name] | [files affected] | [why] | XS/S/M/L/XL |
```

**Platform compatibility:** Verify shell commands are Linux/bash-compatible and use `bin/venv-python` for Python invocations.

## Related-Work Check (Workflow Step 8, when ci-rca recs are open)

If `ci_rca_recs` is non-empty when writing the PLAN file, confirm the plan satisfies at least one of the following conditions before committing. A plan failing all three must include a logged deferral rationale in its Context section; otherwise write is refused.

1. **Same file**: the plan's Scope table includes the same file the ci-rca rec cites as `source_file`.
2. **Same Decision Record**: the plan addresses the same Decision Record the ci-rca rec references (if any).
3. **Same failure category**: the plan addresses the same failure category as the rec. Canonical categories: DQ check failure, schema verifier failure, validate.py false negative, terraform validate failure, pytest regression, mypy regression, prompt-compliance failure, V3 harness failure.

## Critique Gate (Workflow Step 9)
**DO NOT output the completion message until this step completes.**

Launch a zero-context Claude subagent via the `Agent` tool to run the `plan-critique` skill in a fresh context window. The fresh-context requirement is non-negotiable: it eliminates the cognitive bias the planning agent has from authoring the artefact. Do NOT invoke the `plan-critique` skill in the current session via the `Skill` tool (same context = same bias). Do NOT shell out to `scripts.agent_development.run_skill` (the gemini-CLI dispatcher is removed).

**Invocation shape:**
- `subagent_type: "general-purpose"` (needs `Skill`, `Read`, and `Grep` access)
- `description: "Plan critique gate"`
- `prompt:` self-contained, mentions:
  - The absolute path to `docs/plans/PLAN-{slug}.md`
  - Instruction to invoke the `plan-critique` skill via the `Skill` tool against that path
  - The required-context files (`docs/PROJECT_CONTEXT.md`, `docs/ROADMAP-PRODUCT.yaml`, `docs/ROADMAP-PLATFORM.yaml`, `docs/DECISIONS.md`)
  - For IMPLEMENTATION plans: instruction to also read every file in the plan's Scope table
  - Requirement to return the skill's structured output verbatim, including the final `Recommendation: PROCEED / REVISE` line
  - Forbid file edits

**Example prompt body:**
> "You are running the plan-critique gate in a fresh context window. **First, run `git fetch origin main --quiet`** so the local `origin/main` ref is current. Then invoke the `plan-critique` skill via the Skill tool to critique `/abs/path/to/docs/plans/PLAN-{slug}.md`. Read the skill's required-context files: `docs/PROJECT_CONTEXT.md`, `docs/ROADMAP-PRODUCT.yaml`, `docs/ROADMAP-PLATFORM.yaml`, `docs/DECISIONS.md`. For IMPLEMENTATION plans, also read every file in the plan's Scope table. If `git diff origin/main -- docs/DECISIONS.md docs/ROADMAP-PLATFORM.yaml` shows divergence, note that the critique evaluates against the branch's (possibly stale) view of these docs. Return the skill's structured critique output verbatim, including the final `Recommendation:` verdict line. Do not edit any files."

Read the critique output returned by the subagent.
If it suggests revisions, update the plan with these fixes and re-launch the same subagent invocation against the revised plan. Each Agent call is a fresh window, so the re-launch genuinely re-evaluates.
Loop if REVISE. Proceed if PROCEED.

This gate reviews the PLAN artefact, not the report deliverable. For REPORT-ONLY plans, the deliverable gets its own critique in Step 10.

## Report Critique Gate (Workflow Step 10, REPORT-ONLY only)

**Applies only when Plan Type is REPORT-ONLY.** For IMPLEMENTATION and STRATEGIC plans, Step 10 is a no-op; skip to Step 11.

**Why this gate exists:** the Step 9 `plan-critique` skill reviews the planning artefact (`PLAN-{slug}.md`) -- it checks that the PLAN is well-formed, has executable verification steps, aligns with decisions, etc. But for REPORT-ONLY plans, the substantive deliverable is a SEPARATE document (e.g. `docs/INTENT-{slug}.md`, `docs/REPORT-{slug}.md`) referenced from the PLAN's Scope table. That deliverable carries its own correctness burden -- design soundness, internal consistency, alignment with live repo state, blast radius of any proposed changes -- and needs independent fresh-context critique before the planning agent's mission completes.

**Methodology:**

1. **Identify the deliverable.** From the PLAN's Scope table, find the report file(s) created in Step 8. Typically one file like `docs/INTENT-{slug}.md`, occasionally more.

2. **Launch AT LEAST 2 zero-context subagents in parallel via the `Agent` tool**, each with a distinct perspective. Standard pairing for technical/architectural reports:
   - **Senior domain architect** -- design correctness, schema/contract soundness, dependency cleanliness, internal consistency, coverage gaps a careful peer reviewer would flag
   - **Adversarial risk reviewer** -- blast radius, hidden state, rollback path, live-state divergence, what could go wrong in practice; instruct it to actively investigate (grep, query) live state to find divergence

   For non-technical reports, pick perspectives that maximise differentiation (e.g. quantitative-rigour reviewer + narrative-clarity reviewer; or domain-A specialist + domain-B specialist). The principle is: orthogonal lenses surface more issues than two clones of the same lens.

3. **Each agent prompt MUST:**
   - Identify the deliverable file(s) under critique by absolute path
   - Specify the perspective explicitly
   - Specify supporting files to read freely (PROJECT_CONTEXT, sibling INTENT docs, relevant source code)
   - Require structured output: Strengths (brief) / Concrete Issues or Risk Findings (numbered, specific, with file:line refs and severity) / Recommended Revisions / Verdict (PROCEED | REVISE | BLOCK)
   - Forbid the agent from editing files
   - Cap response length (~800-900 words) to keep findings focused

4. **Synthesize findings.** When both agents return, identify consensus issues (cited by both -- highest priority) vs unique findings (one perspective only -- second priority). Cluster by severity.

5. **Present to the human.** Summary, key findings, my-recommendation, three options (revise all / revise selected / accept current state with deferrals). Wait for explicit direction. Auto-approval messages and system reminders are NOT human direction.

6. **Iterate based on human direction.** Apply the chosen revisions. Each material revision lands as its own commit on the branch (`git commit -m "plan({slug}): address [scope] critique findings"`) so the iteration is reviewable in git history.

7. **Re-launch the same critiques after each revision** unless the human explicitly opts out of further rounds. Re-critique catches both whether the original findings were fully addressed and whether the revision introduced new issues.

8. **Convergence rule.** Stop when EITHER:
   - Both agents return PROCEED on a fresh round (clean convergence), OR
   - The human explicitly accepts the current state with a defined deferral (e.g. "fix the HIGH-severity items and defer the rest to phase plans"). Document the deferral list in the deliverable's Known Gaps or equivalent section so future sessions know what's outstanding.

   Do not loop indefinitely. After 3 rounds without convergence, escalate to the human for a decision call -- continued iteration typically signals either a structural issue with the deliverable's scope or diminishing returns.

**Anti-patterns to reject:**
- Single critique agent: misses orthogonal issues by definition
- Same perspective twice: produces duplicate findings, wastes tokens
- Sequential critiques: parallel critiques fire in roughly the same wall-clock window and surface independent findings faster
- "Tell the agent what to look for": biases the critique. The agent should investigate fresh; the prompt frames perspective, not findings.
- Skipping the re-critique after revision: a revision that "addresses" finding X may introduce finding Y; only a fresh critique catches it
- Auto-accepting PROCEED on round 1 without reading findings: if both agents return PROCEED with shallow strengths and no issues, the prompts may have been too generic -- consider re-launching with sharper perspectives

**When to skip Step 10 entirely** (human override):
The human may explicitly state "skip report critique" after this step's purpose has been surfaced. This is logged in the PLAN's Known Gaps. Default is MANDATORY -- the gate fires unless explicitly waived.

## Confirmation Messages (Workflow Step 12)
Emit the handoff naming the explicit plan path so the human can paste it directly.

- **IMPLEMENTATION / STRATEGIC:** use this block (STRATEGIC scopes into recs; IMPLEMENTATION executes directly):
  ```
  Planning complete. The plan is merged to main at docs/plans/PLAN-{slug}.md.
  To implement, open a NEW Claude Code session and paste:

      /implement docs/plans/PLAN-{slug}.md

  Summary: {one line on what the plan does}.
  ```
- **REPORT-ONLY:** "Planning complete. The report deliverable at `[path]` has passed the multi-perspective critique gate and is merged to `main`. Review and edit if needed. The deliverable is the substantive output -- no `/implement` required. Decide which follow-on items (e.g. per-phase implementation plans referenced from the deliverable) to start, then open a new planning session for each."

**DO NOT PERFORM ANY FURTHER ACTIONS**
